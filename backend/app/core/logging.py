import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        standard = {
            "name",
            "msg",
            "args",
            "levelname",
            "levelno",
            "pathname",
            "filename",
            "module",
            "exc_info",
            "exc_text",
            "stack_info",
            "lineno",
            "funcName",
            "created",
            "msecs",
            "relativeCreated",
            "thread",
            "threadName",
            "processName",
            "process",
            "message",
            "asctime",
        }
        for key, val in record.__dict__.items():
            if key not in standard and not key.startswith("_"):
                # Redact sensitive keys
                if any(
                    secret_term in key.lower()
                    for secret_term in ["password", "secret", "token", "key", "authorization"]
                ):
                    payload[key] = "***REDACTED***"
                else:
                    payload[key] = val
        return json.dumps(payload, default=str)


def configure_logging(level: str) -> None:
    logger = logging.getLogger("floodguard")
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger.handlers = [handler]
    logger.setLevel(level)
    logger.propagate = False
