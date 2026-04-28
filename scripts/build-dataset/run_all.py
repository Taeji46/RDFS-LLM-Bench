"""
Run all dataset generation scripts in scripts/build-dataset.

Usage:
    python scripts/build-dataset/run_all.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT_ORDER = [
    "from-samples/gen_rk.py",
    "from-samples/gen_ls.py",
    "from-samples/gen_gs-gsc.py",
    "standalone/gen_ns.py",
    "standalone/gen_nsc.py",
    "standalone/gen_rva.py",
]


def main() -> int:
    base_dir = Path(__file__).resolve().parent

    print("Running all dataset generation scripts...\n")
    for idx, rel_path in enumerate(SCRIPT_ORDER, start=1):
        script_path = base_dir / rel_path
        if not script_path.exists():
            print(f"[{idx}/{len(SCRIPT_ORDER)}] Missing script: {script_path}")
            return 1

        print(f"[{idx}/{len(SCRIPT_ORDER)}] Running: {rel_path}")
        result = subprocess.run([sys.executable, str(script_path)], cwd=base_dir)
        if result.returncode != 0:
            print(f"Failed: {rel_path} (exit code {result.returncode})")
            return result.returncode

    print("\nAll dataset generation scripts completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
