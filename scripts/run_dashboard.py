#!/usr/bin/env python
"""
Convenience script to launch the Streamlit dashboard.
Usage:
    python scripts/run_dashboard.py [--port 8501]
"""
from __future__ import annotations

if __name__ == "__main__":
    import subprocess, sys
    from pathlib import Path

    dashboard = Path(__file__).resolve().parent.parent / "src" / "freight_rail_pipeline" / "reporting" / "dashboard.py"
    sys.exit(subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard)]).returncode)
