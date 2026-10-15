"""Opt-in real render on generated test signals; never uses production footage."""

import os
from array import array
from pathlib import Path
import subprocess
import tempfile
import unittest

from pipeline.media_checks import inspect
from pipeline.workflow import ROOT, baseline_command, wrapper_command


@unittest.skipUnless(os.environ.get("SUCAI_RENDER_SMOKE") == "1", "Set SUCAI_RENDER_SMOKE=1 for isolated macOS render test")
class RenderSmokeTests(unittest.TestCase):
    def test_compiled_ranges_select_actual_video_and_audio_in_order(self):
        with tempfile.TemporaryDirectory(prefix="sucai-range-regression-") as directory:
            base = Path(directory)
            ffmpeg = str(ROOT / "bin/macos-arm64/ffmpeg")
            def execute(command):
                result = subprocess.run(command, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace")[-4000:])
                return result.stdout
            source = str(base / "red440-blue880.mp4")
            execute([ffmpeg, "-nostdin", "-n", "-f", "lavfi", "-i", "color=c=red:s=64x64:r=30:d=1",
                     "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=30:d=1",
                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                     "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=48000:duration=1",
                     "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v];[2:a][3:a]concat=n=2:v=0:a=1[a]",
                     "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-c:a", "aac", source])
            recipe = {"ranges": [{"source_video": source, "start": 1, "end": 1.5},
                                 {"source_video": source, "start": 0, "end": 0.5}],
                      "video": {"width": 64, "height": 64, "fps": "30/1"},
                      "audio": {"sample_rate": 48000, "channels": 1},
                      "encoding": {"-c:v": "libx264", "-c:a": "aac", "-crf": "18"}}
            output = str(base / "blue880-red440.m4v")
            execute(baseline_command(recipe, ffmpeg, output, {source}))
            for start, channel, frequency in (("0.1", 2, 880), ("0.6", 0, 440)):
                pixels = execute([ffmpeg, "-v", "error", "-ss", start, "-i", output, "-frames:v", "1",
                                  "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"])
                self.assertEqual(len(pixels), 64 * 64 * 3)
                self.assertGreater(sum(pixels[channel::3]) / (64 * 64), 200)
                opposite = 0 if channel == 2 else 2
                self.assertLess(sum(pixels[opposite::3]) / (64 * 64), 30)
                sound = execute([ffmpeg, "-v", "error", "-ss", start, "-i", output, "-t", "0.25", "-vn",
                                 "-ac", "1", "-ar", "48000", "-f", "f32le", "pipe:1"])
                samples = array("f")
                samples.frombytes(sound)
                crossings = sum((a >= 0) != (b >= 0) for a, b in zip(samples, samples[1:]))
                measured = crossings / 2 / (len(samples) / 48000)
                self.assertAlmostEqual(measured, frequency, delta=40)

    def test_existing_renderers_with_fractional_fps(self):
        with tempfile.TemporaryDirectory(prefix="sucai-render-smoke-") as directory:
            base = Path(directory)
            ffmpeg = ROOT / "bin/macos-arm64/ffmpeg"
            ffprobe = ROOT / "bin/macos-arm64/ffprobe"
            environment = {**os.environ, "FFMPEG_PATH": str(ffmpeg), "FFPROBE_PATH": str(ffprobe)}
            def execute(command):
                result = subprocess.run([str(arg) for arg in command], env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr[-5000:])
            source = base / "signal.mp4"
            execute([ffmpeg, "-nostdin", "-n", "-f", "lavfi", "-i", "testsrc2=size=360x640:rate=30000/1001",
                     "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "8.008", "-c:v", "libx264",
                     "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", source])
            variant = {"id": "cold_open", "ranges": [
                {"source_video": str(source), "start": 0, "end": 1.001, "role": "opening_window"},
                {"source_video": str(source), "start": 1.001, "end": 3.003, "role": "reset_context"},
                {"source_video": str(source), "start": 3.003, "end": 8.008, "role": "resume_after_opening"}],
                "reset_transition": {"freeze": {"duration": 0.8}, "card": {"duration": 2.0, "text": {"line_1": "WHAT HAPPENED?"}}, "rewind": {"duration": 1.0}},
                "opening_headline": {"lines": ["SYNTHETIC", "RENDER CHECK", "TEST SIGNAL"], "hold_duration": 3.0,
                                     "fade_duration": 1.0, "base_color": "#FFFFFF", "accent_color": "#FF4D4D"},
                "end_hold": {"duration": 1.0, "visual": "shake", "audio": {"kind": "silence"}}}
            current = base / "baseline.m4v"
            execute(baseline_command({"ranges": variant["ranges"], "video": {"width": 360, "height": 640, "fps": "30000/1001"},
                                     "audio": {"sample_rate": 48000, "channels": 2},
                                     "encoding": {"-c:v": "libx264", "-preset": "ultrafast", "-c:a": "aac"}},
                                     ffmpeg, current, {str(source)}))
            for step, name in (("rewind", "insert_rewind_transition"), ("headline", "overlay_opening_headline"), ("end", "apply_punch_end")):
                exe = base / name
                execute(["xcrun", "swiftc", "-parse-as-library", ROOT / "scripts" / (name + ".swift"), "-o", exe])
                output = base / (step + ".m4v")
                execute(wrapper_command({"variants": [variant]}, "cold_open", step, exe, current, output))
                current = output
            report = inspect(current, variant, {"ffmpeg": {"path": str(ffmpeg)}, "ffprobe": {"path": str(ffprobe)}})
            self.assertTrue(all(report["checks"].values()), report)


if __name__ == "__main__":
    unittest.main()
