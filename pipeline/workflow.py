"""Evidence-gated workflow around the existing editorial and render behavior."""

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import re
import subprocess
import os
import uuid
import zipfile

from pipeline.validation import validate_plan, validate_disabled_cold_open
from pipeline.baseline import baseline_command, verify_sources
from pipeline.content_review import review_windows, validate_content


ROOT = Path(__file__).resolve().parents[1]
STAGES = ("intake", "index", "openings", "story", "boundaries", "packaging", "render", "review")
CHECKS = {
    "intake": ("authorized_scope", "input_completeness"),
    "index": ("source_language_provider", "transcript_duration"),
    "openings": ("full_script_comparison", "audience_evidence", "distinct_events"),
    "story": ("continuous_paths", "cold_eligibility", "context_search_coverage", "entry_comparison", "echo_and_new_suspense"),
    "boundaries": ("all_cuts_reviewed", "dialogue_action_integrity", "cross_episode_connections"),
    "packaging": ("headline_after_lock", "representative_frames", "end_audio_review"),
    "render": ("planned_steps_completed",),
    "review": ("plan_structure", "technical_media", "targeted_content_review"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run_options(config):
    count = config.get("opening_count", 3)
    enabled = config.get("cold_open_enabled", True)
    require(type(count) is int and count > 0, "opening_count must be a positive integer")
    require(type(enabled) is bool, "cold_open_enabled must be boolean")
    return {"opening_count": count, "cold_open_enabled": enabled}


def required_checks(state, stage):
    if stage == "story" and not run_options(state["config"])["cold_open_enabled"]:
        return ("continuous_paths", "cold_eligibility")
    return CHECKS[stage]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def inside(base, relative):
    require(isinstance(relative, str) and relative, "Expected a nonempty relative path")
    rel = Path(relative)
    require(not rel.is_absolute() and ".." not in rel.parts, "Path must stay inside its attempt")
    path = base / rel
    require(not any(p.is_symlink() for p in (path, *path.parents)), "Symlinks are not accepted in run artifacts")
    require(path.resolve().is_relative_to(base.resolve()), "Artifact escapes its attempt")
    return path


def snapshot(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        require(not path.is_symlink(), "Run artifacts must not be symlinks")
        if path.is_file():
            result[str(path.relative_to(directory))] = digest(path)
    return result


def skill_fingerprint():
    paths = [ROOT / "SKILL.md"]
    for directory in ("pipeline", "scripts", "references", "bin"):
        paths.extend(p for p in (ROOT / directory).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(set(paths))}


def event(state, action, **details):
    state["events"].append({"at": datetime.now(timezone.utc).isoformat(), "action": action, **details})


def initialize(run, config):
    options = run_options(config)
    require(isinstance(config.get("language"), str) and config["language"], "language is required")
    scope = config.get("scope", {})
    require(scope.get("kind") == "pre_paywall" and scope.get("episodes") and scope.get("paywall"),
            "Explicit pre-paywall scope, episodes and paywall are required")
    sources = deepcopy(config.get("sources", []))
    require(sources and any(s.get("role") == "script" for s in sources), "Script source is required")
    require(any(s.get("role") == "video" for s in sources), "Video sources are required")
    for source in sources:
        path = Path(source["path"]).resolve(strict=True)
        require(path.is_file(), "Source must be a file")
        require(source.get("role") in ("script", "video", "suggestions"), "Unknown source role")
        if source["role"] == "video":
            require(source.get("episode") in scope["episodes"], "Video outside authorized episodes")
        source.update(path=str(path), sha256=digest(path))
    videos = [s for s in sources if s["role"] == "video"]
    require(len({s["episode"] for s in videos}) == len(videos), "Duplicate episode source")
    require(len({s["path"] for s in sources}) == len(sources), "Duplicate source path")
    tools = deepcopy(config.get("tools", {}))
    for name in ("ffmpeg", "ffprobe", "swiftc", "mediakit"):
        require(name in tools and tools[name].get("version"), "Record tool path and version: " + name)
        path = Path(tools[name]["path"]).resolve(strict=True)
        require(path.is_file() and os.access(path, os.X_OK), "Tool is not executable: " + name)
        tools[name].update(path=str(path), sha256=digest(path))
    require(not run.exists(), "Use a new run directory; existing runs and deliverables are never adopted in place")
    run.mkdir(parents=True)
    state = {"schema_version": 1, "config": {**config, **options, "sources": sources, "tools": tools},
             "run_options": options,
             "skill": skill_fingerprint(), "stages": {}, "tasks": {}, "events": [], "delivery": None}
    event(state, "initialized")
    write(run / "workflow.json", state)
    return {"run": str(run), "next": "intake", **options}


@contextmanager
def locked(run):
    require((run / "workflow.json").is_file(), "Not a managed run")
    with (run / ".workflow.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = read(run / "workflow.json")
        yield state
        write(run / "workflow.json", state)


def verify(run, state):
    options = run_options(state["config"])
    require(options == state.get("run_options", options), "Run options changed; start a new run")
    require(state["skill"] == skill_fingerprint(), "Skill changed; keep the frozen skill or start a new run")
    for source in state["config"]["sources"] + list(state["config"]["tools"].values()):
        require(Path(source["path"]).is_file() and digest(source["path"]) == source["sha256"],
                "Source/tool changed: " + source["path"])
    for stage, record in state["stages"].items():
        if record["status"] == "completed":
            require(snapshot(run / record["directory"]) == record["files"], "Locked artifacts changed: " + stage)
        if stage == "render":
            for job in record.get("jobs", {}).values():
                if job["status"] == "completed":
                    require(digest(run / job["output"]) == job["sha256"], "Locked render output changed")
    if state["delivery"]:
        for name, expected in state["delivery"]["files"].items():
            require(digest(run / name) == expected, "Delivered file changed: " + name)


def active(run, state, stage):
    record = state["stages"].get(stage, {})
    require(record.get("status") == "running", "Stage is not running: " + stage)
    return record, run / record["directory"]


def artifact(run, state, stage, name):
    record = state["stages"][stage]
    return inside(run / record["directory"], record["receipt"]["artifacts"][name])


def load_plans(base, receipt, count=3):
    entries = receipt["artifacts"]["plans"]
    require(isinstance(entries, dict) and len(entries) == count, f"Exactly {count} opening plans are required")
    result = {}
    for identifier, relative in entries.items():
        require(re.fullmatch(r"[a-zA-Z0-9_-]+", identifier), "Unsafe opening identifier")
        plan = read(inside(base, relative))
        require(plan["selected_opening"]["candidate_id"] == identifier, "Opening ID mismatch")
        result[identifier] = plan
    return result


def saved_plans(run, state, stage):
    rec = state["stages"][stage]
    return load_plans(run / rec["directory"], rec["receipt"], run_options(state["config"])["opening_count"])


def story_lock(plan):
    # Only frame times may change during boundary refinement; packaging cannot
    # alter the narrative, eligibility decision, context comparison or stop.
    result = deepcopy(plan)
    for key in ("start", "end"):
        result["selected_opening"].pop(key, None)
    for variant in result["variants"]:
        for key in ("opening_headline", "reset_transition", "end_hold", "video_checks"):
            variant.pop(key, None)
        for item in variant["ranges"]:
            item.pop("start", None)
            item.pop("end", None)
    return result


def boundary_lock(plan):
    return {"selected_opening": plan["selected_opening"],
            "ranges": {v["id"]: v["ranges"] for v in plan["variants"]}}


def validate_receipt(run, state, stage, base, receipt):
    require(isinstance(receipt.get("limitations"), list), "Record limitations, including an explicit empty list")
    checks = receipt.get("checks", {})
    for name in required_checks(state, stage):
        check = checks.get(name, {})
        require(check.get("status") == "passed" and check.get("evidence"), "Missing passing evidence: " + name)
        for path in check["evidence"]:
            require(inside(base, path).is_file(), "Missing evidence: " + path)
    if stage == "intake":
        manifest = read(inside(base, receipt["artifacts"]["manifest"]))
        require(manifest["scope"] == state["config"]["scope"], "Scope differs from initialized scope")
        require(manifest["sources"] == state["config"]["sources"], "Source manifest must preserve registered fingerprints")
    elif stage == "index":
        entries = read(inside(base, receipt["artifacts"]["index"]))["transcripts"]
        videos = {s["sha256"]: s for s in state["config"]["sources"] if s["role"] == "video"}
        require(len(entries) == len(videos) and {e["source_sha256"] for e in entries} == set(videos), "ASR coverage mismatch")
        for entry in entries:
            require(entry["language"] == state["config"]["language"] and entry["provider"] == "mediakit-cloud", "ASR provenance mismatch")
            task = state["tasks"].get(entry["source_sha256"], {})
            require(task.get("task_id") == entry["task_id"] and entry["task_id"], "ASR task must be registered before completion")
            require(entry.get("status") == "succeeded", "ASR task has not succeeded")
            for key in ("raw", "terminal", "normalized"):
                require(inside(base, entry[key]).is_file(), "Missing ASR artifact: " + key)
    elif stage == "openings":
        selected = read(inside(base, receipt["artifacts"]["selected"]))["selected_openings"]
        ids = [s["candidate_id"] for s in selected]
        count = run_options(state["config"])["opening_count"]
        require(len(ids) == count and len(set(ids)) == count, f"Lock {count} distinct opening IDs")
        require(all(re.fullmatch(r"[a-zA-Z0-9_-]+", s) for s in ids), "Unsafe opening ID")
        registered = {(s["path"], s.get("episode")) for s in state["config"]["sources"] if s["role"] == "video"}
        for opening in selected:
            require(isinstance(opening.get("event_anchor"), str) and opening["event_anchor"].strip(), "Lock the event anchor, not just its ID")
            require((opening["source_video"], opening["episode"]) in registered, "Opening source is outside the registered scope")
        require(inside(base, receipt["artifacts"]["candidates"]).is_file(), "Missing candidate comparisons")
    elif stage in ("story", "boundaries", "packaging"):
        options = run_options(state["config"])
        plans = load_plans(base, receipt, options["opening_count"])
        selected = {s["candidate_id"]: s for s in read(artifact(run, state, "openings", "selected"))["selected_openings"]}
        ids = set(selected)
        require(set(plans) == ids, "Downstream stage cannot replace locked openings")
        sources = {(s["path"], s.get("episode")) for s in state["config"]["sources"] if s["role"] == "video"}
        for identifier, plan in plans.items():
            require(all(plan["selected_opening"].get(k) == selected[identifier][k] for k in ("event_anchor", "source_video", "episode")),
                    "Downstream stage cannot change the locked opening event")
            require(plan["scope"]["episodes"] == state["config"]["scope"]["episodes"], "Plan scope mismatch")
            variants = plan["variants"]
            enabled = plan.get("cold_open_enabled", True)
            require(type(enabled) is bool and enabled == options["cold_open_enabled"],
                    "Plan cold_open_enabled differs from run configuration")
            if not enabled:
                errors = []
                validate_disabled_cold_open(plan.get("cold_open_eligibility"), errors)
                require(not errors, "; ".join(errors))
            expected = {"continuous", "cold_open"} if enabled and plan["cold_open_eligibility"]["eligible"] else {"continuous"}
            require(len(variants) == len(expected) and {v["id"] for v in variants} == expected, "Variant eligibility mismatch")
            for variant in variants:
                require(variant["ranges"], "Empty narrative path")
                for item in variant["ranges"]:
                    require((item["source_video"], item["episode"]) in sources, "Unregistered narrative source")
                if stage != "packaging":
                    require("opening_headline" not in variant, "Do not generate headlines before all boundaries lock")
            if stage != "story":
                require(story_lock(plan) == story_lock(saved_plans(run, state, "story")[identifier]),
                        "Narrative changed; explicitly revise story first")
            if stage == "packaging":
                require(boundary_lock(plan) == boundary_lock(saved_plans(run, state, "boundaries")[identifier]),
                        "Packaging cannot modify locked boundaries")
                errors = validate_plan(plan)
                require(not errors, "Plan validation failed: " + "; ".join(errors))
                for variant in variants:
                    audio = variant["end_hold"]["audio"]
                    if audio["kind"] == "impact_clip":
                        require(audio["source_video"] in {p for p, _ in sources}, "Unregistered impact audio source")
                    key = identifier + "." + variant["id"]
                    recipe = read(inside(base, receipt["artifacts"]["baselines"][key]))
                    require(recipe["ranges"] == variant["ranges"], "Baseline recipe must bind the exact locked ranges")
                    baseline_command(recipe, state["config"]["tools"]["ffmpeg"]["path"], "output.m4v",
                                     {r["source_video"] for r in variant["ranges"]})
            if stage == "boundaries":
                records = read(inside(base, receipt["artifacts"]["boundaries"][identifier]))
                require(records["locked_boundaries"] == boundary_lock(plan), "Boundary evidence does not match plan times")
                require(records.get("evidence"), "Missing actual boundary review evidence")
                for path in records["evidence"]:
                    require(inside(base, path).is_file(), "Missing boundary review artifact")
    elif stage == "render":
        jobs = state["stages"]["render"]["jobs"]
        require(jobs and all(j["status"] == "completed" for j in jobs.values()), "All render jobs must finish")
    elif stage == "review":
        reviewed = read(inside(base, receipt["artifacts"]["review"]))
        expected = {key: job for key, job in state["stages"]["render"]["jobs"].items() if key.endswith(".end")}
        require(set(reviewed["outputs"]) == set(expected), "Review must cover exactly the expected final variants")
        for key, result in reviewed["outputs"].items():
            require(result["sha256"] == expected[key]["sha256"], "Review refers to a different render")
            require(result.get("technical") == "passed" and result.get("targeted_content") == "passed", "Video review failed")
            require(result.get("continuous_viewing") in ("passed", "not_performed"), "Record actual continuous viewing status")
            if result["continuous_viewing"] == "not_performed":
                require(result.get("limitations"), "Unperformed viewing must be disclosed")
            for name in ("technical_evidence", "content_evidence"):
                require(result.get(name) and inside(base, result[name]).is_file(), "Missing per-output review evidence")
            technical = read(inside(base, result["technical_evidence"]))
            registered = state["stages"]["review"].get("technical_reports", {}).get(key, {})
            require(registered.get("path") == result["technical_evidence"] and
                    registered.get("sha256") == digest(inside(base, result["technical_evidence"])),
                    "Technical evidence must be an unchanged report generated by inspect in this review attempt")
            require(technical.get("output_sha256") == expected[key]["sha256"], "Technical review fingerprint mismatch")
            require(all(technical.get("checks", {}).get(name) is True for name in
                        ("full_decode", "av_tracks", "non_silent_audio", "duration", "orientation", "frame_rate")),
                    "Technical checks must all pass")
            identifier, variant_id, _ = key.split(".")
            packaging = state["stages"]["packaging"]
            plan_path = inside(run / packaging["directory"], packaging["receipt"]["artifacts"]["plans"][identifier])
            plan = read(plan_path)
            plan_hash = digest(plan_path)
            require(technical.get("plan_sha256") == plan_hash, "Technical review refers to an outdated plan")
            variant = next(v for v in plan["variants"] if v["id"] == variant_id)
            required = review_windows(variant, float(technical["probe"]["format"]["duration"]))
            content = read(inside(base, result["content_evidence"]))
            validate_content(content, required, expected[key]["sha256"], plan_hash)
            for name in required:
                for path in content["windows"][name]["evidence"]:
                    require(inside(base, path).is_file(), "Missing playback review evidence: " + path)


def begin(run, state, stage):
    require(not state["delivery"], "Delivered run is sealed; start a new run for revisions")
    for prior in STAGES[:STAGES.index(stage)]:
        require(state["stages"].get(prior, {}).get("status") == "completed", "Complete prior stage: " + prior)
    old = state["stages"].get(stage, {})
    if old.get("status") in ("running", "completed"):
        return old
    relative = "attempts/" + stage + "/" + uuid.uuid4().hex
    (run / relative).mkdir(parents=True)
    record = {"status": "running", "directory": relative}
    if stage == "render":
        record["jobs"] = {}
        caches = [old.get("jobs", {})]
        caches.extend(e.get("previous", {}).get("render", {}).get("jobs", {}) for e in reversed(state["events"]))
        packaging = state["stages"]["packaging"]
        for identifier, plan in saved_plans(run, state, "packaging").items():
            for variant in plan["variants"]:
                previous = None
                for step in (["baseline", "rewind", "headline", "end"] if variant["id"] == "cold_open" else ["baseline", "headline", "end"]):
                    key = identifier + "." + variant["id"] + "." + step
                    if step == "baseline":
                        params = read(inside(run / packaging["directory"], packaging["receipt"]["artifacts"]["baselines"][identifier + "." + variant["id"]]))
                    else:
                        field = {"rewind": "reset_transition", "headline": "opening_headline", "end": "end_hold"}[step]
                        params = variant[field]
                        if step == "rewind":
                            params = [params, variant["ranges"]]
                    signature = hashlib.sha256(json.dumps({"params": params, "skill": state["skill"],
                        "config": state["config"], "upstream": record["jobs"][previous]["signature"] if previous else None},
                        sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    job = {"status": "pending", "depends_on": previous, "signature": signature}
                    for cache in caches:
                        candidate = cache.get(key, {})
                        if candidate.get("status") == "completed" and candidate.get("signature") == signature:
                            path = run / candidate["output"]
                            if path.is_file() and digest(path) == candidate["sha256"]:
                                job = deepcopy(candidate)
                                event(state, "job_reused", job=key, output=job["output"])
                                break
                    record["jobs"][key] = job
                    previous = key
    state["stages"][stage] = record
    event(state, "stage_started", stage=stage, directory=relative)
    return {**record, "required_checks": required_checks(state, stage)}


def finish(run, state, stage, receipt_path):
    record, base = active(run, state, stage)
    receipt = read(inside(base, receipt_path))
    validate_receipt(run, state, stage, base, receipt)
    record.update(status="completed", receipt=receipt, files=snapshot(base))
    event(state, "stage_completed", stage=stage)
    return {"stage": stage, "status": "completed"}


def revise(state, stage, reason):
    require(reason.strip(), "A revision reason is required")
    require(not state["delivery"], "Delivered run is sealed; use a new run")
    affected = STAGES[STAGES.index(stage):]
    require(not any(state["stages"].get(s, {}).get("status") == "running" for s in affected), "Stop and fail active stages before revising")
    archived = {s: state["stages"].pop(s) for s in affected if s in state["stages"]}
    event(state, "revision", stage=stage, reason=reason, previous=archived)
    return {"invalidated": list(archived), "retained_files": True}


def job_begin(run, state, key):
    record, base = active(run, state, "render")
    job = record["jobs"][key]
    if job["status"] in ("running", "completed"):
        return job
    prior = job["depends_on"]
    require(prior is None or record["jobs"][prior]["status"] == "completed", "Finish the upstream render step first")
    directory = base / key / uuid.uuid4().hex
    directory.mkdir(parents=True)
    job.update(status="running", directory=str(directory.relative_to(run)))
    if prior:
        job["input"] = record["jobs"][prior]["output"]
    event(state, "job_started", job=key, directory=job["directory"])
    return job


def job_finish(run, state, key, filename, *, runner_completed=False):
    require(runner_completed, "Managed output must be produced by execute/render; manual completion cannot bypass the compiled plan")
    record, _ = active(run, state, "render")
    job = record["jobs"][key]
    require(job["status"] == "running", "Job is not running")
    path = inside(run / job["directory"], filename)
    require(path.is_file() and path.stat().st_size > 0 and path.suffix in (".mp4", ".m4v"), "Missing media output")
    job.update(status="completed", output=str(path.relative_to(run)), sha256=digest(path))
    event(state, "job_completed", job=key, output=job["output"])
    return job


def register_task(state, source_hash, task_id):
    require(state["stages"].get("index", {}).get("status") == "running", "Start the index stage first")
    require(source_hash in {s["sha256"] for s in state["config"]["sources"] if s["role"] == "video"}, "Unknown video fingerprint")
    task = state["tasks"].get(source_hash)
    newly_reserved = task is None
    if task is None:
        require(task_id is None, "Reserve the ASR submission before making the cloud request")
        task = {"status": "submission_reserved", "language": state["config"]["language"], "provider": "mediakit-cloud"}
        state["tasks"][source_hash] = task
    elif task_id:
        require(all(key == source_hash or value.get("task_id") != task_id for key, value in state["tasks"].items()),
                "Task ID is already bound to a different source")
        require(not task.get("task_id") or task["task_id"] == task_id, "A task already exists; query it rather than submitting again")
        task.update(status="submitted", task_id=task_id)
    event(state, "asr_task_recorded", source_sha256=source_hash, task=deepcopy(task))
    return {**task, "submit_allowed": newly_reserved}


def package(run, state):
    require(state["stages"].get("review", {}).get("status") == "completed", "Complete review before delivery")
    if state["delivery"]:
        return state["delivery"]
    reviewed = read(artifact(run, state, "review", "review"))
    jobs = state["stages"]["render"]["jobs"]
    directory = run / "deliveries" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    listing = {"outputs": [], "limitations": state["stages"]["review"]["receipt"]["limitations"]}
    archive = directory / "ads.zip"
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as target:
        for key, review in reviewed["outputs"].items():
            job = jobs[key]
            name = key.removesuffix(".end") + Path(job["output"]).suffix
            target.write(run / job["output"], arcname=name)
            listing["outputs"].append({"name": name, "source": job["output"], "sha256": job["sha256"], "review": review})
        target.writestr("delivery-manifest.json", json.dumps(listing, ensure_ascii=False, indent=2))
    write(directory / "delivery-manifest.json", listing)
    files = {str((directory / name).relative_to(run)): value for name, value in snapshot(directory).items()}
    state["delivery"] = {"directory": str(directory.relative_to(run)), "files": files}
    event(state, "delivered", directory=state["delivery"]["directory"])
    return state["delivery"]


def wrapper_command(plan, variant_id, step, executable, source, output):
    variant = next(v for v in plan["variants"] if v["id"] == variant_id)
    command = [str(executable), str(source), str(output)]
    if step == "rewind":
        transition = variant["reset_transition"]
        duration = lambda role: sum(r["end"] - r["start"] for r in variant["ranges"] if r["role"] == role)
        card = transition["card"]["text"]
        command += ["--at", str(duration("opening_window")),
                    "--source-position", "after", "--source-duration", str(duration("reset_context")),
                    "--pre-freeze-duration", str(transition["freeze"]["duration"]),
                    "--pre-card-duration", str(transition["card"]["duration"]),
                    "--pre-card-text", "|".join(card[k] for k in ("line_1", "line_2") if card.get(k)),
                    "--transition-duration", str(transition["rewind"]["duration"])]
    elif step == "headline":
        title = variant["opening_headline"]
        for index, line in enumerate(title["lines"], 1):
            command += ["--line" + str(index), line]
        for option, key in (("--hold-duration", "hold_duration"), ("--fade-duration", "fade_duration"),
                            ("--base-color", "base_color"), ("--accent-color", "accent_color")):
            command += [option, str(title[key])]
    elif step == "end":
        hold = variant["end_hold"]
        audio = hold["audio"]
        command += ["--effect-duration", str(hold["duration"]), "--motion", hold["visual"],
                    "--audio-mode", "impact" if audio["kind"] == "impact_clip" else "silence"]
        if audio["kind"] == "impact_clip":
            command += ["--sound-video", audio["source_video"], "--sound-start", str(audio["start"])]
    else:
        raise ValueError("Baseline rendering must use the reviewed source-specific FFmpeg command")
    return command


def execute_wrap(run, key):
    scripts = {"rewind": "insert_rewind_transition.swift", "headline": "overlay_opening_headline.swift",
               "end": "apply_punch_end.swift"}
    with locked(run) as state:
        verify(run, state)
        record = state["stages"].get("render", {})
        existing = record["jobs"][key]
        if existing["status"] == "completed":
            return {"reused": True, **existing}
        active(run, state, "render")
        require(existing["status"] != "running", "Job already running; inspect it before any retry")
        identifier, variant_id, step = key.split(".")
        require(step in scripts or step == "baseline", "Unknown render step")
        plan = saved_plans(run, state, "packaging")[identifier]
        recipe = None
        if step == "baseline":
            rec = state["stages"]["packaging"]
            recipe = read(inside(run / rec["directory"], rec["receipt"]["artifacts"]["baselines"][identifier + "." + variant_id]))
        job = deepcopy(job_begin(run, state, key))
        config = deepcopy(state["config"])
    directory = run / job["directory"]
    executable = directory / "wrapper"
    output = directory / "output.m4v"
    if step == "baseline":
        variant = next(v for v in plan["variants"] if v["id"] == variant_id)
        commands = [baseline_command(recipe, config["tools"]["ffmpeg"]["path"], output,
                                     {r["source_video"] for r in variant["ranges"]})]
    else:
        commands = [[config["tools"]["swiftc"]["path"], "-parse-as-library",
                     str(ROOT / "scripts" / scripts[step]), "-o", str(executable)],
                    wrapper_command(plan, variant_id, step, executable, run / job["input"], output)]
    environment = {**os.environ, "FFMPEG_PATH": config["tools"]["ffmpeg"]["path"],
                   "FFPROBE_PATH": config["tools"]["ffprobe"]["path"]}
    write(directory / "commands.json", commands)
    try:
        with (directory / "execution.log").open("x") as log:
            if step == "baseline":
                write(directory / "source-probes.json", verify_sources(recipe, config["tools"]["ffprobe"]["path"]))
            for command in commands:
                subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        with locked(run) as state:
            verify(run, state)
            require(state["stages"]["render"]["jobs"][key].get("directory") == job["directory"], "Job attempt changed during execution")
            return job_finish(run, state, key, "output.m4v", runner_completed=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        with locked(run) as state:
            record, _ = active(run, state, "render")
            if record["jobs"][key].get("directory") == job["directory"]:
                record["jobs"][key].update(status="failed", error=str(exc))
                event(state, "job_failed", job=key, reason=str(exc))
        raise ValueError("Wrapper failed; logs and previous valid output retained: " + str(exc)) from exc


def inspect_outputs(run, state):
    from pipeline.media_checks import inspect
    _, base = active(run, state, "review")
    directory = base / ("technical-" + uuid.uuid4().hex)
    directory.mkdir()
    results = {}
    plans = saved_plans(run, state, "packaging")
    for key, job in state["stages"]["render"]["jobs"].items():
        if not key.endswith(".end"):
            continue
        identifier, variant_id, _ = key.split(".")
        variant = next(v for v in plans[identifier]["variants"] if v["id"] == variant_id)
        report = inspect(run / job["output"], variant, state["config"]["tools"])
        report["output_sha256"] = job["sha256"]
        packaging = state["stages"]["packaging"]
        plan_path = inside(run / packaging["directory"], packaging["receipt"]["artifacts"]["plans"][identifier])
        report["plan_sha256"] = digest(plan_path)
        path = directory / (key + ".json")
        write(path, report)
        template = directory / (key + "-content.json")
        required = review_windows(variant, float(report["probe"]["format"]["duration"]))
        write(template, {"output_sha256": job["sha256"], "plan_sha256": report["plan_sha256"], "reviewer": "",
                         "windows": {name: {**window, "status": "pending", "observation": "", "evidence": []}
                                     for name, window in required.items()}})
        results[key] = {"path": str(path.relative_to(base)), "sha256": digest(path), "checks": report["checks"],
                        "content_template": str(template.relative_to(base))}
    state["stages"]["review"]["technical_reports"] = deepcopy(results)
    event(state, "technical_inspection", results=results)
    return results


def render_all(run):
    with locked(run) as state:
        verify(run, state)
        if state["stages"].get("render", {}).get("status") != "completed":
            begin(run, state, "render")
        jobs = list(state["stages"]["render"]["jobs"])
    # Order is created from the locked variants; failures stop immediately and
    # already completed jobs are checked and reused by execute_wrap.
    return {key: execute_wrap(run, key) for key in jobs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("config", type=Path)
    init.add_argument("--opening-count", type=int, help="Number of distinct openings (default: config or 3)")
    init.add_argument("--cold-open", choices=("on", "off"), help="Allow eligible cold-open variants (default: config or on)")
    commands.add_parser("status")
    commands.add_parser("package")
    commands.add_parser("inspect")
    commands.add_parser("render")
    wrap = commands.add_parser("wrap")
    wrap.add_argument("job")
    execute = commands.add_parser("execute")
    execute.add_argument("job")
    for name in ("begin", "finish", "fail", "revise"):
        sub = commands.add_parser(name)
        sub.add_argument("stage", choices=STAGES)
        if name == "finish":
            sub.add_argument("receipt", help="Path relative to the active stage attempt")
        if name in ("fail", "revise"):
            sub.add_argument("reason")
    task = commands.add_parser("task")
    task.add_argument("source_sha256")
    task.add_argument("--task-id")
    for name in ("job-begin", "job-finish", "job-fail"):
        sub = commands.add_parser(name)
        sub.add_argument("job")
        if name == "job-finish":
            sub.add_argument("file", help="Media path relative to this job attempt")
        if name == "job-fail":
            sub.add_argument("reason")
    args = parser.parse_args()
    run = args.run.resolve()
    try:
        if args.command == "init":
            config = read(args.config)
            if args.opening_count is not None:
                config["opening_count"] = args.opening_count
            if args.cold_open is not None:
                config["cold_open_enabled"] = args.cold_open == "on"
            result = initialize(run, config)
        elif args.command in ("wrap", "execute"):
            result = execute_wrap(run, args.job)
        elif args.command == "render":
            result = render_all(run)
        else:
            with locked(run) as state:
                verify(run, state)
                if args.command == "status":
                    result = {**run_options(state["config"]), "stages": state["stages"], "tasks": state["tasks"], "delivery": state["delivery"],
                              "next": next((s for s in STAGES if state["stages"].get(s, {}).get("status") != "completed"), "package")}
                elif args.command == "begin":
                    result = begin(run, state, args.stage)
                elif args.command == "finish":
                    result = finish(run, state, args.stage, args.receipt)
                elif args.command == "revise":
                    result = revise(state, args.stage, args.reason)
                elif args.command == "fail":
                    rec, _ = active(run, state, args.stage)
                    require(args.reason.strip(), "Failure reason is required")
                    rec.update(status="failed", error=args.reason)
                    event(state, "stage_failed", stage=args.stage, reason=args.reason)
                    result = rec
                elif args.command == "task":
                    result = register_task(state, args.source_sha256, args.task_id)
                elif args.command == "job-begin":
                    result = job_begin(run, state, args.job)
                elif args.command == "job-finish":
                    result = job_finish(run, state, args.job, args.file)
                elif args.command == "job-fail":
                    rec, _ = active(run, state, "render")
                    job = rec["jobs"][args.job]
                    require(job["status"] == "running" and args.reason.strip(), "Only a running job can fail with a reason")
                    job.update(status="failed", error=args.reason)
                    event(state, "job_failed", job=args.job, reason=args.reason)
                    result = job
                elif args.command == "inspect":
                    result = inspect_outputs(run, state)
                else:
                    result = package(run, state)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, ArithmeticError, StopIteration, subprocess.CalledProcessError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
