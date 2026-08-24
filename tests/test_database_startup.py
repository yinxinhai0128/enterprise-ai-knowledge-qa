import pytest
from sqlalchemy import text

from app.core import database


@pytest.mark.asyncio
async def test_runtime_schema_init_refuses_implicit_create_all_in_production(monkeypatch) -> None:
    monkeypatch.setattr(database.settings, "app_env", "production")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        await database.init_schema_for_runtime()


@pytest.mark.asyncio
async def test_runtime_schema_init_accepts_current_alembic_revision(monkeypatch) -> None:
    monkeypatch.setattr(database.settings, "app_env", "production")

    async with database.engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32))"))
        await conn.execute(
            text("INSERT INTO alembic_version (version_num) VALUES (:revision)"),
            {"revision": database.CURRENT_SCHEMA_REVISION},
        )

    try:
        await database.init_schema_for_runtime()
    finally:
        async with database.engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


@pytest.mark.asyncio
async def test_runtime_schema_init_uses_dev_initializer_outside_production(monkeypatch) -> None:
    called = False

    async def fake_init_db() -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(database.settings, "app_env", "development")
    monkeypatch.setattr(database, "init_db", fake_init_db)

    await database.init_schema_for_runtime()

    assert called is True
