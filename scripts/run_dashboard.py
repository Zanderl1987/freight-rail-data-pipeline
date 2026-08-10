#!/usr/bin/env python
"""
Convenience script to launch the Streamlit dashboard.
Usage:
    python scripts/run_dashboard.py [--port 8501]
"""
from __future__ import annotations

if __name__ == "__main__":
    import subprocess
    import sys
    from pathlib import Path

    _repo_root = Path(__file__).resolve().parent.parent
    dashboard = _repo_root / "src" / "freight_rail_pipeline" / "reporting" / "dashboard.py"
    # S603: argv is a fixed list (sys.executable + literal args), no user input.
    sys.exit(subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard)]).returncode)  # noqa: S603
