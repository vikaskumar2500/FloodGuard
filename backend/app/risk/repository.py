from datetime import datetime
from uuid import UUID

from geoalchemy2 import Geography
from sqlalchemy import and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    FloodPrediction,
    FloodZone,
    Incident,
    RoadEdge,
    SensorEvent,
    WeatherObservation,
)

from .config import RiskConfig
from .models import (
    EdgeEvidence,
    FloodZoneEvidence,
    IncidentEvidence,
    PredictionEvidence,
    SensorEvidence,
    WeatherEvidence,
)
from .scoring import SEVERITY_SCORE


class RiskEvidenceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def load_for_edges(
        self,
        edge_ids: tuple[UUID, ...],
        now: datetime,
        config: RiskConfig,
    ) -> dict[UUID, EdgeEvidence]:
        evidence = {edge_id: EdgeEvidence() for edge_id in edge_ids}
        if not edge_ids:
            return evidence

        chunk_size = 5000
        for i in range(0, len(edge_ids), chunk_size):
            chunk = edge_ids[i : i + chunk_size]
            edge_filter = RoadEdge.id.in_(chunk)

            zone_rows = await self.session.execute(
                select(
                    RoadEdge.id,
                    FloodZone.risk_score,
                    FloodZone.confidence,
                    FloodZone.severity,
                    FloodZone.valid_from,
                )
                .join(FloodZone, func.ST_Intersects(FloodZone.geometry, RoadEdge.geometry))
                .where(
                    edge_filter,
                    FloodZone.valid_from <= now,
                    or_(FloodZone.valid_until.is_(None), FloodZone.valid_until > now),
                )
            )
            for edge_id, score, confidence, severity, valid_from in zone_rows:
                severity_floor = SEVERITY_SCORE.get(severity, 0.0)
                evidence[edge_id].flood_zones.append(
                    FloodZoneEvidence(
                        score=max(float(score), severity_floor),
                        confidence=0.5 if confidence is None else float(confidence),
                        severity=severity,
                        evidence_age=now - valid_from,
                    )
                )

            sensor_point = cast(SensorEvent.location, Geography)
            edge_shape = cast(RoadEdge.geometry, Geography)
            sensor_rows = await self.session.execute(
                select(
                    RoadEdge.id,
                    SensorEvent.water_depth_cm,
                    SensorEvent.rainfall_mm,
                    SensorEvent.observed_at,
                    SensorEvent.quality,
                )
                .join(
                    SensorEvent,
                    and_(
                        func.ST_DWithin(sensor_point, edge_shape, config.sensor_radius_m),
                        SensorEvent.observed_at >= now - config.sensor_validity,
                        SensorEvent.observed_at <= now,
                    ),
                )
                .where(edge_filter, SensorEvent.quality != "INVALID")
            )
            for edge_id, water_depth, rainfall, observed_at, quality in sensor_rows:
                evidence[edge_id].sensors.append(
                    SensorEvidence(water_depth, rainfall, observed_at, quality)
                )

            weather_rows = await self.session.execute(
                select(
                    RoadEdge.id,
                    WeatherObservation.rainfall_mm,
                    WeatherObservation.observed_at,
                    WeatherObservation.observation_interval_minutes,
                )
                .join(
                    WeatherObservation,
                    and_(
                        func.ST_DWithin(
                            cast(WeatherObservation.location, Geography),
                            edge_shape,
                            config.weather_radius_m,
                        ),
                        WeatherObservation.observed_at >= now - config.weather_validity,
                        WeatherObservation.observed_at <= now,
                    ),
                )
                .where(edge_filter)
            )
            for edge_id, rainfall, observed_at, interval in weather_rows:
                evidence[edge_id].weather.append(WeatherEvidence(rainfall, observed_at, interval))

            prediction_rows = await self.session.execute(
                select(
                    RoadEdge.id,
                    FloodPrediction.probability,
                    FloodPrediction.predicted_water_depth_cm,
                    FloodPrediction.predicted_for,
                    FloodPrediction.expires_at,
                )
                .join(
                    FloodPrediction,
                    or_(
                        FloodPrediction.road_edge_id == RoadEdge.id,
                        and_(
                            FloodPrediction.geometry.is_not(None),
                            func.ST_Intersects(FloodPrediction.geometry, RoadEdge.geometry),
                        ),
                    ),
                )
                .where(
                    edge_filter,
                    FloodPrediction.predicted_for <= now,
                    or_(FloodPrediction.expires_at.is_(None), FloodPrediction.expires_at > now),
                )
            )
            for edge_id, probability, depth, predicted_for, expires_at in prediction_rows:
                evidence[edge_id].predictions.append(
                    PredictionEvidence(probability, depth, predicted_for, expires_at)
                )

            incident_rows = await self.session.execute(
                select(
                    RoadEdge.id,
                    Incident.severity,
                    Incident.status,
                    Incident.confidence,
                    Incident.occurred_at,
                )
                .join(
                    Incident,
                    and_(
                        func.ST_DWithin(
                            cast(Incident.location, Geography), edge_shape, config.incident_radius_m
                        ),
                        Incident.occurred_at >= now - config.incident_validity,
                        Incident.occurred_at <= now,
                    ),
                )
                .where(edge_filter, Incident.status.in_(("REPORTED", "VERIFIED")))
            )
            for edge_id, severity, status, confidence, occurred_at in incident_rows:
                evidence[edge_id].incidents.append(
                    IncidentEvidence(severity, status, confidence, occurred_at)
                )

        return evidence
