"""FastAPI application setup and route registration."""

import os
import time
from pathlib import Path
from app.logging_setup import configure_logs, RequestLogging
from collections import defaultdict, deque
from threading import Lock
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.database import init_db
from app.api import incidents, tools, voice, auth, integrations


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    from app.adapters import bank
    bank.start_warmup()
    yield


app = FastAPI(title="Guardian", version="0.2.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, exc):
    return JSONResponse(status_code=422, content={"detail": "Invalid input. Check the required fields and allowed values."})
_requests = defaultdict(deque)
_rate_lock = Lock()


@app.middleware("http")
async def limit_writes(request, call_next):
    if request.method == "POST":
        # Single-instance limit; multiple workers need an ingress limiter.
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with _rate_lock:
            for old in list(_requests):
                if not _requests[old] or _requests[old][-1] < now - 60:
                    del _requests[old]
            bucket = _requests[key]
            while bucket and bucket[0] < now - 60:
                bucket.popleft()
            if len(bucket) >= 120:
                return JSONResponse({"detail": "Too many requests. Try again in a minute."}, status_code=429, headers={"Retry-After": "60"})
            bucket.append(now)
    return await call_next(request)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"]
    + [
        origin.strip()
        for origin in os.getenv("GUARDIAN_FRONTEND_ORIGINS", "").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_credentials=True,
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)
app.include_router(voice.router)
app.include_router(incidents.router)
app.include_router(tools.router)
app.include_router(auth.router)
app.include_router(integrations.router)
from app.tools import AGORA_TOOL_NAMES
app.state.tool_log_names = set(AGORA_TOOL_NAMES) | set(AGORA_TOOL_NAMES.values())
logger, access_logger = configure_logs(os.getenv("GUARDIAN_LOG_DIR") or Path(__file__).resolve().parents[1] / "logs", "guardian")
app.add_middleware(RequestLogging, logger=logger, access=access_logger)


@app.get("/health")
def health():
    return {"status": "ok", "service": "guardian-api"}
