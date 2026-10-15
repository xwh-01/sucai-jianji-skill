"""Read-only technical checks. These never certify narrative or visual quality."""

from fractions import Fraction
import json
import re
import subprocess


def inspect(path, variant, tools):
    probe_command = [tools["ffprobe"]["path"], "-v", "error", "-show_streams", "-show_format", "-of", "json"]
    def probe(source):
        return json.loads(subprocess.run([*probe_command, str(source)], check=True, capture_output=True, text=True).stdout)
    data = probe(path)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audios = [s for s in data["streams"] if s["codec_type"] == "audio"]
    sources = {r["source_video"] for r in variant["ranges"]}
    source_video = [next(s for s in probe(p)["streams"] if s["codec_type"] == "video") for p in sorted(sources)]
    output_rate = Fraction(video["r_frame_rate"])
    frame_rate = output_rate > 0 and Fraction(video["avg_frame_rate"]) == output_rate
    frame_rate = frame_rate and all(Fraction(s["r_frame_rate"]) == output_rate and
                                   Fraction(s["avg_frame_rate"]) == output_rate for s in source_video)
    orientation = all((s["width"] > s["height"]) == (video["width"] > video["height"]) for s in source_video)
    expected = sum(r["end"] - r["start"] for r in variant["ranges"]) + variant["end_hold"]["duration"]
    if variant["id"] == "cold_open":
        expected += sum(variant["reset_transition"][key]["duration"] for key in ("freeze", "card", "rewind"))
    tolerance = max(0.1, (len(variant["ranges"]) + 2) / float(output_rate)) if output_rate > 0 else 0.1
    decode = subprocess.run([tools["ffmpeg"]["path"], "-nostdin", "-v", "error", "-xerror", "-i", str(path),
                             "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"], capture_output=True, text=True)
    volume = subprocess.run([tools["ffmpeg"]["path"], "-nostdin", "-i", str(path), "-vn", "-af", "volumedetect",
                             "-f", "null", "-"], capture_output=True, text=True)
    match = re.search(r"max_volume:\s*(-?inf|[-+\d.]+)\s*dB", volume.stderr)
    non_silent = volume.returncode == 0 and match is not None and float(match.group(1)) > float("-inf")
    return {"checks": {"full_decode": decode.returncode == 0, "av_tracks": bool(audios),
                       "non_silent_audio": non_silent, "duration": abs(float(data["format"]["duration"]) - expected) <= tolerance,
                       "orientation": orientation, "frame_rate": frame_rate},
            "probe": data, "source_video_streams": source_video, "planned_duration": expected,
            "duration_tolerance": tolerance, "decode_error": decode.stderr, "volume_log": volume.stderr,
            "limitations": ["Technical checks do not certify lip sync, cuts, titles, transition content or continuous viewing.",
                            "Mixed/VFR sources require an explicitly reviewed normalization workflow; no silent frame-rate conversion."]}
