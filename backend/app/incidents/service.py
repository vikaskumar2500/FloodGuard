from datetime import UTC, datetime
from uuid import UUID, uuid4

from geoalchemy2.shape import to_shape

from app.incidents.clustering import IncidentClustering
from app.incidents.models import Incident
from app.incidents.repository import IncidentRepository
from app.incidents.schemas import IncidentCreate, IncidentStatus
from app.incidents.trust import TrustScoring
from app.messaging.models import DomainEvent
from app.messaging.publisher import EventPublisher
from app.realtime.coordinator import RuntimeRiskState


class IncidentService:
    def __init__(
        self,
        repository: IncidentRepository,
        clustering: IncidentClustering,
        publisher: EventPublisher,
        risk_state: RuntimeRiskState,
    ):
        self.repository = repository
        self.clustering = clustering
        self.publisher = publisher
        self.risk_state = risk_state

    async def report_incident(self, data: IncidentCreate) -> Incident:
        # Check for cluster
        cluster = await self.clustering.find_cluster(data.location, data.occurred_at)

        if cluster:
            # Add to corroboration instead of a new one
            corroborators = cluster.attributes.get("corroborators", [])
            if (
                str(data.reporter_user_id) not in corroborators
                and data.reporter_user_id is not None
            ):
                corroborators.append(str(data.reporter_user_id))
                cluster.attributes["corroborators"] = corroborators

                # Recalculate confidence
                cluster.confidence = TrustScoring.calculate_confidence(cluster)
                await self.repository.update(cluster)
            incident = cluster
        else:
            incident = await self.repository.create(data)
            incident.confidence = TrustScoring.calculate_confidence(incident)
            await self.repository.update(incident)

        await self._publish_event("incident.reported", incident)
        return incident

    async def verify_incident(self, incident_id: UUID) -> Incident | None:
        incident = await self.repository.get_by_id(incident_id)
        if not incident:
            return None

        incident.status = IncidentStatus.VERIFIED.value
        incident.verified_at = datetime.now(UTC)
        incident.confidence = 1.0  # High confidence if verified manually

        await self.repository.update(incident)
        await self._publish_event("incident.verified", incident)

        if incident.severity in ("HIGH", "SEVERE"):
            self._update_risk(incident, 1.0)

        return incident

    async def reject_incident(self, incident_id: UUID) -> Incident | None:
        incident = await self.repository.get_by_id(incident_id)
        if not incident:
            return None

        incident.status = IncidentStatus.REJECTED.value
        await self.repository.update(incident)
        await self._publish_event("incident.rejected", incident)
        return incident

    async def resolve_incident(self, incident_id: UUID) -> Incident | None:
        incident = await self.repository.get_by_id(incident_id)
        if not incident:
            return None

        incident.status = IncidentStatus.RESOLVED.value
        await self.repository.update(incident)
        await self._publish_event("incident.resolved", incident)

        # Clear risk
        self._update_risk(incident, 0.0)

        return incident

    def _update_risk(self, incident: Incident, evidence_val: float) -> None:
        # Assuming incident has an associated edge_id in attributes if mapped
        # Or we must find it. If no edge_id, we can't update risk_state.
        edge_id = incident.attributes.get("edge_id")
        if edge_id:
            self.risk_state.update_evidence(
                edge_id=edge_id,
                new_evidence=evidence_val,
                risk_level=incident.severity,
                confidence=incident.confidence or 0.0,
            )
            self.risk_state.commit_evidence()

    async def _publish_event(self, event_type: str, incident: Incident) -> None:
        shape = to_shape(incident.location) if hasattr(incident.location, "data") else None

        payload = {
            "incident_id": str(incident.id),
            "type": incident.incident_type,
            "status": incident.status,
            "severity": incident.severity,
            "confidence": incident.confidence,
            "location": {
                "latitude": shape.y if shape else 0.0,
                "longitude": shape.x if shape else 0.0,
            },
        }
        # A simple domain event
        event = DomainEvent(
            event_id=str(uuid4()),
            producer="incident.service",
            event_type=event_type,
            correlation_id=str(uuid4()),
            occurred_at=datetime.now(UTC),
            payload=payload,
        )
        await self.publisher.publish(event)
