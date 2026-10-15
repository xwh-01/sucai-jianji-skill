"""Synthetic workflow tests. No real footage, cloud requests or renders."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from pipeline import workflow as w
from tests.test_validate_edit_plan import fixture


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.run = self.root / "run"
        self.skill = patch.object(w, "skill_fingerprint", return_value={"rules": "frozen"})
        self.skill.start()
        self.addCleanup(self.skill.stop)
        script = self.root / "script.txt"
        script.write_text("Synthetic script")
        sources = [{"path": str(script), "role": "script"}]
        for episode in (1, 2, 3, 4):
            path = self.root / f"EP{episode}.mp4"
            path.write_bytes(f"Synthetic episode {episode}".encode())
            sources.append({"path": str(path), "role": "video", "episode": episode})
        executable = self.root / "fake-tool"
        executable.write_text("Synthetic, not executable media tooling")
        executable.chmod(0o700)
        self.config = {"language": "en", "scope": {"kind": "pre_paywall", "episodes": [1, 2, 3, 4], "paywall": "After EP4"},
                       "sources": sources, "tools": {k: {"path": str(executable), "version": "test"}
                                                    for k in ("ffmpeg", "ffprobe", "swiftc", "mediakit")}}
        w.initialize(self.run, self.config)
        self.state = w.read(self.run / "workflow.json")
        base = w.read(w.ROOT / "references/validated-example.json")
        base["scope"] = {"kind": "pre_paywall", "episodes": [1, 2, 3, 4]}
        base["variants"][1]["context_entry_decision"].update(fixture())
        self.plans = {}
        for index in range(1, 4):
            plan = deepcopy(base)
            identifier = f"opening-{index}"
            plan["selected_opening"].update(candidate_id=identifier, event_anchor=f"Synthetic event {index}", source_video=str(self.root / f"EP{index}.mp4"), episode=index)
            for variant in plan["variants"]:
                for item in variant["ranges"]:
                    item.update(source_video=str(self.root / f"EP{index}.mp4"), episode=index)
                variant["end_hold"]["audio"] = {"kind": "silence"}
            self.assertEqual(w.validate_plan(plan), [])
            self.plans[identifier] = plan

    def prepare(self, stage):
        w.begin(self.run, self.state, stage)
        _, base = w.active(self.run, self.state, stage)
        (base / "evidence.txt").write_text("Synthetic test evidence, not an actual video review.")
        receipt = {"artifacts": {}, "checks": {k: {"status": "passed", "evidence": ["evidence.txt"]} for k in w.required_checks(self.state, stage)},
                   "limitations": ["Synthetic test only"]}
        if stage == "intake":
            w.write(base / "manifest.json", {"scope": self.state["config"]["scope"], "sources": self.state["config"]["sources"]})
            receipt["artifacts"]["manifest"] = "manifest.json"
        elif stage == "index":
            entries = []
            for source in self.state["config"]["sources"]:
                if source["role"] != "video":
                    continue
                h = source["sha256"]
                w.register_task(self.state, h, None)
                task_id = "synthetic-" + str(source["episode"])
                w.register_task(self.state, h, task_id)
                entries.append({"source_sha256": h, "language": "en", "provider": "mediakit-cloud", "task_id": task_id,
                                "status": "succeeded", "raw": "evidence.txt", "terminal": "evidence.txt", "normalized": "evidence.txt"})
            w.write(base / "index.json", {"transcripts": entries})
            receipt["artifacts"]["index"] = "index.json"
        elif stage == "openings":
            w.write(base / "selected.json", {"selected_openings": [p["selected_opening"] for p in self.plans.values()]})
            receipt["artifacts"].update(selected="selected.json", candidates="evidence.txt")
        elif stage in ("story", "boundaries", "packaging"):
            receipt["artifacts"]["plans"] = {}
            receipt["artifacts"]["boundaries"] = {}
            receipt["artifacts"]["baselines"] = {}
            for identifier, original in self.plans.items():
                plan = deepcopy(original)
                if stage != "packaging":
                    for variant in plan["variants"]:
                        for field in ("opening_headline", "reset_transition", "end_hold"):
                            variant.pop(field, None)
                w.write(base / (identifier + ".json"), plan)
                receipt["artifacts"]["plans"][identifier] = identifier + ".json"
                if stage == "packaging":
                    for variant in plan["variants"]:
                        key = identifier + "." + variant["id"]
                        name = key + "-recipe.json"
                        w.write(base / name, {"ranges": variant["ranges"],
                                             "video": {"width": 404, "height": 720, "fps": "30/1"},
                                             "audio": {"sample_rate": 48000, "channels": 2},
                                             "encoding": {"-c:v": "libx264", "-c:a": "aac"}})
                        receipt["artifacts"]["baselines"][key] = name
                if stage == "boundaries":
                    name = identifier + "-boundary.json"
                    w.write(base / name, {"locked_boundaries": w.boundary_lock(plan), "evidence": ["evidence.txt"]})
                    receipt["artifacts"]["boundaries"][identifier] = name
        elif stage == "render":
            for key in self.state["stages"][stage]["jobs"]:
                job = w.job_begin(self.run, self.state, key)
                (self.run / job["directory"] / "output.m4v").write_bytes(("Synthetic media " + key).encode())
                w.job_finish(self.run, self.state, key, "output.m4v", runner_completed=True)
        elif stage == "review":
            reviewed = {}
            def inspect(path, variant, tools):
                duration = sum(r["end"] - r["start"] for r in variant["ranges"]) + 1
                if variant["id"] == "cold_open":
                    duration += 3.8
                return {"probe": {"format": {"duration": str(duration)}}, "checks": {k: True for k in
                        ("full_decode", "av_tracks", "non_silent_audio", "duration", "orientation", "frame_rate")}}
            with patch("pipeline.media_checks.inspect", side_effect=inspect):
                reports = w.inspect_outputs(self.run, self.state)
            for key, job in self.state["stages"]["render"]["jobs"].items():
                if not key.endswith(".end"):
                    continue
                report = reports[key]
                content = w.read(base / report["content_template"])
                content["reviewer"] = "Synthetic reviewer, no real media review implied"
                for window in content["windows"].values():
                    window.update(status="passed", observation="Synthetic observation for state-machine testing only", evidence=["evidence.txt"])
                w.write(base / report["content_template"], content)
                reviewed[key] = {"sha256": job["sha256"], "technical": "passed", "targeted_content": "passed",
                                 "continuous_viewing": "not_performed", "limitations": ["Synthetic test only"],
                                 "technical_evidence": report["path"], "content_evidence": report["content_template"]}
            w.write(base / "review.json", {"outputs": reviewed})
            receipt["artifacts"]["review"] = "review.json"
        w.write(base / "receipt.json", receipt)
        return base, receipt

    def through(self, last):
        for stage in w.STAGES[:w.STAGES.index(last) + 1]:
            self.prepare(stage)
            w.finish(self.run, self.state, stage, "receipt.json")

    def configure_run(self, count, enabled):
        self.run = self.root / f"run-{count}-{enabled}"
        w.initialize(self.run, {**self.config, "opening_count": count, "cold_open_enabled": enabled})
        self.state = w.read(self.run / "workflow.json")
        originals = list(self.plans.values())
        self.plans = {}
        for index in range(count):
            plan = deepcopy(originals[index % len(originals)])
            identifier = f"selected-{index}"
            plan["selected_opening"].update(candidate_id=identifier, event_anchor=f"Distinct synthetic event {index}")
            plan["cold_open_enabled"] = enabled
            if not enabled:
                plan["variants"] = [v for v in plan["variants"] if v["id"] == "continuous"]
                plan["cold_open_eligibility"] = {"status": "not_evaluated", "reason_code": "disabled_by_user",
                                                 "reason": "Disabled for this synthetic run"}
            self.plans[identifier] = plan

    def test_configurable_counts_and_modes_through_delivery(self):
        originals = deepcopy(self.plans)
        for count, enabled in ((1, True), (1, False), (2, False), (4, True)):
            with self.subTest(count=count, enabled=enabled):
                self.plans = deepcopy(originals)
                self.configure_run(count, enabled)
                self.through("review")
                w.verify(self.run, self.state)
                jobs = self.state["stages"]["render"]["jobs"]
                outputs = count * (2 if enabled else 1)
                self.assertEqual(sum(k.endswith(".end") for k in jobs), outputs)
                self.assertEqual(sum(k.endswith(".rewind") for k in jobs), count if enabled else 0)
                delivery = w.package(self.run, self.state)
                with zipfile.ZipFile(self.run / delivery["directory"] / "ads.zip") as archive:
                    self.assertEqual(len(archive.namelist()), outputs + 1)

    def test_enabled_does_not_force_ineligible_variant(self):
        self.configure_run(2, True)
        plan = next(iter(self.plans.values()))
        plan["variants"] = [v for v in plan["variants"] if v["id"] == "continuous"]
        plan["cold_open_eligibility"].update(eligible=False, reason_code="no_prior_context",
                                             reason="No prior context in this synthetic fixture")
        plan["cold_open_eligibility"]["checks"]["prior_context_exists"] = False
        self.through("review")
        jobs = self.state["stages"]["render"]["jobs"]
        self.assertEqual(sum(k.endswith(".end") for k in jobs), 3)
        self.assertEqual(sum(k.endswith(".rewind") for k in jobs), 1)
        delivery = w.package(self.run, self.state)
        with zipfile.ZipFile(self.run / delivery["directory"] / "ads.zip") as archive:
            self.assertEqual(len(archive.namelist()), 4)

    def test_plan_option_requires_boolean(self):
        self.configure_run(1, False)
        plan = next(iter(self.plans.values()))
        for value in (0, 1, "off", None):
            plan["cold_open_enabled"] = value
            self.assertIn("cold_open_enabled must be boolean", w.validate_plan(plan))

    def test_defaults_and_legacy_options(self):
        self.assertEqual(w.run_options({}), {"opening_count": 3, "cold_open_enabled": True})
        self.state.pop("run_options")
        self.state["config"].pop("opening_count")
        self.state["config"].pop("cold_open_enabled")
        w.verify(self.run, self.state)

    def test_invalid_options_do_not_create_run(self):
        for value in (0, -1, True, 1.5, "2", None):
            with self.subTest(count=value), self.assertRaisesRegex(ValueError, "opening_count"):
                w.initialize(self.root / "bad-run", {**self.config, "opening_count": value})
        for value in (0, 1, "off", None):
            with self.subTest(enabled=value), self.assertRaisesRegex(ValueError, "cold_open_enabled"):
                w.initialize(self.root / "bad-run", {**self.config, "cold_open_enabled": value})
        self.assertFalse((self.root / "bad-run").exists())

    def test_wrong_count_is_rejected_at_selection_and_plans(self):
        self.configure_run(1, True)
        self.through("index")
        base, receipt = self.prepare("openings")
        selected = w.read(base / "selected.json")
        selected["selected_openings"].append(deepcopy(selected["selected_openings"][0]))
        w.write(base / "selected.json", selected)
        with self.assertRaisesRegex(ValueError, "1 distinct"):
            w.finish(self.run, self.state, "openings", "receipt.json")
        selected["selected_openings"].pop()
        w.write(base / "selected.json", selected)
        w.finish(self.run, self.state, "openings", "receipt.json")
        base, receipt = self.prepare("story")
        receipt["artifacts"]["plans"] = {}
        w.write(base / "receipt.json", receipt)
        with self.assertRaisesRegex(ValueError, "Exactly 1"):
            w.finish(self.run, self.state, "story", "receipt.json")

    def test_disabled_mode_rejects_cold_variant_and_fake_assessment(self):
        original_cold = deepcopy(next(iter(self.plans.values()))["variants"][1])
        self.configure_run(1, False)
        self.assertEqual(w.required_checks(self.state, "story"), ("continuous_paths", "cold_eligibility"))
        plan = next(iter(self.plans.values()))
        self.assertEqual(w.validate_plan(plan), [])
        plan["variants"].append(original_cold)
        self.assertTrue(w.validate_plan(plan))
        plan["variants"].pop()
        plan["cold_open_eligibility"]["eligible"] = False
        self.assertTrue(any("must not claim" in e for e in w.validate_plan(plan)))

    def test_plan_cannot_override_run_mode(self):
        self.configure_run(1, True)
        self.through("openings")
        next(iter(self.plans.values()))["cold_open_enabled"] = False
        self.prepare("story")
        with self.assertRaisesRegex(ValueError, "differs from run"):
            w.finish(self.run, self.state, "story", "receipt.json")

    def test_options_cannot_change_mid_run(self):
        self.state["config"]["opening_count"] = 1
        with self.assertRaisesRegex(ValueError, "Run options changed"):
            w.verify(self.run, self.state)

    def test_cli_overrides_and_status_report_options(self):
        config = self.root / "config.json"
        run = self.root / "cli-run"
        w.write(config, self.config)
        output = io.StringIO()
        with patch("sys.argv", ["workflow.py", str(run), "init", str(config), "--opening-count", "1", "--cold-open", "off"]), redirect_stdout(output):
            self.assertEqual(w.main(), 0)
        self.assertFalse(json.loads(output.getvalue())["cold_open_enabled"])
        output = io.StringIO()
        with patch("sys.argv", ["workflow.py", str(run), "status"]), redirect_stdout(output):
            self.assertEqual(w.main(), 0)
        self.assertEqual(json.loads(output.getvalue())["opening_count"], 1)

    def test_full_chain_packages_only_reviewed_files_and_seals(self):
        self.through("review")
        (self.run / "unreviewed.m4v").write_bytes(b"Do not deliver")
        w.verify(self.run, self.state)
        delivery = w.package(self.run, self.state)
        with zipfile.ZipFile(self.run / delivery["directory"] / "ads.zip") as archive:
            self.assertEqual(len(archive.namelist()), 7)
            self.assertNotIn("unreviewed.m4v", archive.namelist())
        self.assertEqual(w.package(self.run, self.state), delivery)
        with self.assertRaisesRegex(ValueError, "sealed"):
            w.revise(self.state, "packaging", "Try to overwrite")
        w.verify(self.run, self.state)

    def test_cannot_adopt_existing_directory(self):
        with self.assertRaisesRegex(ValueError, "new run directory"):
            w.initialize(self.run, self.config)

    def test_cannot_skip_stage(self):
        with self.assertRaisesRegex(ValueError, "prior stage"):
            w.begin(self.run, self.state, "render")

    def test_begin_is_idempotent(self):
        one = w.begin(self.run, self.state, "intake")
        two = w.begin(self.run, self.state, "intake")
        self.assertEqual(one["directory"], two["directory"])

    def test_missing_evidence_blocks_completion(self):
        base, receipt = self.prepare("intake")
        receipt["checks"]["authorized_scope"]["evidence"] = []
        w.write(base / "receipt.json", receipt)
        with self.assertRaisesRegex(ValueError, "evidence"):
            w.finish(self.run, self.state, "intake", "receipt.json")

    def test_source_change_invalidates_reuse(self):
        Path(self.config["sources"][0]["path"]).write_text("Different source")
        with self.assertRaisesRegex(ValueError, "Source/tool changed"):
            w.verify(self.run, self.state)

    def test_locked_artifact_change_is_rejected(self):
        self.through("intake")
        w.artifact(self.run, self.state, "intake", "manifest").write_text("{}")
        with self.assertRaisesRegex(ValueError, "Locked artifacts changed"):
            w.verify(self.run, self.state)

    def test_skill_change_is_rejected(self):
        self.state["skill"] = {"rules": "other"}
        with self.assertRaisesRegex(ValueError, "Skill changed"):
            w.verify(self.run, self.state)

    def test_asr_reservation_prevents_blind_resubmission(self):
        self.through("intake")
        w.begin(self.run, self.state, "index")
        h = self.state["config"]["sources"][1]["sha256"]
        self.assertTrue(w.register_task(self.state, h, None)["submit_allowed"])
        self.assertFalse(w.register_task(self.state, h, None)["submit_allowed"])
        w.register_task(self.state, h, "task-one")
        with self.assertRaisesRegex(ValueError, "already exists"):
            w.register_task(self.state, h, "task-two")

    def test_revision_preserves_files_and_upstream(self):
        self.through("packaging")
        old = deepcopy(self.state["stages"])
        result = w.revise(self.state, "packaging", "Change title contrast only")
        self.assertEqual(result["invalidated"], ["packaging"])
        self.assertEqual(self.state["stages"]["boundaries"], old["boundaries"])
        self.assertTrue((self.run / old["packaging"]["directory"]).is_dir())
        new = w.begin(self.run, self.state, "packaging")
        self.assertNotEqual(new["directory"], old["packaging"]["directory"])

    def test_packaging_cannot_change_story(self):
        self.through("boundaries")
        base, receipt = self.prepare("packaging")
        path = base / receipt["artifacts"]["plans"]["opening-1"]
        plan = w.read(path)
        plan["variants"][0]["ending_hook"] = "A different story stop"
        w.write(path, plan)
        with self.assertRaisesRegex(ValueError, "Narrative changed"):
            w.finish(self.run, self.state, "packaging", "receipt.json")

    def test_packaging_cannot_change_frame_times(self):
        self.through("boundaries")
        base, receipt = self.prepare("packaging")
        path = base / receipt["artifacts"]["plans"]["opening-1"]
        plan = w.read(path)
        plan["variants"][0]["ranges"][0]["start"] += 0.1
        w.write(path, plan)
        with self.assertRaisesRegex(ValueError, "locked boundaries"):
            w.finish(self.run, self.state, "packaging", "receipt.json")

    def test_no_early_headline(self):
        self.through("openings")
        base, receipt = self.prepare("story")
        path = base / receipt["artifacts"]["plans"]["opening-1"]
        plan = w.read(path)
        plan["variants"][0]["opening_headline"] = {}
        w.write(path, plan)
        with self.assertRaisesRegex(ValueError, "before all boundaries"):
            w.finish(self.run, self.state, "story", "receipt.json")

    def test_job_dependencies_and_retry_use_clean_upstream(self):
        self.through("packaging")
        w.begin(self.run, self.state, "render")
        with self.assertRaisesRegex(ValueError, "upstream"):
            w.job_begin(self.run, self.state, "opening-1.continuous.headline")
        baseline = w.job_begin(self.run, self.state, "opening-1.continuous.baseline")
        (self.run / baseline["directory"] / "base.mp4").write_bytes(b"synthetic")
        w.job_finish(self.run, self.state, "opening-1.continuous.baseline", "base.mp4", runner_completed=True)
        first = deepcopy(w.job_begin(self.run, self.state, "opening-1.continuous.headline"))
        self.state["stages"]["render"]["jobs"]["opening-1.continuous.headline"]["status"] = "failed"
        retry = w.job_begin(self.run, self.state, "opening-1.continuous.headline")
        self.assertEqual(first["input"], retry["input"])
        self.assertNotEqual(first["directory"], retry["directory"])

    def test_rejects_traversal_and_symlinks(self):
        with self.assertRaises(ValueError):
            w.inside(self.run, "../outside")
        (self.run / "linked").symlink_to(self.root)
        with self.assertRaises(ValueError):
            w.inside(self.run, "linked/script.txt")

    def test_failed_review_blocks_delivery(self):
        self.through("render")
        base, receipt = self.prepare("review")
        path = base / receipt["artifacts"]["review"]
        review = w.read(path)
        next(iter(review["outputs"].values()))["targeted_content"] = "failed"
        w.write(path, review)
        with self.assertRaisesRegex(ValueError, "review failed"):
            w.finish(self.run, self.state, "review", "receipt.json")
        with self.assertRaisesRegex(ValueError, "Complete review"):
            w.package(self.run, self.state)

    def test_wrapper_uses_locked_timing_text_and_silent_fallback(self):
        plan = self.plans["opening-1"]
        command = w.wrapper_command(plan, "cold_open", "rewind", "exe", "input", "output")
        self.assertEqual(command[command.index("--pre-freeze-duration") + 1], "0.8")
        self.assertEqual(command[command.index("--source-position") + 1], "after")
        command = w.wrapper_command(plan, "continuous", "end", "exe", "input", "output")
        self.assertEqual(command[command.index("--audio-mode") + 1], "silence")
        self.assertNotIn("--sound-video", command)

    def test_baseline_rejects_overwrites_extra_outputs_and_unregistered_sources(self):
        for argv in (["-y", "{output}"], ["-i", "source", "old.mp4", "{output}"],
                     ["-i", "other", "{output}"], ["-i", "source", "old.mp4"]):
            with self.subTest(argv=argv), self.assertRaises(ValueError):
                w.baseline_command({"argv": argv}, "ffmpeg", "new.mp4", {"source"})

    def test_execute_uses_saved_recipe_and_reuses_completed_output(self):
        self.through("packaging")
        w.begin(self.run, self.state, "render")
        w.write(self.run / "workflow.json", self.state)
        def run(command, **kwargs):
            Path(command[-1]).write_bytes(b"Synthetic execution output")
        with patch.object(w, "verify_sources", return_value={}), patch.object(w.subprocess, "run", side_effect=run) as process:
            first = w.execute_wrap(self.run, "opening-1.continuous.baseline")
            second = w.execute_wrap(self.run, "opening-1.continuous.baseline")
            self.assertEqual(process.call_count, 1)
            self.assertTrue(second["reused"])
            self.assertEqual(first["sha256"], second["sha256"])

    def test_title_revision_reuses_unaffected_render_steps(self):
        self.through("render")
        original = deepcopy(self.state["stages"]["render"]["jobs"])
        w.revise(self.state, "packaging", "Adjust one opening title only")
        for variant in self.plans["opening-1"]["variants"]:
            variant["opening_headline"]["lines"][2] = "A DIFFERENT RETENTION LINE"
        self.prepare("packaging")
        w.finish(self.run, self.state, "packaging", "receipt.json")
        w.begin(self.run, self.state, "render")
        jobs = self.state["stages"]["render"]["jobs"]
        for key, job in jobs.items():
            changed = key.startswith("opening-1.") and key.endswith((".headline", ".end"))
            self.assertEqual(job["status"], "pending" if changed else "completed", key)
            if not changed:
                self.assertEqual(job["output"], original[key]["output"])
        w.verify(self.run, self.state)

    def test_completed_render_can_be_called_again_without_execution(self):
        self.through("render")
        w.write(self.run / "workflow.json", self.state)
        with patch.object(w.subprocess, "run") as process:
            results = w.render_all(self.run)
            self.assertTrue(all(r["reused"] for r in results.values()))
            process.assert_not_called()

    def test_handwritten_or_edited_technical_report_cannot_pass(self):
        self.through("render")
        base, receipt = self.prepare("review")
        reviewed = w.read(base / receipt["artifacts"]["review"])
        result = next(iter(reviewed["outputs"].values()))
        path = base / result["technical_evidence"]
        data = w.read(path)
        data["invented"] = "Handwritten success claim"
        w.write(path, data)
        with self.assertRaisesRegex(ValueError, "unchanged report generated by inspect"):
            w.finish(self.run, self.state, "review", "receipt.json")

    def test_manual_render_completion_cannot_bypass_plan_compiler(self):
        self.through("packaging")
        w.begin(self.run, self.state, "render")
        job = w.job_begin(self.run, self.state, "opening-1.continuous.baseline")
        (self.run / job["directory"] / "unrelated.m4v").write_bytes(b"Unrelated existing video")
        with self.assertRaisesRegex(ValueError, "manual completion"):
            w.job_finish(self.run, self.state, "opening-1.continuous.baseline", "unrelated.m4v")

    def test_frame_only_review_cannot_pass_as_continuous_playback(self):
        self.through("render")
        base, receipt = self.prepare("review")
        reviewed = w.read(base / receipt["artifacts"]["review"])
        result = next(iter(reviewed["outputs"].values()))
        path = base / result["content_evidence"]
        data = w.read(path)
        next(iter(data["windows"].values()))["mode"] = "frames"
        w.write(path, data)
        with self.assertRaisesRegex(ValueError, "Continuous audiovisual review is incomplete"):
            w.finish(self.run, self.state, "review", "receipt.json")

    def test_stale_plan_content_review_is_rejected(self):
        self.through("render")
        base, receipt = self.prepare("review")
        reviewed = w.read(base / receipt["artifacts"]["review"])
        result = next(iter(reviewed["outputs"].values()))
        path = base / result["content_evidence"]
        data = w.read(path)
        data["plan_sha256"] = "old-plan"
        w.write(path, data)
        with self.assertRaisesRegex(ValueError, "different video or plan"):
            w.finish(self.run, self.state, "review", "receipt.json")


if __name__ == "__main__":
    unittest.main()
