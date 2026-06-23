"""使用专用测试身份和合成文档执行真实 HTTP 端到端验收。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx


class AcceptanceHttpError(RuntimeError):
    """只携带步骤与状态码，避免把远端响应或凭据写入验收输出。"""

    def __init__(self, stage: str, status_code: int, error_code: str) -> None:
        super().__init__(f"{stage} returned HTTP {status_code}")
        self.stage = stage
        self.status_code = status_code
        self.error_code = error_code


def _require_success(response: httpx.Response, stage: str) -> None:
    if response.is_error:
        try:
            value = response.json().get("error_code", "HTTP_ERROR")
        except (json.JSONDecodeError, AttributeError, TypeError):
            value = "HTTP_ERROR"
        error_code = str(value)
        if not error_code.replace("_", "").isalnum() or len(error_code) > 64:
            error_code = "HTTP_ERROR"
        raise AcceptanceHttpError(stage, response.status_code, error_code)


def _loopback_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("acceptance base URL must be loopback HTTP")
    return value.rstrip("/")


async def run(base_url: str, sample: Path, token: str) -> dict[str, object]:
    if not sample.is_file() or sample.suffix.lower() != ".txt":
        raise ValueError("acceptance sample must be an existing TXT file")
    headers = {"Authorization": f"Bearer {token}"}
    document_id: int | None = None
    deleted = False
    async with httpx.AsyncClient(
        base_url=_loopback_url(base_url),
        timeout=90.0,
        trust_env=False,
    ) as client:
        try:
            with sample.open("rb") as stream:
                upload = await client.post(
                    "/documents/upload",
                    headers=headers,
                    files={"file": (sample.name, stream, "text/plain")},
                )
            _require_success(upload, "upload")
            document_id = int(upload.json()["id"])

            status = ""
            for _ in range(120):
                detail = await client.get(f"/documents/{document_id}", headers=headers)
                _require_success(detail, "document-status")
                payload = detail.json()
                status = str(payload["status"])
                if status in {"indexed", "failed"}:
                    break
                await asyncio.sleep(1)
            if status != "indexed":
                raise RuntimeError("document did not reach indexed state")

            question = "合成测试制度要求提前几个工作日提交申请？"
            ask = await client.post(
                "/qa/ask",
                headers=headers,
                json={"question": question, "session_id": "stage12-e2e"},
            )
            _require_success(ask, "qa")
            answer = ask.json()
            sources = answer.get("sources", [])
            if answer.get("refused") is not False or not sources:
                raise RuntimeError("real QA returned no trusted source")
            if not any(
                int(source.get("doc_id", -1)) == document_id
                and source.get("source") == sample.name
                for source in sources
            ):
                raise RuntimeError("real QA source does not match uploaded sample")

            history = await client.get("/qa/history/stage12-e2e", headers=headers)
            _require_success(history, "history")
            if not any(message.get("content") == question for message in history.json()["messages"]):
                raise RuntimeError("real QA history did not persist the question")

            removal = await client.delete(f"/documents/{document_id}", headers=headers)
            if removal.status_code != 204:
                raise RuntimeError("document cleanup failed")
            deleted = True
            missing = await client.get(f"/documents/{document_id}", headers=headers)
            if missing.status_code != 404:
                raise RuntimeError("deleted document remains accessible")
            return {
                "status": "passed",
                "upload": "indexed",
                "trusted_sources": len(sources),
                "history": "persisted",
                "delete": "verified",
            }
        finally:
            if document_id is not None and not deleted:
                try:
                    await client.delete(f"/documents/{document_id}", headers=headers)
                except httpx.HTTPError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--sample", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("ACCEPTANCE_TOKEN", "")
    if not token:
        print('{"status":"error","error_type":"MissingAcceptanceToken"}', file=sys.stderr)
        return 2
    try:
        result = asyncio.run(run(args.base_url, args.sample, token))
    except AcceptanceHttpError as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error_type": type(exc).__name__,
                    "stage": exc.stage,
                    "status_code": exc.status_code,
                    "error_code": exc.error_code,
                }
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps({"status": "error", "error_type": type(exc).__name__}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
