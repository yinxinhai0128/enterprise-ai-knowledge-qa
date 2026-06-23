"""Fail when pytest leaves enterprise-kb temporary roots behind."""

from __future__ import annotations

import tempfile
from pathlib import Path


def main() -> int:
    temp_root = Path(tempfile.gettempdir()).resolve()
    leftovers = sorted(path for path in temp_root.glob("kb_test_*") if path.is_dir())
    if leftovers:
        for path in leftovers:
            print(f"LEFTOVER: {path.name}")
        print(f"test_cleanup: leftovers={len(leftovers)}")
        return 1
    print("test_cleanup: leftovers=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
