"""批量导入演示知识库文档到企业知识问答系统。

用法：
    python scripts/import_demo_data.py --token <JWT> [--base-url URL] [--data-dir DIR]

参数：
    --token      Bearer JWT（必填），开发环境用 scripts/create_dev_token.py 生成
    --base-url   API 基础 URL，默认 http://127.0.0.1:8000
    --data-dir   演示文档目录，默认 docs/demo_data

示例：
    python scripts/import_demo_data.py --token eyJ...
    python scripts/import_demo_data.py --token eyJ... --base-url http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 多部分表单编码（标准库实现，无需第三方 HTTP 库）
# ---------------------------------------------------------------------------

def _encode_multipart(fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]) -> tuple[bytes, str]:
    """将字段和文件编码为 multipart/form-data 格式。

    参数：
        fields: 普通表单字段 {name: value}
        files:  文件字段 {name: (filename, data, content_type)}

    返回：
        (body_bytes, content_type_header_value)
    """
    boundary = "----FormBoundary" + os.urandom(12).hex()
    parts: list[bytes] = []

    for name, value in fields.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n'
            f"\r\n"
            f"{value}\r\n".encode()
        )

    for name, (filename, data, content_type) in files.items():
        parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n"
            f"\r\n".encode() + data + b"\r\n"
        )

    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    content_type_header = f"multipart/form-data; boundary={boundary}"
    return body, content_type_header


# ---------------------------------------------------------------------------
# 上传单个文件
# ---------------------------------------------------------------------------

def upload_file(file_path: Path, base_url: str, token: str) -> dict:
    """将单个文件 POST 到 /api/documents/upload。

    返回：
        解析后的 JSON 响应字典（成功时包含 id、filename、status 等字段）

    抛出：
        urllib.error.HTTPError：HTTP 错误（4xx/5xx）
        urllib.error.URLError：网络错误
    """
    url = f"{base_url.rstrip('/')}/api/documents/upload"
    file_data = file_path.read_bytes()
    content_type = mimetypes.guess_type(file_path.name)[0] or "text/plain"

    body, ct_header = _encode_multipart(
        fields={},
        files={"file": (file_path.name, file_data, content_type)},
    )

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": ct_header,
            "Accept": "application/json",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="批量导入演示知识库文档",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--token",
        required=True,
        help="Bearer JWT（开发环境用 scripts/create_dev_token.py 生成）",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="API 基础 URL（默认：http://127.0.0.1:8000）",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="演示文档目录（默认：相对项目根目录的 docs/demo_data）",
    )
    return parser.parse_args()


def find_project_root() -> Path:
    """从当前工作目录或脚本所在目录向上查找项目根目录（含 requirements.txt）。"""
    candidates = [Path.cwd(), Path(__file__).resolve().parent.parent]
    for start in candidates:
        for p in [start] + list(start.parents):
            if (p / "requirements.txt").exists():
                return p
    return Path.cwd()


def main() -> int:
    args = parse_args()

    # 确定演示数据目录
    if args.data_dir:
        data_dir = Path(args.data_dir).expanduser().resolve()
    else:
        project_root = find_project_root()
        data_dir = project_root / "docs" / "demo_data"

    if not data_dir.is_dir():
        print(f"[ERROR] 演示数据目录不存在：{data_dir}", file=sys.stderr)
        print("       请先运行脚本生成演示文档，或通过 --data-dir 指定正确路径。",
              file=sys.stderr)
        return 1

    # 收集 Markdown 文件，按文件名排序
    md_files = sorted(data_dir.glob("*.md"))
    if not md_files:
        print(f"[ERROR] 目录 {data_dir} 中没有 .md 文件", file=sys.stderr)
        return 1

    print(f"发现 {len(md_files)} 个演示文档，目标服务：{args.base_url}")
    print("-" * 60)

    success: list[str] = []
    failed: list[tuple[str, str]] = []

    for file_path in md_files:
        print(f"上传：{file_path.name} ... ", end="", flush=True)
        try:
            result = upload_file(file_path, args.base_url, args.token)
            doc_id = result.get("id", "?")
            status = result.get("status", "?")
            # 检查是否为幂等重放（文件已存在）
            is_replay = result.get("_replay") or False
            tag = " [已存在，跳过]" if is_replay else ""
            print(f"OK  (id={doc_id}, status={status}){tag}")
            success.append(file_path.name)
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode(errors="replace")
                err_json = json.loads(body)
                detail = err_json.get("detail", body)
            except Exception:  # noqa: BLE001
                detail = body or str(exc)
            print(f"FAIL  HTTP {exc.code}: {detail}")
            failed.append((file_path.name, f"HTTP {exc.code}: {detail}"))
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            print(f"FAIL  网络错误: {reason}")
            failed.append((file_path.name, f"网络错误: {reason}"))
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL  {exc}")
            failed.append((file_path.name, str(exc)))

        # 小间隔，避免并发冲突（UPLOAD_MAX_CONCURRENCY 默认为 2）
        time.sleep(0.3)

    # 汇总结果
    print("-" * 60)
    print(f"完成：{len(success)} 成功，{len(failed)} 失败（共 {len(md_files)} 个）")

    if failed:
        print("\n失败文件列表：")
        for name, reason in failed:
            print(f"  - {name}: {reason}")
        print("\n常见原因：")
        print("  1. Token 无效或过期 → 重新运行 scripts/create_dev_token.py")
        print("  2. 服务未启动 → 确认 uvicorn 和 worker 都在运行")
        print("  3. 上传速率限制（429）→ 适当增加 time.sleep 间隔")
        return 1

    print("\n所有文档已上传，Worker 将在后台完成索引（通常数秒内完成）。")
    print("可通过以下命令查看文档状态：")
    print(f"  curl -H 'Authorization: Bearer <TOKEN>' {args.base_url}/api/documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
