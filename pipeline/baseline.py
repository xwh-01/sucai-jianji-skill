"""Compile locked source intervals, never caller-supplied timeline commands."""

from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
import subprocess


def require(condition, message):
    if not condition:
        raise ValueError(message)


def seconds(value):
    require(type(value) in (int, float), "Source times must be numeric")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError("Invalid source time") from exc
    require(result.is_finite() and result >= 0, "Source times must be finite and nonnegative")
    return result


def merged_ranges(ranges):
    require(isinstance(ranges, list) and ranges, "Locked ranges are required")
    result = []
    for item in ranges:
        start, end = seconds(item["start"]), seconds(item["end"])
        require(start < end, "Source end must follow start")
        source = item["source_video"]
        require(isinstance(source, str) and source.startswith("/"), "Absolute source path is required")
        if result and result[-1]["source_video"] == source and result[-1]["end"] == start:
            result[-1]["end"] = end
        else:
            result.append({"source_video": source, "start": start, "end": end})
    return result


def baseline_command(recipe, ffmpeg, output, sources):
    require("argv" not in recipe, "Free-form baseline argv is no longer accepted; use locked ranges and structured settings")
    require(set(recipe) == {"ranges", "video", "audio", "encoding"}, "Unexpected baseline recipe fields")
    ranges = merged_ranges(recipe["ranges"])
    require({r["source_video"] for r in ranges} == sources, "Baseline sources differ from the locked plan")
    video, audio = recipe["video"], recipe["audio"]
    require(set(video) == {"width", "height", "fps"}, "Explicit video width, height and rational fps are required")
    require(all(type(video[k]) is int and video[k] > 0 and video[k] % 2 == 0 for k in ("width", "height")),
            "Video dimensions must be positive even integers")
    require(isinstance(video["fps"], str), "Frame rate must be an explicit rational string")
    rate = Fraction(video["fps"])
    require(rate > 0, "Frame rate must be positive")
    fps = f"{rate.numerator}/{rate.denominator}"
    require(set(audio) == {"sample_rate", "channels"} and type(audio["sample_rate"]) is int and audio["sample_rate"] > 0
            and type(audio["channels"]) is int and audio["channels"] in (1, 2), "Explicit audio sample rate and mono/stereo channels are required")
    encoding = recipe["encoding"]
    allowed = {"-c:v", "-c:a", "-b:v", "-b:a", "-crf", "-preset", "-pix_fmt", "-movflags", "-threads", "-video_track_timescale"}
    require(isinstance(encoding, dict) and {"-c:v", "-c:a"} <= set(encoding) and set(encoding) <= allowed,
            "Encoding settings cannot override timeline, filters, inputs or output")
    require(encoding["-c:v"] != "copy" and encoding["-c:a"] != "copy", "Filtered baselines cannot use stream copy")
    require(all(isinstance(v, str) and v for v in encoding.values()), "Encoding values must be nonempty strings")
    command = [str(ffmpeg), "-nostdin", "-hide_banner", "-n"]
    filters = []
    layout = "mono" if audio["channels"] == 1 else "stereo"
    for index, item in enumerate(ranges):
        command += ["-i", item["source_video"]]
        span = f"start={item['start']}:end={item['end']}"
        filters.append(f"[{index}:v:0]trim={span},setpts=PTS-STARTPTS,"
                       f"scale={video['width']}:{video['height']},setsar=1,fps={fps}[v{index}]")
        filters.append(f"[{index}:a:0]atrim={span},asetpts=PTS-STARTPTS,"
                       f"aresample={audio['sample_rate']},aformat=sample_fmts=fltp:channel_layouts={layout}[a{index}]")
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(ranges)))
    filters.append(f"{pairs}concat=n={len(ranges)}:v=1:a=1[vout][aout]")
    command += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]", "-fps_mode", "cfr"]
    for key, value in encoding.items():
        command += [key, value]
    return [*command, str(output)]


def verify_sources(recipe, ffprobe):
    probes = {}
    rate = Fraction(recipe["video"]["fps"])
    ratio = recipe["video"]["width"] / recipe["video"]["height"]
    for item in merged_ranges(recipe["ranges"]):
        source = item["source_video"]
        if source not in probes:
            result = subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", source],
                                    capture_output=True, text=True, check=True)
            probes[source] = json.loads(result.stdout)
        probe = probes[source]
        video = next(s for s in probe["streams"] if s["codec_type"] == "video")
        require(any(s["codec_type"] == "audio" for s in probe["streams"]), "Source audio track is missing")
        require(Fraction(video["r_frame_rate"]) == rate and Fraction(video["avg_frame_rate"]) == rate,
                "Source frame rate differs from recipe; do not silently normalize or round it")
        require(abs(video["width"] / video["height"] / ratio - 1) < 0.01,
                "Recipe changes source aspect ratio; explicit crop/rotation requires separate review")
        require(item["end"] <= Decimal(probe["format"]["duration"]), "Locked interval exceeds source duration")
    return probes
