"""Import all models so Alembic sees the complete metadata."""

from app.incidents.models import Incident
from app.models.environment import FloodPrediction, FloodZone, SensorEvent, WeatherObservation
from app.models.road import GraphVersion, Region, RoadEdge, RoadNode
from app.models.route import Route, RouteSegment
from app.models.user import User

__all__ = [
    "FloodPrediction",
    "FloodZone",
    "GraphVersion",
    "Incident",
    "Region",
    "RoadEdge",
    "RoadNode",
    "Route",
    "RouteSegment",
    "SensorEvent",
    "User",
    "WeatherObservation",
]
