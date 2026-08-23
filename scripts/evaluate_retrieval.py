"""检索层离线评测：rewrite → embed → pgvector top-k → distance 过滤。

只评检索不调 LLM；需要 .env 配置 DASHSCOPE_API_KEY 且语料已导入指定租户。

用法：
  python scripts/evaluate_retrieval.py --tenant-id cloudcotton [--k 5] [--limit N]

输出：evals/reports/retrieval-<时间戳>.md / .json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.eval_metrics import aggregate, hit_at_k, reciprocal_rank  # noqa: E402
from app.core.pgvector_store import (  # noqa: E402
    pgvector_similarity_search_with_score,
)
from app.core.query_rewriter import rewrite_query  # noqa: E402
from app.core.retriever_tool import MAX_DISTANCE  # noqa: E402


def load_golden(path: Path, limit: int | None) -> list[dict]:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows[:limit] if limit else rows


def _name(source: object) -> str:
    """source 可能是完整路径/URL，统一取文件名做前缀比较。"""
    text = str(source or "")
    return Path(text.replace("\\", "/")).name


def evaluate_one(row: dict, k: int, tenant_id: str) -> dict:
    started = time.perf_counter()
    query = rewrite_query(row["question"])
    results = asyncio.run(
        pgvector_similarity_search_with_score(query, k=k, tenant_id=tenant_id)
    )
    latency_ms = (time.perf_counter() - started) * 1000
    ranked_names = [_name(doc.metadata.get("source")) for doc, _ in results]
    kept_names = [
        name for name, (_, score) in zip(ranked_names, results) if score <= MAX_DISTANCE
    ]
    expected = row.get("expected_doc")
    if expected is None:
        # OOS 题：期望"阈值过滤后检索不到任何东西"（知识库确实不涵盖）。
        passed = len(kept_names) == 0
        hit5 = passed
        rr = 1.0 if passed else 0.0
    else:
        hit5 = hit_at_k(kept_names or ranked_names, expected, k)
        rr = reciprocal_rank(ranked_names, expected)
        passed = hit5 and rr > 0
    return {
        "id": row["id"],
        "category": row["category"],
        "level": row["level"],
        "passed": passed,
        "hit": hit5,
        "rr": rr,
        "latency_ms": latency_ms,
        "top_sources": ranked_names[:3],
        "distances": [round(score, 4) for _, score in results[:3]],
    }


def write_report(
    rows: list[dict], summary: dict, report_dir: Path
) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"retrieval-{stamp}.md"
    json_path = report_dir / f"retrieval-{stamp}.json"
    mrr = sum(r["rr"] for r in rows) / len(rows) if rows else 0.0
    latencies = sorted(r["latency_ms"] for r in rows)
    p50 = latencies[len(latencies) // 2] if latencies else 0.0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
    lines = [
        "# 检索评测报告",
        "",
        f"- 时间：{stamp}｜题目：{summary['total']}"
        f"｜hit@5 通过：{summary['passed']}（{summary['pass_rate']:.1%}）",
        f"- MRR：{mrr:.3f}｜延迟 p50={p50:.0f}ms p95={p95:.0f}ms"
        f"｜MAX_DISTANCE={MAX_DISTANCE}",
        "",
        "## 分层",
        "",
        "| 层级 | total | passed | pass_rate |",
        "|---|---|---|---|",
    ]
    for level, stat in summary["by_level"].items():
        lines.append(
            f"| {level} | {stat['total']} | {stat['passed']} | {stat['pass_rate']:.1%} |"
        )
    lines += ["", "## 分类别", "", "| 类别 | total | passed | pass_rate |", "|---|---|---|---|"]
    for category, stat in summary["by_category"].items():
        lines.append(
            f"| {category} | {stat['total']} | {stat['passed']} | {stat['pass_rate']:.1%} |"
        )
    lines += ["", "## 未命中题目（迭代抓手）", ""]
    for r in rows:
        if not r["hit"]:
            lines.append(f"- `{r['id']}` top3={r['top_sources']} dist={r['distances']}")
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path.write_text(
        json.dumps({"rows": rows, "summary": summary, "mrr": mrr}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default=str(ROOT / "evals" / "golden_set.jsonl"))
    parser.add_argument("--tenant-id", default="cloudcotton")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--report-dir", default=str(ROOT / "evals" / "reports"))
    args = parser.parse_args()

    golden = load_golden(Path(args.golden), args.limit)
    print(
        f"评测 {len(golden)} 题（tenant={args.tenant_id}, k={args.k}, "
        f"MAX_DISTANCE={MAX_DISTANCE}）"
    )
    rows = [evaluate_one(row, args.k, args.tenant_id) for row in golden]
    summary = aggregate(
        [{key: r[key] for key in ("id", "category", "level", "passed")} for r in rows]
    )
    md_path, _ = write_report(rows, summary, Path(args.report_dir))
    print(f"hit@5={summary['pass_rate']:.1%} 报告：{md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
