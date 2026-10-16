from datetime import UTC, datetime

from app.incidents.models import Incident


class TrustScoring:
    @staticmethod
    def calculate_confidence(incident: Incident) -> float:
        score = 0.5  # Base score

        # Source weight (if reporter is present, we could check their trust level)
        if incident.reporter_user_id:
            score += 0.1

        # Freshness (decays over 24h)
        now = datetime.now(UTC)
        occurred = incident.occurred_at
        if occurred.tzinfo is None:
            occurred = occurred.replace(tzinfo=UTC)

        age_hours = (now - occurred).total_seconds() / 3600
        if age_hours < 1:
            score += 0.2
        elif age_hours < 6:
            score += 0.1

        # Corroboration could be checked from attributes
        corroborators = incident.attributes.get("corroborators", [])
        if len(corroborators) > 0:
            score += min(len(corroborators) * 0.1, 0.2)

        sensor_confirmed = incident.attributes.get("sensor_confirmed", False)
        if sensor_confirmed:
            score += 0.3

        return min(max(score, 0.0), 1.0)
