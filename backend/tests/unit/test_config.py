import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_environment_settings(monkeypatch):
    for key, value in {
        "APP_NAME": "test-api",
        "APP_ENV": "test",
        "APP_VERSION": "0.2.0",
        "DEBUG": "true",
        "LOG_LEVEL": "DEBUG",
        "API_V1_PREFIX": "/api/test",
        "FRONTEND_URL": "http://localhost:3100/",
        "DATABASE_URL": "postgresql+asyncpg://test:secret@localhost:5432/test",
        "REDIS_URL": "redis://localhost:6380/0",
        "REDIS_REQUIRED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    settings = Settings(_env_file=None)
    assert settings.app_name == "test-api"
    assert settings.app_version == "0.2.0"
    assert settings.debug is True
    assert settings.frontend_url == "http://localhost:3100"
    assert settings.redis_required is False
    assert "test:secret" not in repr(settings)


def test_dotenv_loading(tmp_path):
    env = tmp_path / ".env"
    env.write_text("APP_NAME=dotenv-api\nUNKNOWN_FUTURE_SETTING=ignored\n")
    assert Settings(_env_file=env).app_name == "dotenv-api"


def test_namespaced_dotenv_debug_wins_over_unrelated_host_debug(tmp_path, monkeypatch):
    monkeypatch.setenv("DEBUG", "release")
    env = tmp_path / ".env"
    env.write_text("APP_DEBUG=false\n")
    assert Settings(_env_file=env).debug is False


@pytest.mark.parametrize(
    "values",
    [
        {"database_url": "sqlite:///local.db"},
        {"redis_url": "https://localhost"},
        {"frontend_url": "*"},
        {"frontend_url": "http://localhost:3000/path"},
        {"api_v1_prefix": "api/v1"},
        {"api_v1_prefix": "/api/v1/"},
        {"health_check_timeout_seconds": 0},
    ],
)
def test_invalid_settings_rejected(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
