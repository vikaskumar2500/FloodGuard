from datetime import datetime, timedelta

from app.incidents.models import Incident
from app.incidents.repository import IncidentRepository
from app.incidents.schemas import LocationSchema


class IncidentClustering:
    def __init__(self, repository: IncidentRepository):
        self.repository = repository
        self.radius_meters = 50.0
        self.time_window = timedelta(hours=2)

    async def find_cluster(
        self, location: LocationSchema, occurred_at: datetime
    ) -> Incident | None:
        since = occurred_at - self.time_window
        nearby = await self.repository.find_nearby(location, self.radius_meters, since=since)

        # simple heuristic: return the first matched active incident
        for incident in nearby:
            if incident.status not in ("REJECTED", "RESOLVED", "EXPIRED", "DISPUTED"):
                return incident
        return None
