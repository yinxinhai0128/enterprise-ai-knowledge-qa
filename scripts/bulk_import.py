#!/usr/bin/env python3
"""批量导入文档到知识库。

用法：
  python scripts/bulk_import.py --dir /path/to/docs --token <admin_jwt> [--dry-run] [--api-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SUPPORTED_EXTS = frozenset({".pdf", ".docx", ".xlsx", ".txt"})


def upload_file(path: Path, token: str, api_url: str) -> bool:
    boundary = f"----WebKitFormBoundary{int(time.time() * 1000)}"
    with open(path, "rb") as fh:
        file_bytes = fh.read()

    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

    req = urllib.request.Request(
        f"{api_url.rstrip('/')}/documents/upload",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=60)
        return True
    except urllib.error.HTTPError as exc:
        print(f" → HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f" → 错误: {exc}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="批量导入文档到知识库")
    parser.add_argument("--dir", required=True, help="文档所在目录")
    parser.add_argument("--token", required=True, help="管理员 JWT Token")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API 地址")
    parser.add_argument("--dry-run", action="store_true", help="预览模式，不实际上传")
    args = parser.parse_args()

    doc_dir = Path(args.dir)
    if not doc_dir.is_dir():
        print(f"目录不存在: {doc_dir}", file=sys.stderr)
        return 1

    files = sorted(f for f in doc_dir.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS)
    if not files:
        print("目录中没有可导入的文件（支持：.pdf .docx .xlsx .txt）")
        return 0

    mode = "（预览模式，不上传）" if args.dry_run else ""
    print(f"发现 {len(files)} 个文件{mode}")

    success = fail = 0
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name}", end="", flush=True)
        if args.dry_run:
            print(" → 跳过")
            continue
        ok = False
        for attempt in range(3):
            print("." if attempt else " 上传中", end="", flush=True)
            ok = upload_file(path, args.token, args.api_url)
            if ok:
                break
            if attempt < 2:
                time.sleep(5)
        if ok:
            print(" ✓")
            success += 1
        else:
            print(" ✗")
            fail += 1

    if not args.dry_run:
        print(f"\n完成：成功 {success} 个，失败 {fail} 个")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
