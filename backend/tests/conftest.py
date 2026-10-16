import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.health import DependencyHealth


def pytest_collection_modifyitems(items):
    if os.getenv("RUN_INTEGRATION_TESTS") != "1":
        skip = pytest.mark.skip(
            reason="Set RUN_INTEGRATION_TESTS=1 with real PostGIS; Phase 1 also needs Redis"
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip)


@pytest.fixture
def clean_unit_environment(monkeypatch):
    # Unit settings must not depend on the developer shell or checked-out .env.
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.delenv("APP_DEBUG", raising=False)


@pytest.fixture(autouse=True)
def isolated_unit_environment(request):
    if "integration" not in request.keywords:
        request.getfixturevalue("clean_unit_environment")


@pytest.fixture
def settings():
    return Settings(_env_file=None, app_env="test")


@pytest.fixture
def client(monkeypatch, settings):
    async def healthy_database(*args):
        return {
            "postgres": DependencyHealth(status="healthy", message="Database reachable"),
            "postgis": DependencyHealth(status="healthy", message="PostGIS extension available"),
        }

    async def healthy_redis(*args):
        return DependencyHealth(status="healthy", message="Redis reachable")

    monkeypatch.setattr("app.services.health.check_database", healthy_database)
    monkeypatch.setattr("app.services.health.check_redis", healthy_redis)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
