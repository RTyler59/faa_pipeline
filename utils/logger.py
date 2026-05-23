import json
import logging
import time
from typing import Any, Dict


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = {
            k: v
            for k, v in record.__dict__.items()
            if k not in logging.LogRecord.__dict__ and k not in (
                "msg", "args", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "filename", "module", "pathname",
                "created", "msecs", "relativeCreated", "thread", "threadName",
                "processName", "process", "name", "levelname", "levelno",
                "message",
            )
        }
        if extra:
            payload["extra"] = extra
        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level, logging.INFO))
