"""Check stable entry points without running the media pipeline."""

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from pipeline import validation


ROOT = Path(__file__).resolve().parents[1]


class CompatibilityTests(unittest.TestCase):
    def test_validator_cli_matches_implementation(self):
        with tempfile.TemporaryDirectory() as cwd:
            invalid = Path(cwd) / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            malformed = Path(cwd) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            cases = [[], [str(ROOT / "references/validated-example.json")],
                     [str(invalid)], [str(malformed)],
                     [str(Path(cwd) / "missing.json")]]
            for args in cases:
                with self.subTest(args=args):
                    results = [subprocess.run(
                        [sys.executable, str(ROOT / entry), *args],
                        cwd=cwd, capture_output=True, text=True,
                    ) for entry in ("scripts/validate_edit_plan.py", "pipeline/validation.py")]
                    self.assertEqual(
                        (results[0].returncode, results[0].stdout, results[0].stderr),
                        (results[1].returncode, results[1].stdout, results[1].stderr),
                    )

    def test_legacy_import_exports_same_public_api(self):
        spec = importlib.util.spec_from_file_location(
            "legacy_validation", ROOT / "scripts/validate_edit_plan.py")
        legacy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(legacy)
        for name, value in vars(validation).items():
            if not name.startswith("_"):
                self.assertIs(getattr(legacy, name), value)

    def test_swift_entry_points_resolve_to_implementations(self):
        for name in ("overlay_opening_headline.swift", "insert_rewind_transition.swift",
                     "apply_punch_end.swift"):
            with self.subTest(name=name):
                entry = ROOT / "scripts" / name
                self.assertTrue(entry.is_symlink())
                self.assertEqual(entry.resolve(), ROOT / "pipeline/render" / name)
                self.assertGreater(entry.stat().st_size, 0)
