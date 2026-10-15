from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pipeline.baseline import baseline_command, merged_ranges, verify_sources


class BaselineTests(unittest.TestCase):
    def setUp(self):
        self.recipe = {"ranges": [{"source_video": "/source.mp4", "start": 10, "end": 20}],
                       "video": {"width": 360, "height": 640, "fps": "30000/1001"},
                       "audio": {"sample_rate": 48000, "channels": 2},
                       "encoding": {"-c:v": "libx264", "-c:a": "aac", "-crf": "18"}}

    def command(self):
        return baseline_command(self.recipe, "ffmpeg", "new.m4v", {"/source.mp4"})

    def test_times_are_compiled_for_both_audio_and_video(self):
        command = self.command()
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("trim=start=10:end=20", graph)
        self.assertIn("atrim=start=10:end=20", graph)
        self.assertIn("fps=30000/1001", graph)
        self.assertNotIn("-ss", command)
        self.assertNotIn("-t", command)
        self.assertIn("-n", command)

    def test_previously_accepted_mismatched_argv_is_rejected(self):
        self.recipe["argv"] = ["-i", "/source.mp4", "-ss", "0", "-t", "5", "{output}"]
        with self.assertRaisesRegex(ValueError, "Free-form"):
            self.command()

    def test_encoding_cannot_override_timeline(self):
        for flag in ("-ss", "-t", "-filter_complex", "-vf", "-r", "-map", "-i", "-y"):
            with self.subTest(flag=flag):
                recipe = deepcopy(self.recipe)
                recipe["encoding"][flag] = "0"
                with self.assertRaises(ValueError):
                    baseline_command(recipe, "ffmpeg", "out.m4v", {"/source.mp4"})

    def test_merge_only_adjacent_contiguous_source_ranges(self):
        ranges = [{"source_video": "/a", "start": 1, "end": 2}, {"source_video": "/a", "start": 2, "end": 3},
                  {"source_video": "/a", "start": 1, "end": 2}, {"source_video": "/b", "start": 2, "end": 3}]
        result = merged_ranges(ranges)
        self.assertEqual(len(result), 3)
        self.assertEqual((result[0]["start"], result[0]["end"]), (1, 3))
        self.assertEqual(result[1]["start"], 1)

    def test_invalid_times_fail(self):
        for start, end in ((-1, 2), (3, 2), (0, float("nan")), (0, float("inf")), (False, 2)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                merged_ranges([{"source_video": "/a", "start": start, "end": end}])

    def test_source_preflight_rejects_rounding_and_out_of_bounds(self):
        data = {"format": {"duration": "30"}, "streams": [
            {"codec_type": "video", "width": 360, "height": 640, "r_frame_rate": "30000/1001", "avg_frame_rate": "30000/1001"},
            {"codec_type": "audio"}]}
        def probe(*args, **kwargs):
            return SimpleNamespace(stdout=json.dumps(data))
        with patch("pipeline.baseline.subprocess.run", side_effect=probe):
            self.assertTrue(verify_sources(self.recipe, "probe"))
            self.recipe["video"]["fps"] = "30/1"
            with self.assertRaisesRegex(ValueError, "frame rate"):
                verify_sources(self.recipe, "probe")
            self.recipe["video"]["fps"] = "30000/1001"
            self.recipe["ranges"][0]["end"] = 31
            with self.assertRaisesRegex(ValueError, "exceeds source duration"):
                verify_sources(self.recipe, "probe")
