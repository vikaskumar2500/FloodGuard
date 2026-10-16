import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.exc import SQLAlchemyError

from app.cache.keys import compute_config_hash
from app.cache.models import CachedRouteSegmentDTO, CachedRouteTemplateDTO
from app.core.errors import problem_response
from app.realtime.events import RouteCreatedData
from app.realtime.registry import ActiveRoute
from app.routing.exceptions import (
    GraphUnavailable,
    NoRouteFound,
    RoutingError,
    RoutingExpansionLimitExceeded,
    SnapDistanceExceeded,
)
from app.routing.service import calculate_route
from app.schemas.routes import (
    MLRouteMetadata,
    RouteCalculationRequest,
    RouteCalculationResponse,
)

logger = logging.getLogger("floodguard.routing")
from app.api.dependencies import get_rate_limiter
from app.core.config import get_settings

settings = get_settings()
router = APIRouter(prefix="/routes", tags=["routes"])


@router.post(
    "/calculate",
    response_model=RouteCalculationResponse,
    status_code=201,
    dependencies=[Depends(get_rate_limiter("calculate_route", 100, 60))],
    responses={
        400: {"description": "Routing request rejected"},
        404: {"description": "Route unavailable"},
    },
)
async def calculate(request: Request, response: Response, body: RouteCalculationRequest):
    source = (body.source.longitude, body.source.latitude)
    destination = (body.destination.longitude, body.destination.latitude)

    if request.app.state.settings.use_fixture_routing:
        fixture = request.app.state.runtime.fixture
        route_cache = getattr(request.app.state, "route_cache", None)
        risk_revision = getattr(request.app.state.runtime.runtime_risk_state, "revision", 0)
        pred_svc = getattr(request.app.state, "prediction_service", None)
        settings = request.app.state.settings
        config_hash = compute_config_hash(
            settings.risk_balanced_penalty_seconds,
            settings.risk_safest_penalty_seconds,
            settings.ml_mode,
            settings.ml_risk_weight,
        )
        source_node_id = str(fixture.nodes["A"])
        dest_node_id = str(fixture.nodes["D"])
        graph_version_id = "86f3949b-9ba7-4e3b-aef1-65d940a08754"

        cached_template = None
        if route_cache is not None:
            cached_template = await route_cache.get(
                graph_version_id,
                source_node_id,
                dest_node_id,
                body.mode,
                "ASTAR",
                risk_revision,
                config_hash,
            )

        if cached_template is not None:
            response.headers["X-FloodGuard-Cache"] = "HIT"
            route_id = str(uuid4())
            calc_response = RouteCalculationResponse(
                routeId=route_id,
                graphVersionId=cached_template.graph_version_id,
                algorithm=cached_template.algorithm,
                mode=cached_template.mode,
                distanceMeters=cached_template.distance_m,
                estimatedTimeSeconds=cached_template.estimated_time_s,
                riskScore=cached_template.risk_score,
                riskLevel=cached_template.risk_level,
                riskConfidence=cached_template.risk_confidence,
                maxEdgeRisk=cached_template.max_edge_risk,
                highRiskDistanceMeters=cached_template.high_risk_distance_m,
                expandedNodes=cached_template.expanded_nodes,
                riskModelActive=cached_template.risk_model_active,
                riskSegments=[
                    {
                        "edgeId": segment.edge_id,
                        "riskScore": segment.risk_score,
                        "riskLevel": segment.risk_level,
                        "confidence": segment.confidence,
                        "explanation": segment.explanation,
                        "geometry": {
                            "type": "LineString",
                            "coordinates": list(segment.geometry_coordinates),
                        },
                        "mlProbability": segment.ml_probability,
                        "deterministicRisk": segment.deterministic_risk,
                        "fusedRisk": segment.fused_risk,
                    }
                    for segment in cached_template.risk_segments
                ],
                geometry={
                    "type": cached_template.geometry_type,
                    "coordinates": list(cached_template.geometry_coordinates),
                },
                ml=(
                    MLRouteMetadata(
                        mode=cached_template.ml_mode,  # type: ignore[arg-type]
                        available=cached_template.ml_available,
                        modelVersion=cached_template.ml_model_version or settings.ml_model_version,
                        predictionHorizonMinutes=30,
                        provenanceWarning="SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.",
                    )
                    if cached_template.ml_available or cached_template.ml_mode != "DISABLED"
                    else None
                ),
            )
            request.app.state.active_route_registry.register(
                ActiveRoute(
                    route_id=route_id,
                    user_id=None,
                    graph_version_id=str(calc_response.graph_version_id),
                    mode=body.mode,
                    source=source,
                    destination=destination,
                    edge_ids=list(cached_template.edge_ids),
                    risk_score=cached_template.risk_score,
                    risk_level=cached_template.risk_level,
                    current_eta_s=cached_template.estimated_time_s,
                    risk_confidence=cached_template.risk_confidence,
                    evaluated_risk_revision=risk_revision,
                    metadata={"algorithm": "ASTAR"},
                )
            )
            return calc_response

        ml_metadata = None
        if pred_svc and pred_svc.is_available:
            ml_metadata = MLRouteMetadata(
                mode=settings.ml_mode,
                available=True,
                modelVersion=pred_svc.model_version,
                predictionHorizonMinutes=30,
                provenanceWarning="SYNTHETIC DATASET EVALUATION: Do not claim real-world operational accuracy.",
            )

        response.headers["X-FloodGuard-Cache"] = "MISS"
        result = fixture.initial(body.mode)
        calc_response = RouteCalculationResponse(
            routeId=result.route_id,
            graphVersionId=graph_version_id,
            algorithm="ASTAR",
            mode=body.mode,
            distanceMeters=result.distance_meters,
            estimatedTimeSeconds=result.eta_seconds,
            riskScore=result.risk_score,
            riskLevel=result.risk_level,
            riskConfidence=result.confidence,
            maxEdgeRisk=max((segment["riskScore"] for segment in result.risk_segments), default=0),
            highRiskDistanceMeters=0,
            expandedNodes=6,
            riskModelActive=True,
            riskSegments=result.risk_segments,
            geometry=result.geometry,
            ml=ml_metadata,
        )
        route_id = result.route_id
        request.app.state.active_route_registry.register(
            ActiveRoute(
                route_id=route_id,
                user_id=None,
                graph_version_id=str(calc_response.graph_version_id),
                mode=body.mode,
                source=source,
                destination=destination,
                edge_ids=[str(value) for value in result.edge_ids],
                risk_score=result.risk_score,
                risk_level=result.risk_level,
                current_eta_s=result.eta_seconds,
                risk_confidence=result.confidence,
                evaluated_risk_revision=risk_revision,
                metadata={"algorithm": "ASTAR"},
            )
        )

        if route_cache is not None:
            template = CachedRouteTemplateDTO(
                graph_version_id=graph_version_id,
                algorithm="ASTAR",
                mode=body.mode,
                source_node_id=source_node_id,
                destination_node_id=dest_node_id,
                distance_m=result.distance_meters,
                estimated_time_s=result.eta_seconds,
                risk_score=result.risk_score,
                risk_level=result.risk_level,
                risk_confidence=result.confidence,
                max_edge_risk=calc_response.max_edge_risk,
                high_risk_distance_m=0,
                expanded_nodes=6,
                risk_model_active=True,
                edge_ids=tuple(result.edge_ids),
                node_ids=(source_node_id, dest_node_id),
                risk_segments=tuple(
                    CachedRouteSegmentDTO(
                        edge_id=segment["edgeId"],
                        risk_score=segment["riskScore"],
                        risk_level=segment["riskLevel"],
                        confidence=segment["confidence"],
                        explanation=segment["explanation"],
                        geometry_coordinates=tuple(
                            tuple(coord) for coord in segment["geometry"]["coordinates"]
                        ),
                        ml_probability=segment.get("mlProbability"),
                        deterministic_risk=segment.get("deterministicRisk"),
                        fused_risk=segment.get("fusedRisk"),
                    )
                    for segment in result.risk_segments
                ),
                geometry_type=result.geometry["type"],
                geometry_coordinates=tuple(
                    tuple(coord) for coord in result.geometry["coordinates"]
                ),
                risk_revision=risk_revision,
                ml_mode=settings.ml_mode,
                ml_available=bool(pred_svc and pred_svc.is_available),
                ml_model_version=pred_svc.model_version if pred_svc else "",
            )
            await route_cache.set(
                graph_version_id,
                source_node_id,
                dest_node_id,
                body.mode,
                "ASTAR",
                risk_revision,
                config_hash,
                template,
            )

        return calc_response

    graph_cache = getattr(request.app.state, "graph_cache", None)
    risk_cache = getattr(request.app.state, "risk_cache", None)
    route_cache = getattr(request.app.state, "route_cache", None)
    single_flight = getattr(request.app.state, "single_flight", None)
    risk_revision = getattr(request.app.state.runtime.runtime_risk_state, "revision", 0)
    settings = request.app.state.settings

    try:
        async with request.app.state.database.sessions() as session, session.begin():
            flight_key = (
                f"calc:{source[0]:.5f}:{source[1]:.5f}:{destination[0]:.5f}:{destination[1]:.5f}:"
                f"{body.mode}:{body.algorithm}:{risk_revision}"
            )

            async def _do_calc():
                return await calculate_route(
                    session,
                    source=source,
                    destination=destination,
                    mode=body.mode,
                    algorithm=body.algorithm,
                    settings=settings,
                    graph_cache=graph_cache,
                    risk_cache=risk_cache,
                    route_cache=route_cache,
                    risk_revision=risk_revision,
                    prediction_service=getattr(request.app.state, "prediction_service", None),
                    fusion_service=getattr(request.app.state, "fusion_service", None),
                )

            if single_flight is not None:
                result = await single_flight.execute(flight_key, _do_calc)
            else:
                result = await _do_calc()

    except NoRouteFound as error:
        return problem_response(request, 404, "NO_ROUTE", "Route not found", str(error))
    except (GraphUnavailable, SnapDistanceExceeded) as error:
        return problem_response(request, 422, "ROUTE_UNAVAILABLE", "Route unavailable", str(error))
    except RoutingExpansionLimitExceeded as error:
        return problem_response(
            request, 503, "ROUTE_LIMIT", "Route computation limited", str(error)
        )
    except RoutingError as error:
        return problem_response(request, 422, "ROUTE_REJECTED", "Route rejected", str(error))
    except SQLAlchemyError:
        logger.exception("route_persistence_failed", extra={"request_id": request.state.request_id})
        return problem_response(
            request,
            503,
            "ROUTE_BACKEND_UNAVAILABLE",
            "Routing unavailable",
            "The routing database is currently unavailable.",
        )

    is_cache_hit = getattr(result, "is_cache_hit", False)
    response.headers["X-FloodGuard-Cache"] = "HIT" if is_cache_hit else "MISS"

    calc_response = RouteCalculationResponse(
        routeId=result.route_id,
        graphVersionId=result.graph_version_id,
        algorithm=result.algorithm,
        mode=result.mode,
        distanceMeters=result.distance_m,
        estimatedTimeSeconds=result.estimated_time_s,
        riskScore=result.risk_score,
        riskLevel=result.risk_level,
        riskConfidence=result.risk_confidence,
        maxEdgeRisk=result.max_edge_risk,
        highRiskDistanceMeters=result.high_risk_distance_m,
        expandedNodes=result.expanded_nodes,
        riskModelActive=result.risk_model_active,
        riskSegments=[
            {
                "edgeId": segment.edge_id,
                "riskScore": segment.risk_score,
                "riskLevel": segment.risk_level,
                "confidence": segment.confidence,
                "explanation": segment.explanation,
                "geometry": {
                    "type": "LineString",
                    "coordinates": list(segment.geometry_coordinates),
                },
                "mlProbability": segment.ml_probability,
                "deterministicRisk": segment.deterministic_risk,
                "fusedRisk": segment.fused_risk,
            }
            for segment in result.risk_segments
        ],
        geometry={
            "type": result.geometry_type,
            "coordinates": list(result.geometry_coordinates),
        },
        ml=result.ml,
    )

    registry = request.app.state.active_route_registry
    route_id = str(result.route_id)
    registry.register(
        ActiveRoute(
            route_id=route_id,
            user_id=None,
            graph_version_id=str(result.graph_version_id),
            mode=result.mode,
            source=source,
            destination=destination,
            edge_ids=[str(segment.edge_id) for segment in calc_response.risk_segments],
            risk_score=result.risk_score or 0.0,
            risk_level=result.risk_level,
            current_eta_s=result.estimated_time_s,
            risk_confidence=result.risk_confidence,
            evaluated_risk_revision=risk_revision,
            metadata={"algorithm": result.algorithm},
        )
    )
    try:
        publisher = request.app.state.realtime_publisher
        publisher.publish(
            route_id,
            "route.created",
            RouteCreatedData(
                riskScore=result.risk_score,
                riskLevel=result.risk_level,
                riskConfidence=result.risk_confidence,
            ),
            risk_revision=risk_revision,
        )
    except Exception:
        logger.warning("route_stream_publish_failed", extra={"route_id": route_id})
    return calc_response
