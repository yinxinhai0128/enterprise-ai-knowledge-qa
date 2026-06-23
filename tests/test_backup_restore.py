"""阶段 10：备份不可覆盖、清单可验证、恢复副本三存储一致。"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import chromadb
import pytest

from scripts.backup_restore import (
    create_backup,
    restore_backup,
    verify_manifest,
    verify_restored_consistency,
)


def _build_source(root: Path) -> tuple[Path, Path]:
    storage = root / "storage"
    chroma = root / "chroma_db"
    document = storage / "documents" / "tenant-a" / "example.txt"
    document.parent.mkdir(parents=True)
    document.write_text("恢复演练文档", encoding="utf-8")
    database = storage / "app.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                chunk_count INTEGER NOT NULL
            );
            CREATE TABLE ingest_jobs (document_id INTEGER NOT NULL);
            INSERT INTO documents VALUES (
                1, 'tenant-a', 'storage/documents/tenant-a/example.txt', 'indexed', 1
            );
            INSERT INTO ingest_jobs VALUES (1);
            """
        )
    with sqlite3.connect(storage / "checkpoints.db") as connection:
        connection.execute("CREATE TABLE checkpoints (id TEXT PRIMARY KEY)")

    client = chromadb.PersistentClient(path=str(chroma))
    try:
        collection = client.create_collection("enterprise_kb")
        collection.add(
            ids=["tenant-a:1:0:test"],
            documents=["恢复演练文档"],
            embeddings=[[0.1, 0.2, 0.3]],
            metadatas=[{"tenant_id": "tenant-a", "doc_id": 1}],
        )
    finally:
        client.close()
    return storage, chroma


def test_backup_restore_drill_is_consistent(tmp_path):
    storage, chroma = _build_source(tmp_path / "source")
    backup = tmp_path / "backup"
    manifest = create_backup(
        backup,
        storage_dir=storage,
        chroma_dir=chroma,
        maintenance_confirmed=True,
    )
    assert manifest.is_file()
    assert verify_manifest(backup)["schema_version"] == 1

    restored = restore_backup(backup, tmp_path / "restored")
    report = verify_restored_consistency(restored)
    assert report.to_dict() == {
        "sqlite_integrity_errors": 0,
        "missing_files": 0,
        "missing_vectors": 0,
        "extra_vectors": 0,
        "orphan_vectors": 0,
        "orphan_files": 0,
        "orphan_jobs": 0,
        "total_issues": 0,
    }


def test_backup_requires_maintenance_and_never_overwrites(tmp_path):
    storage, chroma = _build_source(tmp_path / "source")
    with pytest.raises(ValueError, match="维护窗口"):
        create_backup(
            tmp_path / "backup",
            storage_dir=storage,
            chroma_dir=chroma,
            maintenance_confirmed=False,
        )

    backup = tmp_path / "backup-ok"
    create_backup(
        backup,
        storage_dir=storage,
        chroma_dir=chroma,
        maintenance_confirmed=True,
    )
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("do not overwrite", encoding="utf-8")
    with pytest.raises(FileExistsError, match="非空"):
        restore_backup(backup, nonempty)
    assert (nonempty / "keep.txt").read_text(encoding="utf-8") == "do not overwrite"


def test_manifest_detects_tampering(tmp_path):
    storage, chroma = _build_source(tmp_path / "source")
    backup = tmp_path / "backup"
    create_backup(
        backup,
        storage_dir=storage,
        chroma_dir=chroma,
        maintenance_confirmed=True,
    )
    (backup / "data" / "storage" / "documents" / "tenant-a" / "example.txt").write_text(
        "tampered", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="校验失败"):
        verify_manifest(backup)
