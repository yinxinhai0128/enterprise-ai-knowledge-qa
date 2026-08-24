import pytest

from app.config import Settings


def _production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "dashscope_api_key": "prod-dashscope-key",
        "auth_jwt_secret": "x" * 48,
        "database_url": "postgresql+asyncpg://ekqa:strong-password@db:5432/ekqa",
        "redis_url": "redis://redis:6379/0",
        "malware_scan_required": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_settings_accept_safe_values() -> None:
    _production_settings().validate_production_ready()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"database_url": "sqlite+aiosqlite:///storage/app.db"}, "PostgreSQL"),
        ({"database_url": "postgresql+asyncpg://ekqa:ekqa_dev_password@db:5432/ekqa"}, "development password"),
        ({"dashscope_api_key": "your_dashscope_api_key_here"}, "DASHSCOPE_API_KEY"),
        ({"auth_jwt_secret": "short"}, "AUTH_JWT_SECRET"),
        ({"redis_url": "redis://127.0.0.1:6379/0"}, "localhost"),
        ({"malware_scan_required": False}, "MALWARE_SCAN_REQUIRED"),
    ],
)
def test_production_settings_reject_unsafe_values(overrides, message: str) -> None:
    with pytest.raises(RuntimeError, match=message):
        _production_settings(**overrides).validate_production_ready()
