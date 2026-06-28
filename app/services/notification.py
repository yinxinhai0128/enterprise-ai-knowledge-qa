"""运营通知服务：目前支持企业微信群机器人。"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from loguru import logger


async def notify_human_review(
    *,
    question: str,
    category: str,
    task_id: int | None,
    webhook_url: str,
) -> None:
    """向企业微信群机器人发送人工审核提醒（失败只记日志，不抛异常）。"""
    if not webhook_url:
        return

    # 企业微信机器人 Markdown 消息格式
    question_preview = question[:50] + ("…" if len(question) > 50 else "")
    content = (
        f"## 🔔 人工审核提醒\n"
        f"**问题摘要**：{question_preview}\n"
        f"**触发类别**：{category or '未知'}\n"
        f"**任务 ID**：{task_id or '创建中'}\n"
        f"> 请登录管理后台处理此任务"
    )
    payload = json.dumps({"msgtype": "markdown", "markdown": {"content": content}}, ensure_ascii=False).encode("utf-8")

    def _send() -> None:
        req = urllib.request.Request(
            webhook_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)

    try:
        import asyncio
        await asyncio.get_event_loop().run_in_executor(None, _send)
    except urllib.error.HTTPError as exc:
        logger.warning("企业微信通知 HTTP 失败 status={} task_id={}", exc.code, task_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("企业微信通知失败 task_id={} err={}", task_id, exc)
