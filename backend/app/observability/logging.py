import json
import logging
import sys

from .context import get_correlation_id


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
            "correlation_id": get_correlation_id(),
        }

        # Redaction logic
        redact_keys = {"password", "token", "secret", "authorization"}

        if hasattr(record, "extra_data"):
            extra = record.extra_data
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if any(rk in k.lower() for rk in redact_keys):
                        log_data[k] = "***REDACTED***"
                    else:
                        log_data[k] = v

        return json.dumps(log_data)


def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    formatter = JSONFormatter()
    handler.setFormatter(formatter)

    logger.addHandler(handler)


def get_logger(name: str):
    return logging.getLogger(name)
