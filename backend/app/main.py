import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from floodguard_ml.models.artifacts import LoadedFloodModel
from starlette.exceptions import HTTPException

from app.api.v1.assistant.routes import router as assistant_router
from app.api.v1.environment import router as environment_router
from app.api.v1.health import live_health
from app.api.v1.health import router as health_router
from app.api.v1.incidents import router as incidents_router
from app.api.v1.realtime import router as realtime_router
from app.api.v1.routes import router as routes_router
from app.api.v1.simulation import router as simulation_router
from app.cache import (
    CacheMetrics,
    GraphCache,
    RiskSnapshotCache,
    RouteCache,
    SingleFlight,
)
from app.cache.ml_cache import MLPredictionCache
from app.core.config import Settings, get_settings
from app.core.errors import problem_response
from app.core.logging import configure_logging
from app.core.redis import create_redis_client
from app.db.session import Database
from app.environment.polling import EnvironmentalPollingService
from app.environment.providers.mock import MockEnvironmentalProvider
from app.environment.providers.open_meteo import OpenMeteoProvider
from app.environment.service import EnvironmentalService
from app.messaging.consumer import HandlerRegistry
from app.messaging.factory import create_event_publisher
from app.messaging.handlers import (
    SensorObservationHandler,
    SimulationEventHandler,
    WeatherObservedHandler,
)
from app.messaging.idempotency import RedisIdempotencyStore
from app.messaging.metrics import MessagingMetrics
from app.messaging.models import (
    EVENT_SENSOR_WATER_DEPTH,
    EVENT_SIMULATION_EMITTED,
    EVENT_WEATHER_OBSERVED,
)
from app.messaging.sqs.client import Boto3SqsClient
from app.messaging.sqs.consumer import SqsEventConsumer
from app.ml.builder import OnlineFeatureBuilder
from app.ml.service import FloodPredictionService
from app.realtime.runtime import FloodGuardRuntime
from app.risk.fusion import RiskFusionService
from app.schemas.health import HealthResponse
from app.services.health import HealthService

