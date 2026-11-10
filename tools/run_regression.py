#!/usr/bin/env python3
"""Run the 39-case offline fault-attribution matrix from a fresh clone."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from geoagent_m6 import regression  # noqa: E402


def main() -> int:
    report = regression.run_matrix()
    print(json.dumps({
        "total": report["total_cases"],
        "passed": report["passed"],
        "failed": report["failed"],
        "by_category": report["by_category"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
