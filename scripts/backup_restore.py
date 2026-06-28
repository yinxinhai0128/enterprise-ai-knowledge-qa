"""SQLite、FAISS 与文档文件的可验证备份/恢复工具。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import shutil
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)
DEFAULT_STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", ROOT / "storage"))
DEFAULT_FAISS_DIR = Path.home() / "faiss_kb"

# v1：Chroma 时代备份；v2 起改为 FAISS。
SCHEMA_VERSION = 2
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


@dataclass(frozen=True, slots=True)
class RestoreConsistencyReport:
    sqlite_integrity_errors: int = 0
    missing_files: int = 0
    missing_vectors: int = 0
    extra_vectors: int = 0
    orphan_vectors: int = 0
    orphan_files: int = 0
    orphan_jobs: int = 0

    @property
    def total_issues(self) -> int:
        return sum(asdict(self).values())

    def to_dict(self) -> dict[str, int]:
        result = asdict(self)
        result["total_issues"] = self.total_issues
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _assert_plain_tree(root: Path) -> None:
    if not root.exists():
        return
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"备份源禁止符号链接：{path.name}")


def _sqlite_snapshot(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)


def _copy_tree_with_sqlite_snapshots(source: Path, destination: Path) -> None:
    if not source.exists():
        destination.mkdir(parents=True, exist_ok=True)
        return
    _assert_plain_tree(source)
    shutil.copytree(source, destination)
    for sqlite_file in source.rglob("*"):
        if sqlite_file.is_file() and sqlite_file.suffix.lower() in SQLITE_SUFFIXES:
            relative = sqlite_file.relative_to(source)
            copied = destination / relative
            copied.unlink(missing_ok=True)
            _sqlite_snapshot(sqlite_file, copied)


def _manifest_entries(data_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(data_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        }
        for path in sorted(item for item in data_root.rglob("*") if item.is_file())
    ]


def create_backup(
    destination: Path,
    *,
    storage_dir: Path,
    faiss_dir: Path,
    maintenance_confirmed: bool,
) -> Path:
    """创建新备份；调用方必须先停止 API/Worker 写入。"""
    if not maintenance_confirmed:
        raise ValueError("必须先停止 API/Worker，并显式确认维护窗口")
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError("备份目标已存在，禁止覆盖")
    data_root = destination / "data"
    destination.mkdir(parents=True)
    try:
        _copy_tree_with_sqlite_snapshots(storage_dir.resolve(), data_root / "storage")
        _copy_tree_with_sqlite_snapshots(faiss_dir.resolve(), data_root / "faiss_kb")
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "files": _manifest_entries(data_root),
        }
        manifest_path = destination / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest_path
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise


def verify_manifest(backup_root: Path) -> dict[str, Any]:
    manifest_path = backup_root.resolve() / "manifest.json"
    data_root = manifest_path.parent / "data"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = manifest.get("schema_version")
    if schema not in (1, SCHEMA_VERSION) or not isinstance(manifest.get("files"), list):
        raise ValueError("备份清单格式无效")
    expected_paths: set[str] = set()
    for entry in manifest["files"]:
        relative = Path(str(entry["path"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("备份清单包含不安全路径")
        path = data_root / relative
        expected_paths.add(relative.as_posix())
        if not path.is_file():
            raise ValueError(f"备份文件缺失：{relative.as_posix()}")
        if path.stat().st_size != int(entry["size"]) or _sha256(path) != entry["sha256"]:
            raise ValueError(f"备份文件校验失败：{relative.as_posix()}")
    actual_paths = {
        path.relative_to(data_root).as_posix()
        for path in data_root.rglob("*")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ValueError("备份数据与清单文件集合不一致")
    return manifest


def restore_backup(backup_root: Path, target_root: Path) -> Path:
    """仅恢复到空目标，永不原地覆盖正式数据。"""
    backup_root = backup_root.resolve()
    manifest = verify_manifest(backup_root)
    target_root = target_root.resolve()
    if target_root.exists() and any(target_root.iterdir()):
        raise FileExistsError("恢复目标非空，禁止覆盖")
    target_root.mkdir(parents=True, exist_ok=True)
    # v1 备份含 chroma_db；v2 起含 faiss_kb。
    vector_dir_name = "faiss_kb" if manifest.get("schema_version", 1) >= 2 else "chroma_db"
    try:
        for name in ("storage", vector_dir_name):
            source = backup_root / "data" / name
            destination = target_root / name
            if source.exists():
                shutil.copytree(source, destination)
        return target_root
    except Exception:
        shutil.rmtree(target_root, ignore_errors=True)
        raise


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _restored_document_path(storage_root: Path, tenant_id: str, stored_path: str) -> Path:
    original = Path(stored_path)
    parts = list(original.parts)
    for marker in ("documents", "quarantine"):
        if marker in parts:
            suffix = parts[parts.index(marker) + 1 :]
            return storage_root / marker / Path(*suffix)
    # 阶段 2 前的 legacy 文件可能直接位于 storage 根目录；仅在文件名唯一时重定位。
    matches = [path for path in storage_root.rglob(original.name) if path.is_file()]
    if len(matches) == 1:
        return matches[0]
    return storage_root / "documents" / tenant_id / original.name


def _sqlite_integrity_errors(root: Path) -> int:
    errors = 0
    for database in root.rglob("*"):
        if not database.is_file() or database.suffix.lower() not in SQLITE_SUFFIXES:
            continue
        try:
            with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
                result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                errors += 1
        except sqlite3.DatabaseError:
            errors += 1
    return errors


def _load_faiss_metadatas(faiss_dir: Path) -> list[dict[str, Any]]:
    """直接读 FAISS pickle，不需要 embeddings，避免 API key 依赖。"""
    pkl_file = faiss_dir / "index.pkl"
    if not pkl_file.is_file():
        return []
    try:
        with pkl_file.open("rb") as f:
            docstore, _ = pickle.load(f)  # (InMemoryDocstore, index_to_docstore_id)
        return [doc.metadata for doc in docstore._dict.values()]
    except Exception:
        return []


def verify_restored_consistency(target_root: Path) -> RestoreConsistencyReport:
    """对恢复副本执行 SQLite、文件和 FAISS 三方只读一致性检查。"""
    target_root = target_root.resolve()
    storage_root = target_root / "storage"
    database = storage_root / "app.db"
    documents: list[tuple[int, str, str, str, int]] = []
    jobs: list[int] = []
    if database.is_file():
        with sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True) as connection:
            if _table_exists(connection, "documents"):
                documents = [
                    (int(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4] or 0))
                    for row in connection.execute(
                        "SELECT id, tenant_id, file_path, status, chunk_count FROM documents"
                    )
                ]
            if _table_exists(connection, "ingest_jobs"):
                jobs = [int(row[0]) for row in connection.execute("SELECT document_id FROM ingest_jobs")]

    document_keys = {(tenant_id, doc_id) for doc_id, tenant_id, _, _, _ in documents}
    referenced_files = {
        _restored_document_path(storage_root, tenant_id, stored_path).resolve()
        for _, tenant_id, stored_path, _, _ in documents
    }
    missing_files = sum(1 for path in referenced_files if not path.is_file())
    stored_files = {
        path.resolve()
        for name in ("documents", "quarantine")
        for path in (storage_root / name).rglob("*")
        if path.is_file()
    }

    faiss_dir = target_root / "faiss_kb"
    metadatas = _load_faiss_metadatas(faiss_dir)

    vector_counts: dict[tuple[str, int], int] = {}
    orphan_vectors = 0
    for metadata in metadatas:
        try:
            key = (str(metadata["tenant_id"]), int(metadata["doc_id"]))
        except (KeyError, TypeError, ValueError):
            orphan_vectors += 1
            continue
        if key not in document_keys:
            orphan_vectors += 1
        else:
            vector_counts[key] = vector_counts.get(key, 0) + 1

    missing_vectors = 0
    extra_vectors = 0
    for doc_id, tenant_id, _, status, chunk_count in documents:
        if status != "indexed":
            continue
        actual = vector_counts.get((tenant_id, doc_id), 0)
        missing_vectors += max(0, chunk_count - actual)
        extra_vectors += max(0, actual - chunk_count)

    document_ids = {doc_id for doc_id, _, _, _, _ in documents}
    return RestoreConsistencyReport(
        sqlite_integrity_errors=_sqlite_integrity_errors(target_root),
        missing_files=missing_files,
        missing_vectors=missing_vectors,
        extra_vectors=extra_vectors,
        orphan_vectors=orphan_vectors,
        orphan_files=len(stored_files - referenced_files),
        orphan_jobs=sum(1 for document_id in jobs if document_id not in document_ids),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--destination", type=Path, required=True)
    backup_parser.add_argument("--storage-dir", type=Path, default=DEFAULT_STORAGE_DIR)
    backup_parser.add_argument("--faiss-dir", type=Path, default=DEFAULT_FAISS_DIR)
    backup_parser.add_argument("--maintenance-confirmed", action="store_true")
    restore_parser = subparsers.add_parser("restore")
    restore_parser.add_argument("--backup", type=Path, required=True)
    restore_parser.add_argument("--target-root", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "backup":
            manifest = create_backup(
                args.destination,
                storage_dir=args.storage_dir,
                faiss_dir=args.faiss_dir,
                maintenance_confirmed=args.maintenance_confirmed,
            )
            print(json.dumps({"status": "ok", "manifest": str(manifest)}, ensure_ascii=False))
        elif args.command == "restore":
            restored = restore_backup(args.backup, args.target_root)
            print(json.dumps({"status": "ok", "root": str(restored)}, ensure_ascii=False))
        else:
            report = verify_restored_consistency(args.root)
            print(json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True))
            return 0 if report.total_issues == 0 else 1
    except (OSError, ValueError, KeyError, sqlite3.DatabaseError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {"status": "error", "error_type": type(exc).__name__},
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
