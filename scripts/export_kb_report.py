#!/usr/bin/env python3
"""导出知识库文档列表为 CSV。

用法：
  python scripts/export_kb_report.py --token <admin_jwt> [--output kb_report.csv] [--api-url http://localhost:8000]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="导出知识库文档列表")
    parser.add_argument("--token", required=True, help="管理员 JWT Token")
    parser.add_argument("--output", default="kb_report.csv", help="输出文件路径")
    parser.add_argument("--api-url", default="http://localhost:8000", help="API 地址")
    args = parser.parse_args()

    req = urllib.request.Request(
        f"{args.api_url.rstrip('/')}/documents/",
        headers={"Authorization": f"Bearer {args.token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            docs: list[dict] = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print(f"请求失败 HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"请求失败: {exc}", file=sys.stderr)
        return 1

    out_path = Path(args.output)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["id", "filename", "status", "created_at", "uploaded_by"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for doc in docs:
            writer.writerow({
                "id": doc.get("id", ""),
                "filename": doc.get("filename", ""),
                "status": doc.get("status", ""),
                "created_at": doc.get("created_at", ""),
                "uploaded_by": doc.get("uploaded_by", ""),
            })

    print(f"已导出 {len(docs)} 条记录到 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
