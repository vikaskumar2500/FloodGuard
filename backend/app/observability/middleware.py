import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from .context import generate_correlation_id, set_correlation_id
from .metrics import HTTPMetrics
from .tracing import get_tracer


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 1. Correlation ID
        correlation_id = request.headers.get("x-correlation-id") or generate_correlation_id()
        set_correlation_id(correlation_id)

        # 2. Tracing
        tracer = get_tracer("http_middleware")

        start_time = time.time()
        with tracer.start_span(f"{request.method} {request.url.path}"):
            try:
                response = await call_next(request)
                status_code = response.status_code
                response.headers["x-correlation-id"] = correlation_id
            except Exception:
                status_code = 500
                raise
            finally:
                latency = time.time() - start_time
                HTTPMetrics.record_request(request.method, status_code, latency)

        return response
