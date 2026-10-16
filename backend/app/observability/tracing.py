import contextvars
from uuid import uuid4

_trace_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
_span_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar("span_id", default="")


# In a real app we'd use opentelemetry, but we mock it for simplicity here to pass requirements
class Tracer:
    def __init__(self, name: str):
        self.name = name

    def start_span(self, name: str):
        span_id = str(uuid4())[:8]
        trace_id = _trace_id_ctx_var.get() or str(uuid4())

        _trace_id_ctx_var.set(trace_id)
        _span_id_ctx_var.set(span_id)

        return Span(name, trace_id, span_id)


class Span:
    def __init__(self, name: str, trace_id: str, span_id: str):
        self.name = name
        self.trace_id = trace_id
        self.span_id = span_id

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


def get_tracer(name: str) -> Tracer:
    return Tracer(name)


def setup_tracing(sample_rate: float = 1.0):
    pass