logger = logging.getLogger("floodguard.api")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    configure_logging("DEBUG" if config.debug else config.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database = Database(config)
        redis = create_redis_client(config)
        app.state.database = database
        app.state.redis = redis
        app.state.health_service = HealthService(database.engine, redis, config)

        cache_metrics = CacheMetrics()
        single_flight = SingleFlight()
        graph_cache = GraphCache(
            redis if config.cache_enabled else None,
            ttl_seconds=config.graph_cache_ttl_seconds,
            max_bytes=config.graph_cache_max_bytes,
            enabled=config.cache_enabled,
            metrics=cache_metrics,
        )
        route_cache = RouteCache(
            redis if config.cache_enabled else None,
            ttl_seconds=config.route_cache_ttl_seconds,
            enabled=config.cache_enabled,
            metrics=cache_metrics,
        )
        risk_cache = RiskSnapshotCache(
            redis if config.cache_enabled else None,
            ttl_seconds=config.risk_cache_ttl_seconds,
            enabled=config.cache_enabled,
            metrics=cache_metrics,
        )
        ml_cache = MLPredictionCache(
            redis if config.cache_enabled else None,
            ttl_seconds=config.ml_prediction_cache_ttl_seconds,
            enabled=config.cache_enabled,
            metrics=cache_metrics,
        )
        app.state.cache_metrics = cache_metrics
        app.state.single_flight = single_flight
        app.state.graph_cache = graph_cache
        app.state.route_cache = route_cache
        app.state.risk_cache = risk_cache
        app.state.ml_cache = ml_cache

        # Phase 13: ML Inference and Risk Fusion
        feature_builder = OnlineFeatureBuilder()
        loaded_model: LoadedFloodModel | None = None
        if config.ml_enabled and config.ml_mode != "DISABLED":
            model_path = Path(config.ml_model_path)
            if not model_path.is_absolute():
                model_path = Path(__file__).resolve().parents[2] / model_path

            # Phase 17: Cache model from S3 locally
            if getattr(config, "ml_s3_bucket", None):
                try:
                    import os

                    import boto3

                    s3_client = boto3.client(
                        "s3", region_name=getattr(config, "aws_region", "us-east-1")
                    )
                    bucket = config.ml_s3_bucket
                    s3_key = getattr(
                        config, "ml_s3_key", f"ml/models/{config.ml_model_version}/model.json"
                    )

                    os.makedirs(model_path.parent, exist_ok=True)
                    s3_client.download_file(bucket, s3_key, str(model_path))
                    logger.info(
                        "ml_model_downloaded_from_s3",
                        extra={"bucket": bucket, "key": s3_key, "dest": str(model_path)},
                    )
                except Exception as e:
                    logger.warning("ml_model_s3_download_failed", extra={"error": str(e)})

            try:
                loaded_model = LoadedFloodModel.load(model_path)
                schema_features = loaded_model.expected_features
                if not schema_features:
                    raise ValueError("Model feature schema is empty")
                dummy_sample = {feat: 0.0 for feat in schema_features}
                dummy_pred = loaded_model.predict_proba([dummy_sample])
                prob_val = float(dummy_pred[0, 1] if dummy_pred.ndim == 2 else dummy_pred[0])
                if not (0.0 <= prob_val <= 1.0):
                    raise ValueError(f"Warm-up prediction returned invalid probability: {prob_val}")
                logger.info(
                    "ml_model_loaded",
                    extra={
                        "model_version": loaded_model.metadata.get(
                            "model_version", config.ml_model_version
                        ),
                        "model_path": str(model_path),
                        "ml_mode": config.ml_mode,
                    },
                )
            except Exception as e:
                logger.warning(
                    "ml_model_load_failed_falling_back_to_deterministic",
                    extra={"error": str(e), "model_path": str(model_path)},
                    exc_info=True,
                )
                loaded_model = None

        prediction_service = FloodPredictionService(
            settings=config,
            model=loaded_model,
            feature_builder=feature_builder,
            cache=ml_cache,
        )
        fusion_service = RiskFusionService(
            settings=config,
        )
        app.state.feature_builder = feature_builder
        app.state.prediction_service = prediction_service
        app.state.fusion_service = fusion_service

        runtime = FloodGuardRuntime.create(
            config,
            prediction_service=prediction_service,
            fusion_service=fusion_service,
        )
        app.state.runtime = runtime
        app.state.event_bus = runtime.event_bus
        app.state.realtime_publisher = runtime.realtime_publisher
        app.state.active_route_registry = runtime.route_registry

        # Phase 14: Messaging & Asynchronous Event Processing
        messaging_metrics = MessagingMetrics()
        app.state.messaging_metrics = messaging_metrics

        idempotency_store = RedisIdempotencyStore(
            redis if config.cache_enabled else None,
            ttl_seconds=config.sqs_idempotency_ttl_seconds,
            fallback_mode=config.sqs_idempotency_fallback,
        )
        app.state.idempotency_store = idempotency_store

        handler_registry = HandlerRegistry()
        weather_handler = WeatherObservedHandler(
            risk_state=runtime.runtime_risk_state,
            event_bus=runtime.event_bus,
        )
        sensor_handler = SensorObservationHandler(
            risk_state=runtime.runtime_risk_state,
            event_bus=runtime.event_bus,
        )
        simulation_handler = SimulationEventHandler(
            runtime=runtime,
        )
        handler_registry.register(EVENT_WEATHER_OBSERVED, weather_handler)
        handler_registry.register(EVENT_SENSOR_WATER_DEPTH, sensor_handler)
        handler_registry.register(EVENT_SIMULATION_EMITTED, simulation_handler)
        app.state.handler_registry = handler_registry

        sqs_consumer: SqsEventConsumer | None = None
        event_publisher = create_event_publisher(config, messaging_metrics)
        if config.event_transport in {"SQS", "EVENTBRIDGE"} and config.sqs_enabled:
            sqs_client = Boto3SqsClient(
                endpoint_url=config.sqs_endpoint_url,
                region_name=config.aws_region,
            )
            sqs_consumer = SqsEventConsumer(
                client=sqs_client,
                queue_url=config.sqs_environment_queue_url,
                registry=handler_registry,
                idempotency=idempotency_store,
                metrics=messaging_metrics,
                visibility_timeout=config.sqs_visibility_timeout_seconds,
                poll_wait_seconds=config.sqs_poll_wait_seconds,
                max_messages=config.sqs_max_messages,
                concurrency=config.sqs_consumer_concurrency,
            )
            sqs_consumer.start()

        app.state.event_publisher = event_publisher
        app.state.sqs_consumer = sqs_consumer

        # Phase 10: Environmental Data Adapter
        if config.environment_provider == "open_meteo":
            env_provider = OpenMeteoProvider(
                base_url=config.weather_api_base_url,
                timeout_seconds=config.weather_request_timeout_seconds,
                api_key=(
                    config.weather_api_key.get_secret_value() if config.weather_api_key else None
                ),
            )
        else:
            env_provider = MockEnvironmentalProvider()

        env_service = EnvironmentalService(
            provider=env_provider,
            redis=redis if config.cache_enabled else None,
            cache_ttl_seconds=config.weather_cache_ttl_seconds,
            freshness_fresh_seconds=config.weather_freshness_fresh_seconds,
            freshness_stale_seconds=config.weather_freshness_stale_seconds,
        )
        app.state.environmental_service = env_service

        env_polling: EnvironmentalPollingService | None = None
        if config.weather_polling_enabled and config.weather_monitored_locations:
            env_polling = EnvironmentalPollingService(
                env_service=env_service,
                runtime_risk_state=runtime.runtime_risk_state,
                locations=config.weather_monitored_locations,
                interval_seconds=config.weather_polling_interval_seconds,
                event_bus=runtime.event_bus,
                event_publisher=(event_publisher if sqs_consumer is not None else None),
            )
            await env_polling.start()
        app.state.environmental_polling_service = env_polling

        logger.info("application_startup", extra={"app_env": config.app_env})
        try:
            # Keep liveness available during dependency outages; readiness reports failure.
            startup = await app.state.health_service.readiness("startup")
            logger.info(
                "startup_dependency_check",
                extra={"status_code": 200 if startup.ready else 503},
            )
            yield
        finally:
            if sqs_consumer is not None:
                await sqs_consumer.stop()
            if env_polling is not None:
                await env_polling.stop()
            runtime.close()
            await asyncio.gather(database.close(), redis.aclose())
            logger.info("application_shutdown")

    app = FastAPI(
        title="FloodGuard API",
        version=config.app_version,
        debug=False,  # Client responses never expose debug tracebacks.
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url=f"{config.api_v1_prefix}/openapi.json",
        redoc_url=None,
    )
    app.state.settings = config

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else str(uuid4())
        )
        try:
            response = await call_next(request)
        except Exception as error:
            logger.error(
                "unhandled_http_error",
                exc_info=True,
                extra={
                    "request_id": request.state.request_id,
                    "error_type": type(error).__name__,
                    "status_code": 500,
                },
            )
            response = problem_response(
                request, 500, "INTERNAL_ERROR", "Internal error", "An unexpected error occurred."
            )
        response.headers["X-Request-ID"] = request.state.request_id
        if response.status_code >= 400:
            logger.warning(
                "http_error",
                extra={"request_id": request.state.request_id, "status_code": response.status_code},
            )
        return response

    from app.core.security_middleware import RequestSizeLimitMiddleware, SecurityHeadersMiddleware
    from app.observability.middleware import ObservabilityMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ObservabilityMiddleware)
    app.add_middleware(RequestSizeLimitMiddleware, max_upload_size=5 * 1024 * 1024)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS", "PUT", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        title = "Resource not found" if error.status_code == 404 else "Request rejected"
        return problem_response(request, error.status_code, "HTTP_ERROR", title, title)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        return problem_response(
            request, 422, "VALIDATION_ERROR", "Invalid request", "Request validation failed."
        )

    app.add_api_route("/health", live_health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route("/health/live", live_health, methods=["GET"], response_model=HealthResponse)

    from app.api.v1.auth import router as auth_router

    app.include_router(auth_router, prefix=config.api_v1_prefix)

    app.include_router(health_router, prefix=config.api_v1_prefix)
    app.include_router(routes_router, prefix=config.api_v1_prefix)
    app.include_router(realtime_router, prefix=config.api_v1_prefix)
    app.include_router(simulation_router, prefix=config.api_v1_prefix)
    app.include_router(environment_router, prefix=config.api_v1_prefix)
    app.include_router(incidents_router, prefix=config.api_v1_prefix)
    app.include_router(assistant_router, prefix=config.api_v1_prefix)

    from app.observability.health import router as obs_health_router

    app.include_router(obs_health_router, prefix="")
    return app
