from uuid import UUID

from app.routing.service import RouteCalculation


def test_route_calculation_validates_coordinates_before_service(client):
    response = client.post(
        "/api/v1/routes/calculate",
        json={
            "source": {"latitude": 91, "longitude": 72},
            "destination": {"latitude": 19, "longitude": 73},
            "mode": "FASTEST",
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_route_calculation_returns_typed_backend_shape(client, monkeypatch):
    async def fake_calculate(*args, **kwargs):
        return RouteCalculation(
            route_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            graph_version_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            algorithm="ASTAR",
            mode="FASTEST",
            distance_m=120.5,
            estimated_time_s=14.25,
            risk_score=0.2,
            risk_level="LOW",
            risk_confidence=0.75,
            max_edge_risk=0.3,
            high_risk_distance_m=0,
            risk_segments=(),
            risk_model_active=True,
            expanded_nodes=7,
            geometry_type="LineString",
            geometry_coordinates=((72.0, 19.0), (72.001, 19.001)),
        )

    monkeypatch.setattr("app.api.v1.routes.calculate_route", fake_calculate)
    response = client.post(
        "/api/v1/routes/calculate",
        json={
            "source": {"latitude": 19, "longitude": 72},
            "destination": {"latitude": 19.001, "longitude": 72.001},
            "mode": "FASTEST",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "routeId": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "graphVersionId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "algorithm": "ASTAR",
        "mode": "FASTEST",
        "distanceMeters": 120.5,
        "estimatedTimeSeconds": 14.25,
        "riskScore": 0.2,
        "riskLevel": "LOW",
        "riskConfidence": 0.75,
        "maxEdgeRisk": 0.3,
        "highRiskDistanceMeters": 0,
        "expandedNodes": 7,
        "riskModelActive": True,
        "riskSegments": [],
        "geometry": {
            "type": "LineString",
            "coordinates": [[72.0, 19.0], [72.001, 19.001]],
        },
        "ml": None,
    }
