import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.media_checks import inspect


class MediaChecksTests(unittest.TestCase):
    def check(self, rate="30000/1001", output_rate=None, audio=True, volume="-3.0", decode=0, duration="3.003"):
        output_rate = output_rate or rate
        def result(command, **kwargs):
            if command[0] == "probe":
                fps = output_rate if command[-1] == "output" else rate
                streams = [{"codec_type": "video", "width": 360, "height": 640, "r_frame_rate": fps, "avg_frame_rate": fps}]
                if audio:
                    streams.append({"codec_type": "audio"})
                return SimpleNamespace(stdout=json.dumps({"streams": streams, "format": {"duration": duration}}))
            if "volumedetect" in command:
                return SimpleNamespace(returncode=0, stderr="max_volume: " + volume + " dB")
            return SimpleNamespace(returncode=decode, stderr="decode failure" if decode else "")
        variant = {"id": "continuous", "ranges": [{"source_video": "source", "start": 0, "end": 2.003}], "end_hold": {"duration": 1}}
        with patch("pipeline.media_checks.subprocess.run", side_effect=result):
            return inspect("output", variant, {"ffmpeg": {"path": "ffmpeg"}, "ffprobe": {"path": "probe"}})

    def test_fractional_frame_rate_preserved(self):
        self.assertTrue(all(self.check()["checks"].values()))

    def test_rounded_frame_rate_fails(self):
        self.assertFalse(self.check(output_rate="30/1")["checks"]["frame_rate"])

    def test_silent_media_fails(self):
        self.assertFalse(self.check(volume="-inf")["checks"]["non_silent_audio"])

    def test_missing_audio_fails(self):
        self.assertFalse(self.check(audio=False)["checks"]["av_tracks"])

    def test_decode_and_duration_fail_independently(self):
        checks = self.check(decode=1, duration="8")["checks"]
        self.assertFalse(checks["full_decode"])
        self.assertFalse(checks["duration"])


if __name__ == "__main__":
    unittest.main()
