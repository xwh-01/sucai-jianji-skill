"""Required playback windows, not an automated opinion about story quality."""

import math


def review_windows(variant, output_duration):
    if not math.isfinite(output_duration) or output_duration <= 0:
        raise ValueError("Actual output duration must be positive")
    result = {}
    def add(name, start, end):
        result[name] = {"start": max(0, min(start, output_duration)),
                        "end": min(output_duration, end), "mode": "continuous_av"}
    add("first_second", 0, 1)
    add("headline", 0, 4)
    cold = variant["id"] == "cold_open"
    extra = sum(variant["reset_transition"][k]["duration"] for k in ("freeze", "card", "rewind")) if cold else 0
    elapsed = 0
    for index, item in enumerate(variant["ranges"]):
        duration = item["end"] - item["start"]
        if cold and item["role"] == "reset_context":
            add(f"context-{index}", elapsed - 0.5, elapsed + duration + 0.5)
        if cold and item["role"] == "opening_echo":
            add("echo_resume", elapsed - 0.5, elapsed + duration + 1)
        elapsed += duration
        if index == 0 and cold:
            add("cold_transition", elapsed - 0.5, elapsed + extra + 1)
            elapsed += extra
        elif index < len(variant["ranges"]) - 1:
            add(f"connection-{index}", elapsed - 0.5, elapsed + 0.5)
    add("ending", output_duration - variant["end_hold"]["duration"] - 1, output_duration)
    return result


def validate_content(review, required, output_sha256, plan_sha256):
    if review.get("output_sha256") != output_sha256 or review.get("plan_sha256") != plan_sha256:
        raise ValueError("Content review refers to a different video or plan")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError("Record who actually performed the content review")
    windows = review.get("windows", {})
    for name, expected in required.items():
        observed = windows.get(name, {})
        if observed.get("status") != "passed" or observed.get("mode") != "continuous_av":
            raise ValueError("Continuous audiovisual review is incomplete: " + name)
        if any(observed.get(key) != expected[key] for key in ("start", "end")):
            raise ValueError("Content review window differs from actual required window: " + name)
        if not isinstance(observed.get("observation"), str) or not observed["observation"].strip():
            raise ValueError("Record the actual observation for review window: " + name)
        if not observed.get("evidence"):
            raise ValueError("Missing playback/review evidence for: " + name)
