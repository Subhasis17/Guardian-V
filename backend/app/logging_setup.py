"""Rotating JSON logs; credentials, bodies and OAuth query strings are excluded."""
import json
import logging
import os
import re
import time
from contextvars import ContextVar
from logging.handlers import RotatingFileHandler
from pathlib import Path
from uuid import uuid4

request_id = ContextVar("request_id", default="-")

class SafeFormatter(logging.Formatter):
    def format(self, record):
        message = record.getMessage()
        message = re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[redacted]", message)
        for key, value in os.environ.items():
            if len(value) >= 8 and any(word in key for word in ("SECRET", "TOKEN", "PASSWORD", "CERTIFICATE", "API_KEY")):
                message = message.replace(value, "[redacted]")
        data = {"time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
                "process_id": os.getpid(),
                "level": record.levelname, "logger": record.name,
                "request_id": request_id.get(), "message": message}
        if record.exc_info:
            data["exception_type"] = record.exc_info[0].__name__
        return json.dumps(data, ensure_ascii=False)

def configure_logs(directory, service):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(service)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        for filename, minimum, maximum in (("info.log", logging.INFO, logging.WARNING),
                                           ("error.log", logging.WARNING, logging.CRITICAL + 1)):
            handler = RotatingFileHandler(directory / filename, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
            handler.setLevel(minimum)
            handler.addFilter(lambda record, upper=maximum: record.levelno < upper)
            handler.setFormatter(SafeFormatter())
            logger.addHandler(handler)
        handler = RotatingFileHandler(directory / "tools.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        handler.addFilter(lambda record: record.getMessage().startswith("tool_"))
        handler.setFormatter(SafeFormatter())
        logger.addHandler(handler)
    access = logging.getLogger(service + ".access")
    access.setLevel(logging.INFO)
    access.propagate = False
    if not access.handlers:
        handler = RotatingFileHandler(directory / "access.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
        handler.setFormatter(SafeFormatter())
        access.addHandler(handler)
    # Uvicorn's default access logger includes OAuth codes in query strings.
    logging.getLogger("uvicorn.access").disabled = True
    uvicorn = logging.getLogger("uvicorn.error")
    for handler in logger.handlers:
        if handler not in uvicorn.handlers:
            uvicorn.addHandler(handler)
    logger.info("service_logging_started service=%s", service)
    return logger, access

class RequestLogging:
    def __init__(self, app, logger, access):
        self.app, self.logger, self.access = app, logger, access

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        marker = request_id.set(uuid4().hex)
        started, status = time.monotonic(), 500
        tool = None
        if scope["path"].startswith(("/api/agent-tools/", "/api/tools/")):
            candidate = scope["path"].rsplit("/", 1)[-1]
            tool = candidate if candidate in getattr(scope["app"].state, "tool_log_names", set()) else "unregistered"
            self.logger.info("tool_request_received tool=%s method=%s", tool, scope["method"])
        async def logged_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = list(message.get("headers", [])) + [(b"x-request-id", request_id.get().encode())]
            await send(message)
        try:
            await self.app(scope, receive, logged_send)
        except Exception as exc:
            self.logger.error("request_exception type=%s", type(exc).__name__)
            raise
        finally:
            route = scope.get("route")
            path = getattr(route, "path", "<unmatched>")
            values = (scope["method"], path, status, round((time.monotonic() - started) * 1000, 2))
            self.access.info("method=%s route=%s status=%s duration_ms=%s", *values)
            if tool:
                self.logger.log(logging.ERROR if status >= 400 else logging.INFO,
                                "tool_request_finished tool=%s http_status=%s duration_ms=%.2f", tool, status, (time.monotonic()-started)*1000)
            if status >= 400:
                self.logger.log(logging.ERROR if status >= 500 else logging.WARNING,
                                "request_failed method=%s route=%s status=%s duration_ms=%s", *values)
            request_id.reset(marker)

