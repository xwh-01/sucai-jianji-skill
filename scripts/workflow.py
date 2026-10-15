#!/usr/bin/env python3
"""Stable command entry point for the evidence-gated workflow."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.workflow import main


if __name__ == "__main__":
    raise SystemExit(main())
