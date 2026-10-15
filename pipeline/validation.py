#!/usr/bin/env python3
"""Validate the deterministic structure of a v1.9 short-drama edit plan."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_CONTEXT_GAPS = {"none", "title_resolvable", "video_required"}
ALLOWED_ROLES = {
    "opening_window",
    "continuous_story",
    "reset_context",
    "opening_echo",
    "resume_after_opening",
    "ending_hook",
}
ALLOWED_VARIANTS = {"continuous", "cold_open"}
ELIGIBILITY_REASON_CODES = {
    "eligible",
    "no_prior_context",
    "no_causal_context",
    "no_natural_entry",
    "no_clean_catchup",
    "no_added_value",
}
ELIGIBILITY_CHECKS = {
    "prior_context_exists",
    "causal_context_exists",
    "natural_entry_exists",
    "clean_catchup_exists",
    "adds_viewing_value",
}
REASON_TO_FAILED_CHECK = {
    "no_prior_context": "prior_context_exists",
    "no_causal_context": "causal_context_exists",
    "no_natural_entry": "natural_entry_exists",
    "no_clean_catchup": "clean_catchup_exists",
    "no_added_value": "adds_viewing_value",
}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_disabled_cold_open(eligibility: Any, errors: list[str]) -> None:
    require(isinstance(eligibility, dict), "Disabled cold open needs a decision record", errors)
    if not isinstance(eligibility, dict):
        return
    require(set(eligibility) == {"status", "reason_code", "reason"},
            "Disabled cold open must not claim editorial eligibility checks", errors)
    require(eligibility.get("status") == "not_evaluated" and
            eligibility.get("reason_code") == "disabled_by_user",
            "Disabled cold open must record not_evaluated / disabled_by_user", errors)
    require(isinstance(eligibility.get("reason"), str) and bool(eligibility["reason"].strip()),
            "Disabled cold open needs a non-empty reason", errors)


def validate_entry_search(decision: dict[str, Any], path: str, errors: list[str]) -> None:
    """Check coverage bookkeeping, not the truth or appeal of narrative evidence."""
    def nonempty(value: Any) -> bool:
        return isinstance(value, str) and bool(value.strip())

    search = decision.get("entry_search")
    require(isinstance(search, dict), f"{path}.entry_search must be an object", errors)
    if not isinstance(search, dict):
        return
    for key in ("scope_start", "scope_end", "source_evidence"):
        require(nonempty(search.get(key)), f"{path}.entry_search.{key} must be non-empty", errors)
    layers = {"relationship_setup", "conflict_origin", "direct_trigger"}
    events = search.get("events")
    require(isinstance(events, list) and bool(events), f"{path}.entry_search.events must be non-empty", errors)
    if not isinstance(events, list):
        return
    ids: list[str] = []
    compared_ids: list[str] = []
    covered: set[str] = set()
    for index, event in enumerate(events):
        ep = f"{path}.entry_search.events[{index}]"
        require(isinstance(event, dict), f"{ep} must be an object", errors)
        if not isinstance(event, dict):
            continue
        for key in ("id", "anchor", "connection", "viewer_evidence"):
            require(nonempty(event.get(key)), f"{ep}.{key} must be non-empty", errors)
        event_id = event.get("id")
        if nonempty(event_id):
            require(event_id not in ids, f"{ep}.id must be unique", errors)
            ids.append(event_id)
        event_layers = event.get("layers")
        require(isinstance(event_layers, list) and bool(event_layers), f"{ep}.layers must be non-empty", errors)
        if isinstance(event_layers, list):
            for layer in event_layers:
                valid = isinstance(layer, str) and layer in layers
                require(valid, f"{ep}.layers contains an invalid layer", errors)
                if valid:
                    covered.add(layer)
        disposition = event.get("disposition")
        require(disposition in ("compare", "exclude"), f"{ep}.disposition must be compare or exclude", errors)
        if disposition == "compare" and nonempty(event_id):
            compared_ids.append(event_id)
        if disposition == "exclude":
            require(nonempty(event.get("exclusion_reason")), f"{ep}.exclusion_reason must explain exclusion", errors)
    absent = search.get("absent_layers")
    require(isinstance(absent, dict), f"{path}.entry_search.absent_layers must be an object", errors)
    if isinstance(absent, dict):
        require(set(absent) == layers - covered, f"{path}.entry_search.absent_layers must explain exactly the uncovered layers", errors)
        for reason in absent.values():
            require(nonempty(reason), f"{path}.entry_search.absent_layers reasons must be non-empty", errors)
    candidates = decision.get("compared_entries")
    candidate_ids: list[str] = []
    selected_id = None
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            event_id = candidate.get("start_event_id")
            require(nonempty(event_id), f"{path}.compared_entries.start_event_id must be non-empty", errors)
            if nonempty(event_id):
                candidate_ids.append(event_id)
                if candidate.get("selected") is True:
                    selected_id = event_id
    require(len(candidate_ids) == len(set(candidate_ids)), f"{path}.compared_entries must use distinct events, not neighboring cuts", errors)
    require(set(candidate_ids) == set(compared_ids), f"{path}.compared_entries must cover exactly all compare events", errors)
    earlier_ids = set()
    if selected_id in ids:
        earlier_ids = set(ids[:ids.index(selected_id)]) & set(compared_ids)
    reviews = decision.get("earlier_prefix_review")
    require(isinstance(reviews, list), f"{path}.earlier_prefix_review must be a list", errors)
    reviewed_ids: list[str] = []
    if isinstance(reviews, list):
        for index, review in enumerate(reviews):
            rp = f"{path}.earlier_prefix_review[{index}]"
            require(isinstance(review, dict), f"{rp} must be an object", errors)
            if not isinstance(review, dict):
                continue
            for key in ("event_id", "added_information", "retention_value", "connection", "cost", "rejection_reason"):
                require(nonempty(review.get(key)), f"{rp}.{key} must be non-empty", errors)
            if nonempty(review.get("event_id")):
                reviewed_ids.append(review["event_id"])
    require(len(reviewed_ids) == len(set(reviewed_ids)) and set(reviewed_ids) == earlier_ids,
            f"{path}.earlier_prefix_review must cover exactly the candidates earlier than the selected entry", errors)


def validate_range(item: Any, path: str, errors: list[str]) -> None:
    require(isinstance(item, dict), f"{path} must be an object", errors)
    if not isinstance(item, dict):
        return

    required = (
        "source_video",
        "episode",
        "start",
        "end",
        "role",
        "entry_reason",
        "exit_reason",
    )
    for key in required:
        require(key in item, f"{path}.{key} is required", errors)

    source_video = item.get("source_video")
    require(
        isinstance(source_video, str) and source_video.startswith("/"),
        f"{path}.source_video must be an absolute path",
        errors,
    )
    require(
        isinstance(item.get("episode"), (int, str))
        and not isinstance(item.get("episode"), bool),
        f"{path}.episode must be an integer or string",
        errors,
    )

    start = item.get("start")
    end = item.get("end")
    require(
        is_number(start) and start >= 0,
        f"{path}.start must be a non-negative number",
        errors,
    )
    require(
        is_number(end) and end >= 0,
        f"{path}.end must be a non-negative number",
        errors,
    )
    if is_number(start) and is_number(end):
        require(end > start, f"{path}.end must be greater than start", errors)

    require(
        item.get("role") in ALLOWED_ROLES,
        f"{path}.role must be one of {sorted(ALLOWED_ROLES)}",
        errors,
    )
    for key in ("entry_reason", "exit_reason"):
        require(
            isinstance(item.get(key), str) and bool(item.get(key).strip()),
            f"{path}.{key} must be non-empty",
            errors,
        )
    if item.get("role") == "opening_echo":
        require(
            item.get("echo_type") in {"last_line", "last_action"},
            f"{path}.echo_type must be 'last_line' or 'last_action'",
            errors,
        )
        require(
            isinstance(item.get("echo_content"), str)
            and bool(item.get("echo_content", "").strip()),
            f"{path}.echo_content must be non-empty",
            errors,
        )


def validate_plan(plan: Any) -> list[str]:
    errors: list[str] = []
    require(isinstance(plan, dict), "root must be an object", errors)
    if not isinstance(plan, dict):
        return errors

    require(
        plan.get("schema_version") == "1.9",
        "schema_version must be '1.9'",
        errors,
    )
    require(
        isinstance(plan.get("case_id"), str)
        and bool(plan.get("case_id", "").strip()),
        "case_id must be non-empty",
        errors,
    )

    scope = plan.get("scope")
    require(isinstance(scope, dict), "scope must be an object", errors)
    if isinstance(scope, dict):
        require(
            scope.get("kind") == "pre_paywall",
            "scope.kind must be 'pre_paywall'",
            errors,
        )
        episodes = scope.get("episodes")
        require(
            isinstance(episodes, list) and len(episodes) > 0,
            "scope.episodes must be a non-empty list",
            errors,
        )

    opening = plan.get("selected_opening")
    require(isinstance(opening, dict), "selected_opening must be an object", errors)
    if isinstance(opening, dict):
        required = (
            "candidate_id",
            "source_video",
            "episode",
            "start",
            "end",
            "context_gap",
        )
        for key in required:
            require(key in opening, f"selected_opening.{key} is required", errors)
        require(
            isinstance(opening.get("source_video"), str)
            and opening.get("source_video", "").startswith("/"),
            "selected_opening.source_video must be an absolute path",
            errors,
        )
        start = opening.get("start")
        end = opening.get("end")
        require(
            is_number(start) and start >= 0,
            "selected_opening.start must be non-negative",
            errors,
        )
        require(
            is_number(end) and end >= 0,
            "selected_opening.end must be non-negative",
            errors,
        )
        if is_number(start) and is_number(end):
            require(
                end > start,
                "selected_opening.end must be greater than start",
                errors,
            )
        require(
            opening.get("context_gap") in ALLOWED_CONTEXT_GAPS,
            "selected_opening.context_gap must be none, title_resolvable, or video_required",
            errors,
        )

    eligibility = plan.get("cold_open_eligibility")
    require(
        isinstance(eligibility, dict),
        "cold_open_eligibility must be an object",
        errors,
    )
    enabled = plan.get("cold_open_enabled", True)
    require(type(enabled) is bool, "cold_open_enabled must be boolean", errors)
    cold_open_eligible = False
    if enabled is False:
        validate_disabled_cold_open(eligibility, errors)
    elif isinstance(eligibility, dict):
        require(
            eligibility.get("evaluated_after_opening_locked") is True,
            "cold_open_eligibility.evaluated_after_opening_locked must be true",
            errors,
        )
        cold_open_eligible = eligibility.get("eligible") is True
        require(
            isinstance(eligibility.get("eligible"), bool),
            "cold_open_eligibility.eligible must be boolean",
            errors,
        )
        reason_code = eligibility.get("reason_code")
        require(
            reason_code in ELIGIBILITY_REASON_CODES,
            "cold_open_eligibility.reason_code is invalid",
            errors,
        )
        require(
            isinstance(eligibility.get("reason"), str)
            and bool(eligibility.get("reason", "").strip()),
            "cold_open_eligibility.reason must be non-empty",
            errors,
        )
        checks = eligibility.get("checks")
        require(
            isinstance(checks, dict),
            "cold_open_eligibility.checks must be an object",
            errors,
        )
        if isinstance(checks, dict):
            for check_key in ELIGIBILITY_CHECKS:
                require(
                    isinstance(checks.get(check_key), bool),
                    f"cold_open_eligibility.checks.{check_key} must be boolean",
                    errors,
                )
            if cold_open_eligible:
                require(
                    reason_code == "eligible",
                    "eligible cold open must use reason_code 'eligible'",
                    errors,
                )
                require(
                    all(checks.get(key) is True for key in ELIGIBILITY_CHECKS),
                    "eligible cold open requires all eligibility checks to be true",
                    errors,
                )
            else:
                require(
                    reason_code in ELIGIBILITY_REASON_CODES - {"eligible"},
                    "ineligible cold open must use an ineligibility reason_code",
                    errors,
                )
                require(
                    any(checks.get(key) is False for key in ELIGIBILITY_CHECKS),
                    "ineligible cold open requires at least one failed check",
                    errors,
                )
                failed_check = REASON_TO_FAILED_CHECK.get(reason_code)
                if failed_check is not None:
                    require(
                        checks.get(failed_check) is False,
                        "cold_open_eligibility.reason_code must match its "
                        "failed check",
                        errors,
                    )

    variants = plan.get("variants")
    require(isinstance(variants, list), "variants must be a list", errors)
    if not isinstance(variants, list):
        return errors

    ids = [variant.get("id") for variant in variants if isinstance(variant, dict)]
    require(len(ids) == len(set(ids)), "variant ids must be unique", errors)
    expected_variants = (
        {"continuous", "cold_open"}
        if cold_open_eligible
        else {"continuous"}
    )
    require(
        set(ids) == expected_variants,
        "variants must contain continuous and include cold_open exactly when "
        "cold_open_eligibility.eligible is true",
        errors,
    )
    require(
        all(variant_id in ALLOWED_VARIANTS for variant_id in ids),
        f"variant ids must be in {sorted(ALLOWED_VARIANTS)}",
        errors,
    )
    headline_lines = [
        variant.get("opening_headline", {}).get("lines")
        for variant in variants
        if isinstance(variant, dict)
        and isinstance(variant.get("opening_headline"), dict)
    ]
    if len(headline_lines) == 2:
        require(
            headline_lines[0] == headline_lines[1],
            "continuous and cold_open must use the same opening headline lines",
            errors,
        )
    headline_specs = [
        variant.get("opening_headline")
        for variant in variants
        if isinstance(variant, dict)
        and isinstance(variant.get("opening_headline"), dict)
    ]
    if len(headline_specs) == 2:
        require(
            headline_specs[0] == headline_specs[1],
            "continuous and cold_open must use the same opening headline design",
            errors,
        )

    for index, variant in enumerate(variants):
        path = f"variants[{index}]"
        require(isinstance(variant, dict), f"{path} must be an object", errors)
        if not isinstance(variant, dict):
            continue
        require(
            is_number(variant.get("target_duration"))
            and variant.get("target_duration", 0) > 0,
            f"{path}.target_duration must be positive",
            errors,
        )
        require(
            isinstance(variant.get("ending_hook"), str)
            and bool(variant.get("ending_hook", "").strip()),
            f"{path}.ending_hook must be non-empty",
            errors,
        )
        headline = variant.get("opening_headline")
        require(
            isinstance(headline, dict),
            f"{path}.opening_headline must be an object",
            errors,
        )
        if isinstance(headline, dict):
            lines = headline.get("lines")
            require(
                isinstance(lines, list)
                and len(lines) == 3
                and all(isinstance(line, str) and line.strip() for line in lines),
                f"{path}.opening_headline.lines must contain three non-empty strings",
                errors,
            )
            expected_headline = {
                "generation": "automatic_final",
                "generation_stage": "after_story_ranges_locked",
                "affects_range_selection": False,
                "position": "top_center",
                "background": "none",
                "design_mode": "automatic_scene_adaptive",
                "sample_window": 4.0,
                "accent_target": "line_3",
                "outline": "light_black",
                "hold_duration": 3.0,
                "fade_duration": 1.0,
            }
            for key, value in expected_headline.items():
                require(
                    headline.get(key) == value,
                    f"{path}.opening_headline.{key} must be {value!r}",
                    errors,
                )
            require(
                headline.get("purpose")
                in {"necessary_context", "retention_hook"},
                f"{path}.opening_headline.purpose must be necessary_context "
                "or retention_hook",
                errors,
            )
            require(
                isinstance(headline.get("rationale"), str)
                and bool(headline.get("rationale", "").strip()),
                f"{path}.opening_headline.rationale must be non-empty",
                errors,
            )
            for color_key in ("base_color", "accent_color"):
                color = headline.get(color_key)
                require(
                    isinstance(color, str)
                    and re.fullmatch(r"#[0-9A-Fa-f]{6}", color) is not None,
                    f"{path}.opening_headline.{color_key} must be #RRGGBB",
                    errors,
                )
            require(
                headline.get("base_color") != headline.get("accent_color"),
                f"{path}.opening_headline base_color and accent_color must differ",
                errors,
            )
            qa = headline.get("qa")
            require(
                isinstance(qa, dict),
                f"{path}.opening_headline.qa must be an object",
                errors,
            )
            if isinstance(qa, dict):
                for qa_key in (
                    "readability_passed",
                    "subject_overlap_passed",
                    "source_text_overlap_passed",
                ):
                    require(
                        qa.get(qa_key) is True,
                        f"{path}.opening_headline.qa.{qa_key} must be true",
                        errors,
                    )
                require(
                    isinstance(qa.get("fallback_used"), bool),
                    f"{path}.opening_headline.qa.fallback_used must be boolean",
                    errors,
                )
        end_hold = variant.get("end_hold")
        require(
            isinstance(end_hold, dict),
            f"{path}.end_hold must be an object",
            errors,
        )
        if isinstance(end_hold, dict):
            require(
                end_hold.get("kind") == "freeze_last_frame",
                f"{path}.end_hold.kind must be 'freeze_last_frame'",
                errors,
            )
            duration = end_hold.get("duration")
            require(
                is_number(duration) and abs(duration - 1.0) < 0.001,
                f"{path}.end_hold.duration must be 1.0",
                errors,
            )
            require(
                end_hold.get("visual") == "shake",
                f"{path}.end_hold.visual must be 'shake'",
                errors,
            )
            audio = end_hold.get("audio")
            require(
                isinstance(audio, dict),
                f"{path}.end_hold.audio must be an object",
                errors,
            )
            if isinstance(audio, dict):
                audio_kind = audio.get("kind")
                require(
                    audio_kind in {"silence", "impact_clip"},
                    f"{path}.end_hold.audio.kind must be 'silence' or 'impact_clip'",
                    errors,
                )
                if audio_kind == "impact_clip":
                    require(
                        isinstance(audio.get("source_video"), str)
                        and audio.get("source_video", "").startswith("/"),
                        f"{path}.end_hold.audio.source_video must be an absolute path",
                        errors,
                    )
                    audio_start = audio.get("start")
                    audio_end = audio.get("end")
                    require(
                        is_number(audio_start) and audio_start >= 0,
                        f"{path}.end_hold.audio.start must be non-negative",
                        errors,
                    )
                    require(
                        is_number(audio_end) and audio_end >= 0,
                        f"{path}.end_hold.audio.end must be non-negative",
                        errors,
                    )
                    if is_number(audio_start) and is_number(audio_end):
                        require(
                            audio_end > audio_start,
                            f"{path}.end_hold.audio.end must be greater than start",
                            errors,
                        )
                        if is_number(duration):
                            require(
                                abs(duration - (audio_end - audio_start)) < 0.001,
                                f"{path}.end_hold.duration must equal audio clip duration",
                                errors,
                            )
                    require(
                        audio.get("gain") == 1.0,
                        f"{path}.end_hold.audio.gain must be 1.0",
                        errors,
                    )
                    require(
                        audio.get("speed") == 1.0,
                        f"{path}.end_hold.audio.speed must be 1.0",
                        errors,
                    )
                    require(
                        audio.get("contains_speech") is False,
                        f"{path}.end_hold.audio.contains_speech must be false",
                        errors,
                    )
                    require(
                        audio.get("overlaps_story_tail") is False,
                        f"{path}.end_hold.audio.overlaps_story_tail must be false",
                        errors,
                    )
        ranges = variant.get("ranges")
        require(
            isinstance(ranges, list) and len(ranges) > 0,
            f"{path}.ranges must be a non-empty list",
            errors,
        )
        if isinstance(ranges, list):
            for range_index, item in enumerate(ranges):
                validate_range(item, f"{path}.ranges[{range_index}]", errors)
            roles = [item.get("role") for item in ranges if isinstance(item, dict)]
            require(
                roles and roles[0] == "opening_window",
                f"{path}.ranges must begin with opening_window",
                errors,
            )
            require(
                "ending_hook" in roles,
                f"{path}.ranges must contain an ending_hook range",
                errors,
            )
            if ranges and isinstance(ranges[0], dict) and isinstance(opening, dict):
                first = ranges[0]
                require(
                    first.get("source_video") == opening.get("source_video")
                    and first.get("episode") == opening.get("episode")
                    and first.get("start") == opening.get("start")
                    and first.get("end") == opening.get("end"),
                    f"{path}.ranges[0] must exactly match selected_opening",
                    errors,
                )

        if variant.get("id") == "cold_open":
            context_decision = variant.get("context_entry_decision")
            require(
                isinstance(context_decision, dict),
                f"{path}.context_entry_decision must be an object",
                errors,
            )
            if isinstance(context_decision, dict):
                validate_entry_search(context_decision, f"{path}.context_entry_decision", errors)
                require(
                    context_decision.get("selection_rule")
                    == "best_narrative_arc_covering_full_causal_chain",
                    f"{path}.context_entry_decision.selection_rule must be "
                    "'best_narrative_arc_covering_full_causal_chain'",
                    errors,
                )
                for key in (
                    "hook_question",
                    "selected_entry",
                    "selection_reason",
                    "narrative_unit",
                ):
                    require(
                        isinstance(context_decision.get(key), str)
                        and bool(context_decision.get(key, "").strip()),
                        f"{path}.context_entry_decision.{key} must be non-empty",
                        errors,
                    )
                causal_chain = context_decision.get("causal_chain")
                require(
                    isinstance(causal_chain, list) and len(causal_chain) >= 2,
                    f"{path}.context_entry_decision.causal_chain must contain "
                    "at least direct_cause and motivation",
                    errors,
                )
                causal_types: list[str] = []
                if isinstance(causal_chain, list):
                    for causal_index, item in enumerate(causal_chain):
                        item_path = (
                            f"{path}.context_entry_decision."
                            f"causal_chain[{causal_index}]"
                        )
                        require(
                            isinstance(item, dict),
                            f"{item_path} must be an object",
                            errors,
                        )
                        if isinstance(item, dict):
                            causal_type = item.get("type")
                            require(
                                causal_type
                                in {
                                    "direct_cause",
                                    "motivation",
                                    "relationship_context",
                                },
                                f"{item_path}.type is invalid",
                                errors,
                            )
                            if isinstance(causal_type, str):
                                causal_types.append(causal_type)
                            require(
                                isinstance(item.get("beat"), str)
                                and bool(item.get("beat", "").strip()),
                                f"{item_path}.beat must be non-empty",
                                errors,
                            )
                require(
                    "direct_cause" in causal_types,
                    f"{path}.context_entry_decision.causal_chain must include "
                    "direct_cause",
                    errors,
                )
                require(
                    "motivation" in causal_types,
                    f"{path}.context_entry_decision.causal_chain must include "
                    "motivation",
                    errors,
                )
                viewer_evidence = context_decision.get("viewer_evidence")
                require(
                    isinstance(viewer_evidence, dict),
                    f"{path}.context_entry_decision.viewer_evidence must be an object",
                    errors,
                )
                if isinstance(viewer_evidence, dict):
                    require(
                        viewer_evidence.get("status")
                        in {
                            "script_only_unverified",
                            "asr_only_unverified",
                            "video_verified",
                        },
                        f"{path}.context_entry_decision.viewer_evidence.status "
                        "is invalid",
                        errors,
                    )
                    require(
                        viewer_evidence.get("status") == "video_verified",
                        f"{path}.context_entry_decision.viewer_evidence.status "
                        "must be 'video_verified' in a final edit plan",
                        errors,
                    )
                    for evidence_key in (
                        "dialogue_evidence",
                        "visual_evidence",
                        "excluded_script_information",
                    ):
                        evidence_items = viewer_evidence.get(evidence_key)
                        require(
                            isinstance(evidence_items, list),
                            f"{path}.context_entry_decision.viewer_evidence."
                            f"{evidence_key} must be a list",
                            errors,
                        )
                        if isinstance(evidence_items, list):
                            for evidence_index, evidence_item in enumerate(
                                evidence_items
                            ):
                                require(
                                    isinstance(evidence_item, str)
                                    and bool(evidence_item.strip()),
                                    f"{path}.context_entry_decision.viewer_evidence."
                                    f"{evidence_key}[{evidence_index}] must be "
                                    "non-empty",
                                    errors,
                                )
                compared_entries = context_decision.get("compared_entries")
                require(
                    isinstance(compared_entries, list)
                    and len(compared_entries) >= 1,
                    f"{path}.context_entry_decision.compared_entries must "
                    "contain at least one candidate with coverage evidence",
                    errors,
                )
                selected_candidates: list[str] = []
                boundary_types: list[str] = []
                if isinstance(compared_entries, list):
                    for candidate_index, item in enumerate(compared_entries):
                        item_path = (
                            f"{path}.context_entry_decision."
                            f"compared_entries[{candidate_index}]"
                        )
                        require(
                            isinstance(item, dict),
                            f"{item_path} must be an object",
                            errors,
                        )
                        if not isinstance(item, dict):
                            continue
                        for key in (
                            "entry",
                            "story_arc",
                            "information_gained",
                            "return_effect",
                        ):
                            require(
                                isinstance(item.get(key), str)
                                and bool(item.get(key, "").strip()),
                                f"{item_path}.{key} must be non-empty",
                                errors,
                            )
                        boundary_type = item.get("boundary_type")
                        require(
                            boundary_type
                            in {
                                "latest_complete",
                                "natural_story",
                                "emotional_or_relationship_setup",
                            },
                            f"{item_path}.boundary_type is invalid",
                            errors,
                        )
                        if isinstance(boundary_type, str):
                            boundary_types.append(boundary_type)
                        require(
                            item.get("causal_chain_complete") is True,
                            f"{item_path}.causal_chain_complete must be true",
                            errors,
                        )
                        retention_beats = item.get("retention_beats")
                        require(
                            isinstance(retention_beats, list)
                            and len(retention_beats) > 0,
                            f"{item_path}.retention_beats must be a non-empty list",
                            errors,
                        )
                        if isinstance(retention_beats, list):
                            for beat_index, beat in enumerate(retention_beats):
                                require(
                                    isinstance(beat, str) and bool(beat.strip()),
                                    f"{item_path}.retention_beats[{beat_index}] "
                                    "must be non-empty",
                                    errors,
                                )
                        require(
                            item.get("dead_zone_risk")
                            in {"none", "low", "high"},
                            f"{item_path}.dead_zone_risk is invalid",
                            errors,
                        )
                        require(
                            isinstance(item.get("emotional_build"), bool),
                            f"{item_path}.emotional_build must be boolean",
                            errors,
                        )
                        require(
                            isinstance(item.get("selected"), bool),
                            f"{item_path}.selected must be boolean",
                            errors,
                        )
                        if item.get("selected") is True and isinstance(
                            item.get("entry"), str
                        ):
                            selected_candidates.append(item["entry"])
                            require(
                                item.get("dead_zone_risk") != "high",
                                f"{item_path}.dead_zone_risk cannot be high "
                                "for the selected candidate",
                                errors,
                            )
                require(
                    "latest_complete" in boundary_types,
                    f"{path}.context_entry_decision.compared_entries must "
                    "include a latest_complete candidate",
                    errors,
                )
                require(
                    len(selected_candidates) == 1,
                    f"{path}.context_entry_decision.compared_entries must "
                    "select exactly one candidate",
                    errors,
                )
                if len(selected_candidates) == 1:
                    require(
                        selected_candidates[0]
                        == context_decision.get("selected_entry"),
                        f"{path}.context_entry_decision.selected_entry must "
                        "match the selected compared_entries candidate",
                        errors,
                    )
                forward_check = context_decision.get("forward_check")
                require(
                    isinstance(forward_check, dict),
                    f"{path}.context_entry_decision.forward_check must be an object",
                    errors,
                )
                if isinstance(forward_check, dict):
                    for check_key in (
                        "standalone_entry",
                        "causal_chain_complete",
                        "narrative_arc_complete",
                        "emotional_investment_before_catchup",
                        "change_before_catchup",
                        "clean_opening_echo_and_resume",
                    ):
                        require(
                            forward_check.get(check_key) is True,
                            f"{path}.context_entry_decision.forward_check."
                            f"{check_key} must be true",
                            errors,
                        )
                post_stop = context_decision.get("post_opening_stop")
                require(
                    isinstance(post_stop, dict),
                    f"{path}.context_entry_decision.post_opening_stop must be "
                    "an object",
                    errors,
                )
                if isinstance(post_stop, dict):
                    require(
                        post_stop.get("rule")
                        == "first_new_suspense_after_payoff",
                        f"{path}.context_entry_decision.post_opening_stop.rule "
                        "must be 'first_new_suspense_after_payoff'",
                        errors,
                    )
                    require(
                        isinstance(post_stop.get("description"), str)
                        and bool(post_stop.get("description", "").strip()),
                        f"{path}.context_entry_decision.post_opening_stop."
                        "description must be non-empty",
                        errors,
                    )
                rejected = context_decision.get("rejected_later_entries")
                require(
                    isinstance(rejected, list),
                    f"{path}.context_entry_decision.rejected_later_entries must be a list",
                    errors,
                )
                if isinstance(rejected, list):
                    for rejected_index, item in enumerate(rejected):
                        item_path = (
                            f"{path}.context_entry_decision."
                            f"rejected_later_entries[{rejected_index}]"
                        )
                        require(
                            isinstance(item, dict),
                            f"{item_path} must be an object",
                            errors,
                        )
                        if isinstance(item, dict):
                            for key in ("entry", "reason"):
                                require(
                                    isinstance(item.get(key), str)
                                    and bool(item.get(key, "").strip()),
                                    f"{item_path}.{key} must be non-empty",
                                    errors,
                                )
            transition = variant.get("reset_transition")
            require(
                isinstance(transition, dict),
                f"{path}.reset_transition must be an object",
                errors,
            )
            if isinstance(transition, dict):
                require(
                    transition.get("kind")
                    == "freeze_then_question_card_then_rewind",
                    f"{path}.reset_transition.kind must be "
                    "'freeze_then_question_card_then_rewind'",
                    errors,
                )
                freeze = transition.get("freeze")
                require(
                    isinstance(freeze, dict),
                    f"{path}.reset_transition.freeze must be an object",
                    errors,
                )
                if isinstance(freeze, dict):
                    expected_freeze = {
                        "duration": 0.8,
                        "visual": "static",
                        "audio": "silence",
                    }
                    for key, value in expected_freeze.items():
                        require(
                            freeze.get(key) == value,
                            f"{path}.reset_transition.freeze.{key} must be "
                            f"{value!r}",
                            errors,
                        )
                card = transition.get("card")
                require(
                    isinstance(card, dict),
                    f"{path}.reset_transition.card must be an object",
                    errors,
                )
                if isinstance(card, dict):
                    require(
                        card.get("duration") == 2.0,
                        f"{path}.reset_transition.card.duration must be 2.0",
                        errors,
                    )
                    require(
                        card.get("background") == "black",
                        f"{path}.reset_transition.card.background must be 'black'",
                        errors,
                    )
                    require(
                        card.get("audio") == "silence",
                        f"{path}.reset_transition.card.audio must be 'silence'",
                        errors,
                    )
                    require(
                        card.get("design") == "two_line_centered",
                        f"{path}.reset_transition.card.design must be "
                        "'two_line_centered'",
                        errors,
                    )
                    text = card.get("text")
                    require(
                        isinstance(text, dict),
                        f"{path}.reset_transition.card.text must be an object",
                        errors,
                    )
                    if isinstance(text, dict):
                        for key in ("line_1", "line_2"):
                            require(
                                isinstance(text.get(key), str)
                                and bool(text.get(key, "").strip()),
                                f"{path}.reset_transition.card.text.{key} "
                                "must be non-empty",
                                errors,
                            )
                rewind = transition.get("rewind")
                require(
                    isinstance(rewind, dict),
                    f"{path}.reset_transition.rewind must be an object",
                    errors,
                )
                if isinstance(rewind, dict):
                    expected = {
                        "duration": 1.0,
                        "source_role": "reset_context",
                        "coverage": "full_range",
                        "audio": "rewind_sfx",
                        "landing": "first_frame",
                        "resume": "second_frame",
                    }
                    for key, value in expected.items():
                        require(
                            rewind.get(key) == value,
                            f"{path}.reset_transition.rewind.{key} must be "
                            f"{value!r}",
                            errors,
                        )
            roles = [
                item.get("role")
                for item in variant.get("ranges", [])
                if isinstance(item, dict)
            ]
            require(
                "reset_context" in roles,
                f"{path} must contain reset_context",
                errors,
            )
            require(
                roles.count("opening_echo") == 1,
                f"{path} must contain exactly one opening_echo",
                errors,
            )
            require(
                "resume_after_opening" in roles,
                f"{path} must contain resume_after_opening",
                errors,
            )
            reset_index = roles.index("reset_context") if "reset_context" in roles else -1
            echo_index = (
                roles.index("opening_echo") if "opening_echo" in roles else -1
            )
            resume_index = (
                roles.index("resume_after_opening")
                if "resume_after_opening" in roles
                else -1
            )
            require(
                reset_index == 1,
                f"{path}.reset_context must immediately follow opening_window",
                errors,
            )
            require(
                echo_index == reset_index + 1,
                f"{path}.opening_echo must immediately follow reset_context",
                errors,
            )
            require(
                resume_index == echo_index + 1,
                f"{path}.resume_after_opening must immediately follow opening_echo",
                errors,
            )
            if (
                echo_index >= 0
                and isinstance(ranges, list)
                and echo_index < len(ranges)
                and isinstance(ranges[echo_index], dict)
                and isinstance(opening, dict)
            ):
                echo = ranges[echo_index]
                require(
                    echo.get("source_video") == opening.get("source_video")
                    and echo.get("episode") == opening.get("episode"),
                    f"{path}.opening_echo must use the selected opening source",
                    errors,
                )
                echo_start = echo.get("start")
                echo_end = echo.get("end")
                opening_start = opening.get("start")
                opening_end = opening.get("end")
                require(
                    is_number(echo_start)
                    and is_number(opening_start)
                    and echo_start > opening_start,
                    f"{path}.opening_echo must be a proper ending subrange of "
                    "selected_opening",
                    errors,
                )
                require(
                    echo_end == opening_end,
                    f"{path}.opening_echo.end must equal selected_opening.end",
                    errors,
                )

    return errors


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: validate_edit_plan.py <edit-plan.json>", file=sys.stderr)
        return 2

    path = Path(sys.argv[1])
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    errors = validate_plan(plan)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"OK: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
