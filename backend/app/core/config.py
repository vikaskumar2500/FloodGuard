import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
        hide_input_in_errors=True,
    )

    app_name: str = "floodguard-api"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_version: str = "0.1.0"
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://floodguard:change-me-local-only@localhost:5432/floodguard"
    )
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    api_v1_prefix: str = "/api/v1"
    frontend_url: str = "http://localhost:3000"
    health_check_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    redis_required: bool = True
    max_route_snap_distance_m: float = Field(default=5_000, gt=0, le=100_000)
    max_routing_expansions: int = Field(default=1_000_000, gt=0, le=10_000_000)
    risk_balanced_penalty_seconds: float = Field(default=120.0, ge=0)
    risk_safest_penalty_seconds: float = Field(default=900.0, ge=0)
    risk_safest_unknown_penalty_seconds: float = Field(default=60.0, ge=0)
    risk_change_threshold: float = Field(default=0.3, ge=0, le=1)
    reroute_min_risk_improvement: float = Field(default=0.1, ge=0, le=1)
    reroute_unsafe_threshold: float = Field(default=0.7, ge=0, le=1)
    reroute_recovery_threshold: float = Field(default=0.55, ge=0, le=1)
    reroute_cooldown_seconds: float = Field(default=30.0, ge=0)
    realtime_heartbeat_seconds: float = Field(default=15.0, gt=0)
    realtime_queue_size: int = Field(default=16, ge=4, le=1024)
    enable_simulation_api: bool = True
    use_fixture_routing: bool = False
    active_route_ttl_seconds: float = Field(default=900.0, gt=0)
    cache_enabled: bool = True
    graph_cache_ttl_seconds: int = Field(default=86400, gt=0)
    route_cache_ttl_seconds: int = Field(default=3600, gt=0)
    risk_cache_ttl_seconds: int = Field(default=3600, gt=0)
    graph_cache_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)

    # --- Phase 10: Environmental Data Adapter ---
    environment_provider: str = Field(default="mock")  # "mock" | "open_meteo"
    weather_api_key: SecretStr | None = Field(default=None)
    weather_api_base_url: str = Field(default="https://api.open-meteo.com")
    weather_request_timeout_seconds: float = Field(default=5.0, gt=0)
    weather_cache_ttl_seconds: int = Field(default=300, gt=0)
    weather_polling_enabled: bool = Field(default=False)
    weather_polling_interval_seconds: float = Field(default=300.0, gt=0)
    weather_monitored_locations: list[tuple[float, float]] = Field(default_factory=list)
    weather_freshness_fresh_seconds: int = Field(default=600, gt=0)
    weather_freshness_stale_seconds: int = Field(default=3600, gt=0)

    # --- Phase 13: ML Integration with Routing ---
    ml_enabled: bool = Field(default=True)
    ml_mode: Literal["DISABLED", "SHADOW", "ACTIVE"] = Field(default="SHADOW")
    ml_model_path: str = Field(default="ml/artifacts/xgboost-v1")
    ml_model_version: str = Field(default="xgboost-v1")
    ml_prediction_threshold: float | None = Field(default=None)
    ml_max_inference_batch_size: int = Field(default=256, gt=0)
    ml_inference_timeout_ms: float = Field(default=500.0, gt=0)
    ml_risk_weight: float = Field(default=0.35, ge=0.0, le=1.0)
    ml_min_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    ml_prediction_cache_ttl_seconds: int = Field(default=300, gt=0)

    # --- Phase 14: Messaging & AWS SQS ---
    event_transport: Literal["IN_PROCESS", "SQS", "EVENTBRIDGE"] = Field(default="IN_PROCESS")
    eventbridge_enabled: bool = False
    eventbridge_bus_name: str = "floodguard-dev-events"
    eventbridge_source: str = "com.floodguard"
    eventbridge_endpoint_url: str | None = None
    sqs_enabled: bool = Field(default=False)
    aws_region: str = Field(default="us-east-1")
    sqs_endpoint_url: str | None = Field(default=None)
    sqs_environment_queue_url: str = Field(
        default="http://localhost:4566/000000000000/floodguard-environment-events"
    )
    sqs_poll_wait_seconds: int = Field(default=20, ge=0, le=20)
    sqs_max_messages: int = Field(default=10, ge=1, le=10)
    sqs_visibility_timeout_seconds: int = Field(default=60, ge=1, le=43200)
    sqs_consumer_concurrency: int = Field(default=5, ge=1, le=100)
    sqs_idempotency_ttl_seconds: int = Field(default=86400, gt=0)
    sqs_idempotency_fallback: Literal["DEGRADED_PROCESS", "REJECT"] = Field(
        default="DEGRADED_PROCESS"
    )

    # --- Phase 16: Retry Policies, DLQ & Failure Recovery ---
    sqs_dlq_url: str | None = Field(default=None)
    sqs_max_receive_count: int = Field(default=5, ge=1, le=100)
    sqs_retry_base_delay_seconds: int = Field(default=5, ge=1)
    sqs_retry_max_delay_seconds: int = Field(default=300, ge=1)
    sqs_retry_jitter: bool = Field(default=True)
    event_handler_timeout_seconds: int = Field(default=30, ge=1)
    idempotency_completed_ttl_seconds: int = Field(default=86400, gt=0)

    # --- Phase 20: Authentication, Authorization & Security Hardening ---
    jwt_secret_key: SecretStr = Field(default=SecretStr("super-secret-key-change-in-production"))
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=30, gt=0)
    sse_token_expire_seconds: int = Field(default=300, gt=0)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_requests: int = Field(default=100, gt=0)
    rate_limit_window_seconds: int = Field(default=60, gt=0)
    rate_limit_login_requests: int = Field(default=5, gt=0)
    rate_limit_login_window_seconds: int = Field(default=300, gt=0)

    @model_validator(mode="after")
    def validate_timeouts(self):
        if self.sqs_idempotency_ttl_seconds <= self.event_handler_timeout_seconds:
            raise ValueError(
                "PROCESSING_LEASE_TTL (sqs_idempotency_ttl_seconds) must be strictly greater than EVENT_HANDLER_TIMEOUT_SECONDS"
            )
        if self.sqs_visibility_timeout_seconds <= self.event_handler_timeout_seconds:
            raise ValueError(
                "SQS_VISIBILITY_TIMEOUT_SECONDS must be strictly greater than EVENT_HANDLER_TIMEOUT_SECONDS"
            )
        return self

    @model_validator(mode="after")
    def validate_eventbridge_transport(self):
        if self.event_transport == "EVENTBRIDGE":
            if not self.eventbridge_enabled or not self.sqs_enabled:
                raise ValueError("EVENTBRIDGE requires EVENTBRIDGE_ENABLED and SQS_ENABLED")
            bus = self.eventbridge_bus_name.strip()
            if not bus or bus == "default" or bus.endswith(":event-bus/default"):
                raise ValueError("EVENTBRIDGE requires a custom event bus name or ARN")
            if not self.eventbridge_source.strip() or not self.sqs_environment_queue_url.strip():
                raise ValueError("EVENTBRIDGE requires source and processing SQS queue URL")
        return self

    @model_validator(mode="after")
    def protect_development_features(self):
        if self.app_env == "production":
            if "enable_simulation_api" in self.model_fields_set and self.enable_simulation_api:
                raise ValueError("simulation API must be disabled in production")
            if self.use_fixture_routing:
                raise ValueError("fixture routing must be disabled in production")
            object.__setattr__(self, "enable_simulation_api", False)
        return self

    @model_validator(mode="before")
    @classmethod
    def legacy_debug_fallback(cls, values: dict) -> dict:
        # An explicit namespaced setting, including .env, wins over generic host DEBUG.
        if "debug" in values:
            raw = values["debug"]
            if isinstance(raw, str) and raw.lower() not in {
                "1",
                "true",
                "yes",
                "on",
                "0",
                "false",
                "no",
                "off",
            }:
                values.pop("debug", None)
        if "APP_DEBUG" not in values and "debug" not in values:
            raw = os.getenv("DEBUG", values.get("DEBUG", False))
            if isinstance(raw, str):
                values["APP_DEBUG"] = raw.lower() in {"1", "true", "yes", "on"}
            else:
                values["APP_DEBUG"] = bool(raw)
        return values

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername != "postgresql+asyncpg" or not url.host or not url.database:
                raise ValueError
        except Exception:
            raise ValueError("DATABASE_URL must be a PostgreSQL asyncpg URL") from None
        return value

    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, value: SecretStr) -> SecretStr:
        from urllib.parse import urlsplit

        url = urlsplit(value.get_secret_value())
        if url.scheme not in {"redis", "rediss"} or not url.hostname:
            raise ValueError("REDIS_URL must be a Redis URL")
        return value

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/") or "?" in value or "#" in value:
            raise ValueError("API_V1_PREFIX must start with / and have no trailing slash")
        return value

    @field_validator("frontend_url")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        from urllib.parse import urlsplit

        url = urlsplit(value)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
        ):
            raise ValueError("FRONTEND_URL must be one explicit HTTP(S) origin")
        return value.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
