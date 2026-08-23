"""端到端 QA 评测：走真实 /qa/ask 链路（Agent+检索+拒答+引用）。

消耗真实百炼 token，手动触发；CI 不跑。

用法：
  python scripts/evaluate_qa.py --base-url http://127.0.0.1:8765 --token <JWT> \
      [--limit 20] [--level L2,L3] [--category RT,LG]

判定三关：
  ① 拒答正确：response.refused == should_refuse
  ② 关键词覆盖（非拒答题）：answer 命中 ≥1 个 expected_keywords
  ③ 来源一致（非拒答题）：sources 中存在 expected_doc 前缀匹配
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.eval_metrics import aggregate, keyword_coverage  # noqa: E402


def _name(source: object) -> str:
    text = str(source or "")
    return Path(text.replace("\\", "/")).name


def ask(base_url: str, token: str, question: str, session_id: str) -> dict:
    body = json.dumps({"question": question, "session_id": session_id}).encode()
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/qa/ask",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode())


def judge(row: dict, resp: dict) -> dict:
    reasons: list[str] = []
    refused = bool(resp.get("refused"))
    refuse_ok = refused == row["should_refuse"]
    if not refuse_ok:
        reasons.append("refused_mismatch")
    kw_ok = src_ok = True
    if not row["should_refuse"]:
        kw_ok = keyword_coverage(resp.get("answer", ""), row["expected_keywords"])
        if not kw_ok:
            reasons.append("keyword_miss")
        src_names = [_name(s.get("source")) for s in resp.get("sources", [])]
        src_ok = any(name.startswith(row["expected_doc"]) for name in src_names)
        if not src_ok:
            reasons.append("source_miss")
    return {
        "id": row["id"],
        "category": row["category"],
        "level": row["level"],
        "passed": refuse_ok and kw_ok and src_ok,
        "refuse_ok": refuse_ok,
        "kw_ok": kw_ok,
        "src_ok": src_ok,
        "reasons": reasons,
        "answer_head": resp.get("answer", "")[:120],
        "sources": [s.get("source") for s in resp.get("sources", [])][:3],
    }


def write_report(results: list[dict], summary: dict, report_dir: Path) -> tuple[Path, Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    md_path = report_dir / f"qa-{stamp}.md"
    json_path = report_dir / f"qa-{stamp}.json"
    md = [
        "# QA 端到端评测",
        "",
        f"- 时间：{stamp}｜通过率 {summary['passed']}/{summary['total']}"
        f" = {summary['pass_rate']:.1%}",
        "",
        "## 分层",
        "",
        "| 层级 | total | passed | pass_rate |",
        "|---|---|---|---|",
    ]
    for level, stat in summary["by_level"].items():
        md.append(
            f"| {level} | {stat['total']} | {stat['passed']} | {stat['pass_rate']:.1%} |"
        )
    md += ["", "## 失败题明细", ""]
    md += [
        f"- `{r['id']}` {','.join(r['reasons'])}｜答：{r.get('answer_head', '')[:60]}"
        for r in results
        if not r["passed"]
    ]
    md_path.write_text("\n".join(md), encoding="utf-8")
    json_path.write_text(
        json.dumps({"rows": results, "summary": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return md_path, json_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", default=str(ROOT / "evals" / "golden_set.jsonl"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--level", default=None, help="逗号分隔，如 L2,L3")
    parser.add_argument("--category", default=None, help="逗号分隔，如 RT,LG")
    parser.add_argument("--report-dir", default=str(ROOT / "evals" / "reports"))
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in Path(args.golden).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.level:
        levels = set(args.level.split(","))
        rows = [r for r in rows if r["level"] in levels]
    if args.category:
        cats = set(args.category.split(","))
        rows = [r for r in rows if r["category"] in cats]
    if args.limit:
        rows = rows[: args.limit]

    results = []
    for i, row in enumerate(rows, 1):
        try:
            resp = ask(
                args.base_url, args.token, row["question"], session_id=f"eval-{row['id']}"
            )
            results.append(judge(row, resp))
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "id": row["id"],
                    "category": row["category"],
                    "level": row["level"],
                    "passed": False,
                    "reasons": [f"http_error:{exc}"],
                }
            )
        tail = (
            "PASS"
            if results[-1]["passed"]
            else "FAIL " + ",".join(results[-1]["reasons"])
        )
        print(f"[{i}/{len(rows)}] {results[-1]['id']} {tail}")

    summary = aggregate(results)
    md_path, _ = write_report(results, summary, Path(args.report_dir))
    print(f"pass={summary['pass_rate']:.1%} 报告：{md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
