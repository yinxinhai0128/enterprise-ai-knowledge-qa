"""可配置、可版本化的敏感分类与角色访问策略。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.config import settings


@dataclass(frozen=True, slots=True)
class PolicyMatch:
    rule_id: str
    category: str
    version: str
    required_roles: frozenset[str]
    human_review: bool


@dataclass(frozen=True, slots=True)
class _CompiledRule:
    match: PolicyMatch
    pattern: re.Pattern[str]


@lru_cache(maxsize=8)
def _load(path_text: str, modified_ns: int) -> tuple[_CompiledRule, ...]:
    del modified_ns  # 仅作为缓存失效键。
    payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
    version = str(payload["version"])
    rules: list[_CompiledRule] = []
    for raw in payload["rules"]:
        rule_id = str(raw["id"])
        category = str(raw["category"])
        pattern = re.compile(str(raw["pattern"]), re.IGNORECASE)
        roles = frozenset(str(role) for role in raw.get("required_roles", []))
        rules.append(
            _CompiledRule(
                match=PolicyMatch(
                    rule_id=rule_id,
                    category=category,
                    version=version,
                    required_roles=roles,
                    human_review=bool(raw.get("human_review", False)),
                ),
                pattern=pattern,
            )
        )
    return tuple(rules)


def classify_question(question: str) -> list[PolicyMatch]:
    path = settings.sensitive_rules_path
    rules = _load(str(path.resolve()), path.stat().st_mtime_ns)
    return [rule.match for rule in rules if rule.pattern.search(question)]


def denied_match(
    matches: list[PolicyMatch], roles: frozenset[str]
) -> PolicyMatch | None:
    """返回首条角色不满足的分类规则；空角色集仅转人工、不拒绝。"""
    return next(
        (
            match
            for match in matches
            if match.required_roles and match.required_roles.isdisjoint(roles)
        ),
        None,
    )


def clear_policy_cache() -> None:
    _load.cache_clear()
