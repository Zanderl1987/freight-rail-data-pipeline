#!/usr/bin/env python
"""
Convenience script to run the freight rail data pipeline.
Usage:
    python scripts/run_pipeline.py [--sources usda,fbx] [--date 2026-07-28]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from freight_rail_pipeline.reporting.cli import main

if __name__ == "__main__":
    main()
