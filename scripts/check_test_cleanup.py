"""Fail when pytest leaves enterprise-kb temporary roots behind."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

STALE_INACCESSIBLE_SECONDS = 24 * 60 * 60


def main() -> int:
    temp_root = Path(tempfile.gettempdir()).resolve()
    leftovers: list[Path] = []
    stale_leftovers: list[Path] = []
    now = time.time()
    for path in sorted(temp_root.glob("kb_test_*")):
        if not path.is_dir():
            continue
        stat = path.stat()
        age = max(now - stat.st_ctime, now - stat.st_mtime)
        if age >= STALE_INACCESSIBLE_SECONDS:
            stale_leftovers.append(path)
            continue
        try:
            next(path.iterdir(), None)
        except OSError:
            pass
        leftovers.append(path)
    if leftovers:
        for path in leftovers:
            print(f"LEFTOVER: {path.name}")
        print(f"test_cleanup: leftovers={len(leftovers)}")
        return 1
    for path in stale_leftovers:
        print(f"STALE_LEFTOVER_IGNORED: {path.name}")
    print("test_cleanup: leftovers=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
