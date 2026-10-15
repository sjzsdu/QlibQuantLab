"""结构化日志与 request_id 贯穿。"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")
_org_id: contextvars.ContextVar[str] = contextvars.ContextVar("org_id", default="-")

_RESERVED = set(
    [
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
        "taskName",
        "message",
        "asctime",
    ]
)


class JsonFormatter(logging.Formatter):
    """轻量 JSON 行日志（不引入第三方依赖）。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": _request_id.get(),
            "user_id": _user_id.get(),
            "org_id": _org_id.get(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                payload[key] = repr(value)
            else:
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    # uvicorn 自带 handler，避免重复输出
    for noisy in ("uvicorn.access",):
        logging.getLogger(noisy).handlers = []


def set_request_context(request_id: str, user_id: str = "-", org_id: str = "-") -> None:
    _request_id.set(request_id)
    _user_id.set(user_id)
    _org_id.set(org_id)


def get_request_id() -> str:
    return _request_id.get()


def bind_user(user_id: str, org_id: str) -> None:
    _user_id.set(user_id)
    _org_id.set(org_id)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
