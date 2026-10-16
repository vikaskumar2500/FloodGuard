from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.incidents.models import Incident
from app.incidents.schemas import IncidentCreate, IncidentSeverity, IncidentType, LocationSchema
from app.incidents.service import IncidentService


@pytest.fixture
def mock_repository():
    return AsyncMock()


@pytest.fixture
def mock_clustering():
    return AsyncMock()


@pytest.fixture
def mock_publisher():
    return AsyncMock()


@pytest.fixture
def mock_risk_state():
    return MagicMock()


@pytest.fixture
def service(mock_repository, mock_clustering, mock_publisher, mock_risk_state):
    return IncidentService(mock_repository, mock_clustering, mock_publisher, mock_risk_state)


@pytest.mark.asyncio
async def test_report_incident_new(service, mock_clustering, mock_repository, mock_publisher):
    mock_clustering.find_cluster.return_value = None
    mock_loc = MagicMock()
    del mock_loc.data
    mock_repository.create.return_value = Incident(
        id="test-id",
        incident_type="WATERLOGGING",
        location=mock_loc,
        occurred_at=datetime.now(UTC),
        attributes={},
    )
    mock_repository.update.return_value = None

    data = IncidentCreate(
        incident_type=IncidentType.WATERLOGGING,
        location=LocationSchema(latitude=12.0, longitude=13.0),
        description="test",
        severity=IncidentSeverity.HIGH,
        occurred_at=datetime.now(UTC),
    )

    incident = await service.report_incident(data)
    assert incident.id == "test-id"
    mock_repository.create.assert_called_once()
    mock_publisher.publish.assert_called_once()


@pytest.mark.asyncio
async def test_report_incident_cluster(service, mock_clustering, mock_repository, mock_publisher):
    mock_loc = MagicMock()
    del mock_loc.data
    existing = Incident(
        id="existing-id",
        incident_type="WATERLOGGING",
        location=mock_loc,
        occurred_at=datetime.now(UTC),
        attributes={},
    )
    mock_clustering.find_cluster.return_value = existing

    data = IncidentCreate(
        incident_type=IncidentType.WATERLOGGING,
        location=LocationSchema(latitude=12.0, longitude=13.0),
        description="test",
        severity=IncidentSeverity.HIGH,
        occurred_at=datetime.now(UTC),
        reporter_user_id="00000000-0000-0000-0000-000000000001",
    )

    incident = await service.report_incident(data)
    assert incident.id == "existing-id"
    assert "00000000-0000-0000-0000-000000000001" in incident.attributes["corroborators"]
    mock_repository.create.assert_not_called()
    mock_repository.update.assert_called_once()
    mock_publisher.publish.assert_called_once()
