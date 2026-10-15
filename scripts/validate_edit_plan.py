#!/usr/bin/env python3
"""Backward-compatible entry point for edit-plan validation."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline.validation import *  # noqa: F401,F403


if __name__ == "__main__":
    raise SystemExit(main())
