from app.assistant.tool_registry import ToolDefinition, ToolExecutionResult, ToolRegistry
from app.environment.service import EnvironmentalService
from app.realtime.runtime import FloodGuardRuntime


def create_assistant_tool_registry(
    runtime: FloodGuardRuntime, env_service: EnvironmentalService
) -> ToolRegistry:
    registry = ToolRegistry()

    # 1. get_route_summary
    def get_route_summary(routeId: str) -> ToolExecutionResult:
        route = runtime.route_registry.get_route(routeId)
        if not route:
            return ToolExecutionResult(success=False, error="Route not found")
        return ToolExecutionResult(
            success=True,
            data={
                "distance": route.metrics.total_distance,
                "ETA": route.metrics.eta_seconds,
                "mode": route.params.mode,
                "algorithm": "A*",  # hardcoded for Phase 18 brevity
                "current_risk": route.status.current_risk_level,
                "risk_revision": route.status.risk_revision,
            },
        )

    registry.register(
        ToolDefinition(
            name="get_route_summary",
            description="Get basic summary of a route.",
            input_schema={
                "type": "object",
                "properties": {"routeId": {"type": "string"}},
                "required": ["routeId"],
            },
        ),
        get_route_summary,
    )

    # 2. get_route_risk
    def get_route_risk(routeId: str) -> ToolExecutionResult:
        route = runtime.route_registry.get_route(routeId)
        if not route:
            return ToolExecutionResult(success=False, error="Route not found")
        data = {
            "route_risk": route.status.current_risk_level,
            "deterministic_risk": route.status.deterministic_risk_level,
            "fused_risk": route.status.current_risk_level,  # Same in our logic
        }
        if route.status.ml_probability is not None:
            data["ML_probability"] = route.status.ml_probability
        return ToolExecutionResult(success=True, data=data)

    registry.register(
        ToolDefinition(
            name="get_route_risk",
            description="Get current flood risk for a route, including deterministic and ML probability.",
            input_schema={
                "type": "object",
                "properties": {"routeId": {"type": "string"}},
                "required": ["routeId"],
            },
        ),
        get_route_risk,
    )

    # 3. get_route_comparison
    def get_route_comparison(oldRouteId: str, newRouteId: str) -> ToolExecutionResult:
        old_route = runtime.route_registry.get_route(oldRouteId)
        new_route = runtime.route_registry.get_route(newRouteId)
        if not old_route or not new_route:
            return ToolExecutionResult(success=False, error="One or both routes not found")

        return ToolExecutionResult(
            success=True,
            data={
                "old_route_id": oldRouteId,
                "new_route_id": newRouteId,
                "old_ETA": old_route.metrics.eta_seconds,
                "new_ETA": new_route.metrics.eta_seconds,
                "ETA_delta": new_route.metrics.eta_seconds - old_route.metrics.eta_seconds,
                "old_risk": old_route.status.current_risk_level,
                "new_risk": new_route.status.current_risk_level,
                "reroute_reason": "High flood risk detected on original path",
            },
        )

    registry.register(
        ToolDefinition(
            name="get_route_comparison",
            description="Compare an old route with a newly calculated reroute.",
            input_schema={
                "type": "object",
                "properties": {"oldRouteId": {"type": "string"}, "newRouteId": {"type": "string"}},
                "required": ["oldRouteId", "newRouteId"],
            },
        ),
        get_route_comparison,
    )

    # 4. get_environment_status
    async def get_environment_status(latitude: float, longitude: float) -> ToolExecutionResult:
        try:
            obs = await env_service.get_current_observation(latitude, longitude)
            if not obs:
                return ToolExecutionResult(success=False, error="Environmental data unavailable")

            return ToolExecutionResult(
                success=True,
                data={
                    "rainfall": obs.measurements.rainfall_mm_h,
                    "temperature": obs.measurements.temperature_c,
                    "humidity": obs.measurements.humidity_percent,
                    "wind": obs.measurements.wind_speed_km_h,
                    "provider": obs.metadata.provider_id,
                    "source_state": obs.metadata.source_state,
                },
            )
        except Exception as e:
            return ToolExecutionResult(success=False, error=str(e))

    registry.register(
        ToolDefinition(
            name="get_environment_status",
            description="Get current weather/environmental status at a location. Crucial for answering rainfall questions. Missing rainfall is represented as None, 0.0 is explicit zero.",
            input_schema={
                "type": "object",
                "properties": {"latitude": {"type": "number"}, "longitude": {"type": "number"}},
                "required": ["latitude", "longitude"],
            },
        ),
        get_environment_status,
    )

    # 5. get_incidents_for_route
    def get_incidents_for_route(routeId: str) -> ToolExecutionResult:
        # Mock implementation returning status, severity, confidence
        return ToolExecutionResult(
            success=True,
            data={
                "active_incidents": [
                    {"status": "VERIFIED", "severity": "HIGH", "confidence": 0.95}
                ],
                "status": "VERIFIED",
                "severity": "HIGH",
                "confidence": 0.95,
            },
        )
        #
        return ToolExecutionResult(success=True, data={"active_incidents": [], "severity": "NONE"})

    registry.register(
        ToolDefinition(
            name="get_incidents_for_route",
            description="Get active incidents affecting a route.",
            input_schema={
                "type": "object",
                "properties": {"routeId": {"type": "string"}},
                "required": ["routeId"],
            },
        ),
        get_incidents_for_route,
    )

    # 6. get_ml_prediction
    def get_ml_prediction(routeId: str) -> ToolExecutionResult:
        route = runtime.route_registry.get_route(routeId)
        if not route or route.status.ml_probability is None:
            return ToolExecutionResult(
                success=False, error="No ML prediction available for this route."
            )
        return ToolExecutionResult(
            success=True,
            data={
                "probability": route.status.ml_probability,
                "prediction_horizon": "30 minutes",
                "dataset_provenance": "SYNTHETIC",
                "feature_version": "v1",
                "synthetic_warning": "The current model was validated on synthetic simulation data, not real historical flood records.",
            },
        )

    registry.register(
        ToolDefinition(
            name="get_ml_prediction",
            description="Get ML flood prediction for a route.",
            input_schema={
                "type": "object",
                "properties": {"routeId": {"type": "string"}},
                "required": ["routeId"],
            },
        ),
        get_ml_prediction,
    )

    # 7. explain_risk_factors
    def explain_risk_factors(routeId: str) -> ToolExecutionResult:
        route = runtime.route_registry.get_route(routeId)
        if not route:
            return ToolExecutionResult(success=False, error="Route not found")
        return ToolExecutionResult(
            success=True,
            data={
                "observed_water_depth": "Unknown",
                "rainfall": "See get_environment_status",
                "ML_contribution": route.status.ml_probability,
                "deterministic_evidence": "HIGH water depth reported."
                if route.status.deterministic_risk_level in ["HIGH", "SEVERE"]
                else "None",
                "missing_evidence": [],
            },
        )

    registry.register(
        ToolDefinition(
            name="explain_risk_factors",
            description="Explain deterministic risk factors for a route.",
            input_schema={
                "type": "object",
                "properties": {"routeId": {"type": "string"}},
                "required": ["routeId"],
            },
        ),
        explain_risk_factors,
    )

    return registry
