from collections import defaultdict
from datetime import datetime
from typing import Literal
from uuid import UUID

from .models import EventType, SensorStatus, SimulationEvent


def _edge_ids(event: SimulationEvent, aliases: dict[str, UUID]) -> tuple[UUID, ...]:
    values = event.payload.get("target_edge_ids", ())
    return (
        tuple(aliases[value] for value in values if value in aliases)
        if aliases
        else tuple(UUID(value) for value in values)
    )


def events_to_evidence(
    events: tuple[SimulationEvent, ...],
    edge_aliases: dict[str, UUID],
    evaluated_at: datetime,
):
    from app.risk.models import (
        EdgeEvidence,
        FloodZoneEvidence,
        IncidentEvidence,
        SensorEvidence,
        WeatherEvidence,
    )

    evidence = defaultdict(EdgeEvidence)
    sensor_status: dict[str, SensorStatus] = {}
    active_zones: dict[UUID, FloodZoneEvidence] = {}
    active_incidents: dict[UUID, IncidentEvidence] = {}
    for event in events:
        if event.occurred_at > evaluated_at:
            continue
        edge_ids = _edge_ids(event, edge_aliases)
        payload = event.payload
        if event.event_type == EventType.SENSOR_HEALTH_CHANGED:
            sensor_status[payload["sensor_id"]] = SensorStatus(payload["status"])
            if sensor_status[payload["sensor_id"]] == SensorStatus.OFFLINE:
                for edge_id in edge_ids:
                    evidence[edge_id].sensors.clear()
            continue
        if event.event_type in {EventType.RAINFALL_OBSERVATION, EventType.WATER_DEPTH_READING}:
            if (
                sensor_status.get(payload.get("sensor_id"), SensorStatus.ONLINE)
                == SensorStatus.OFFLINE
            ):
                continue
            for edge_id in edge_ids:
                evidence[edge_id].sensors.append(
                    SensorEvidence(
                        payload.get("water_depth_cm"),
                        payload.get("rainfall_mm_per_hour"),
                        event.occurred_at,
                        payload.get("quality", "SIMULATED"),
                    )
                )
        elif event.event_type == EventType.WEATHER_OBSERVATION:
            for edge_id in edge_ids:
                evidence[edge_id].weather.append(
                    WeatherEvidence(
                        payload.get("rainfall_mm"),
                        event.occurred_at,
                        payload.get("observation_interval_minutes"),
                    )
                )
        elif event.event_type in {
            EventType.FLOOD_ZONE_ACTIVATED,
            EventType.FLOOD_ZONE_UPDATED,
        }:
            zone = FloodZoneEvidence(
                float(payload["risk_score"]),
                float(payload.get("confidence", 0.5)),
                str(payload["severity"]),
                evaluated_at - event.occurred_at,
            )
            for edge_id in edge_ids:
                active_zones[edge_id] = zone
        elif event.event_type == EventType.FLOOD_ZONE_CLEARED:
            for edge_id in edge_ids:
                active_zones.pop(edge_id, None)
        elif event.event_type == EventType.INCIDENT_REPORTED:
            incident = IncidentEvidence(
                str(payload["severity"]),
                "REPORTED",
                payload.get("confidence"),
                event.occurred_at,
            )
            for edge_id in edge_ids:
                active_incidents[edge_id] = incident
        elif event.event_type == EventType.INCIDENT_RESOLVED:
            for edge_id in edge_ids:
                active_incidents.pop(edge_id, None)
    for edge_id, zone in active_zones.items():
        evidence[edge_id].flood_zones.append(zone)
    for edge_id, incident in active_incidents.items():
        evidence[edge_id].incidents.append(incident)
    return dict(evidence)


def route_with_simulated_risk(
    graph,
    source_node_id: UUID,
    destination_node_id: UUID,
    events: tuple[SimulationEvent, ...],
    edge_aliases: dict[str, UUID],
    evaluated_at: datetime,
    mode: Literal["FASTEST", "BALANCED", "SAFEST"],
    algorithm: Literal["DIJKSTRA", "ASTAR"],
):
    from app.risk.config import RiskConfig
    from app.risk.costs import build_edge_costs
    from app.risk.service import evaluate_graph, summarize_route
    from app.routing import astar, dijkstra

    config = RiskConfig()
    evidence = events_to_evidence(events, edge_aliases, evaluated_at)
    snapshot = evaluate_graph(graph, evidence, evaluated_at, config)
    costs = build_edge_costs(graph, snapshot.assessments, mode, config)
    search = astar.find_path if algorithm == "ASTAR" else dijkstra.find_path
    path = search(graph, source_node_id, destination_node_id, costs=costs)
    return path, summarize_route(graph, path, snapshot, config), snapshot
