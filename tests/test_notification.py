"""运营通知服务的测试。"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock


@pytest.mark.asyncio
async def test_notify_skips_when_no_webhook():
    """没有 webhook URL 时不发请求。"""
    from app.services.notification import notify_human_review
    # 调用不应抛异常，也不应发任何 HTTP 请求
    await notify_human_review(
        question="测试问题",
        category="test",
        task_id=1,
        webhook_url="",
    )


@pytest.mark.asyncio
async def test_notify_sends_request_when_webhook_set():
    """有 webhook URL 时发送 HTTP POST（mock 掉网络）。"""
    from app.services.notification import notify_human_review
    import urllib.request

    call_args = {}
    original_urlopen = urllib.request.urlopen

    def mock_urlopen(req, timeout=None):
        call_args["url"] = req.full_url
        call_args["data"] = req.data
        call_args["method"] = req.method
        # 返回一个简单的 mock 响应对象
        class MockResp:
            status = 200
            def read(self): return b'{"errcode":0}'
            def __enter__(self): return self
            def __exit__(self, *a): pass
        return MockResp()

    with patch.object(urllib.request, "urlopen", mock_urlopen):
        await notify_human_review(
            question="测试问题，超过50字" * 3,
            category="薪资",
            task_id=42,
            webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=fake",
        )

    assert call_args.get("method") == "POST"
    assert b"markdown" in call_args.get("data", b"")
    assert b"42" in call_args.get("data", b"")


@pytest.mark.asyncio
async def test_notify_does_not_raise_on_http_error():
    """HTTP 错误时不抛异常（只记日志）。"""
    from app.services.notification import notify_human_review
    import urllib.error

    def mock_urlopen_error(req, timeout=None):
        raise urllib.error.HTTPError("url", 500, "Internal Error", {}, None)

    import urllib.request
    with patch.object(urllib.request, "urlopen", mock_urlopen_error):
        # 不应抛异常
        await notify_human_review(
            question="测试",
            category="test",
            task_id=1,
            webhook_url="https://fake.webhook.url",
        )
