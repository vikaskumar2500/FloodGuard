import contextvars
from uuid import uuid4

_correlation_id_ctx_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)


def get_correlation_id() -> str:
    return _correlation_id_ctx_var.get()


def set_correlation_id(correlation_id: str) -> None:
    _correlation_id_ctx_var.set(correlation_id)


def generate_correlation_id() -> str:
    return str(uuid4())
