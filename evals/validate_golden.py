"""黄金评测集校验：schema、枚举值、id 唯一性、OOS 约定。

用法：python evals/validate_golden.py [--golden evals/golden_set.jsonl]
退出码 0=通过；非 0=失败并列出问题行。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.eval_metrics import CATEGORIES, LEVELS  # noqa: E402

REQUIRED_KEYS = {
    "id",
    "category",
    "level",
    "question",
    "expected_doc",
    "expected_keywords",
    "should_refuse",
}


def validate(path: Path) -> list[str]:
    """返回错误列表；空列表表示通过。"""
    errors: list[str] = []
    seen_ids: set[str] = set()
    lines = path.read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"L{lineno}: JSON 解析失败 {exc}")
            continue
        missing = REQUIRED_KEYS - set(row)
        if missing:
            errors.append(f"L{lineno}: 缺字段 {sorted(missing)}")
            continue
        if row["id"] in seen_ids:
            errors.append(f"L{lineno}: id 重复 {row['id']}")
        seen_ids.add(row["id"])
        if row["category"] not in CATEGORIES:
            errors.append(f"L{lineno}: category 非法 {row['category']}")
        if row["level"] not in LEVELS:
            errors.append(f"L{lineno}: level 非法 {row['level']}")
        if row["should_refuse"]:
            if row["expected_doc"] is not None or row["level"] != "OOS":
                errors.append(f"L{lineno}: OOS 题 expected_doc 必须为 null 且 level=OOS")
            if row["expected_keywords"]:
                errors.append(f"L{lineno}: OOS 题 expected_keywords 必须为空")
        else:
            if not row["expected_doc"] or not row["expected_keywords"]:
                errors.append(
                    f"L{lineno}: 非 OOS 题必须给 expected_doc 和 expected_keywords"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--golden", default=str(Path(__file__).parent / "golden_set.jsonl")
    )
    args = parser.parse_args()
    golden_path = Path(args.golden)
    if not golden_path.is_file():
        print(f"评测集不存在: {golden_path}")
        return 1
    errors = validate(golden_path)
    if errors:
        print("\n".join(errors))
        return 1
    count = sum(
        1
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    print(f"OK: {count} questions valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
