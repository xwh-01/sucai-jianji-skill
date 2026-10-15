"""Retain the original test command after moving tests into tests/."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def load_tests(loader, tests, pattern):
    return loader.discover(str(Path(__file__).resolve().parents[1] / "tests"),
                           pattern="test_*.py",
                           top_level_dir=str(Path(__file__).resolve().parents[1]))


if __name__ == "__main__":
    unittest.main()
