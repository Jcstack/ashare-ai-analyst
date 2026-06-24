"""FastAPI application factory for the A-share web interface.

Entry point: ``python -m src.web.app``
"""

import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.utils.config import load_config
from src.utils.logger import get_logger
from src.web.routes import api_v1

logger = get_logger("web.app")

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_STATIC_DIR = _PROJECT_ROOT / "static"

_SLOW_REQUEST_THRESHOLD = 2.0  # seconds

# Valid A-share symbol: 6 digits, optionally prefixed by exchange letters
# or suffixed by .SZ/.SH/.BJ (e.g. 000983, sz000983, 000983.SZ)
_SYMBOL_RE = re.compile(r"^[A-Za-z]{0,2}\d{6}(?:\.[A-Za-z]{2,3})?$")

# URL path segments where the next segment is a stock symbol
_SYMBOL_ROUTES = re.compile(r"/api/v1/(?:stock|predict|advisor/stock)/([^/]+)")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan: pre-warm singletons on startup."""
    from src.utils.config import get_data_dir
    from src.web.dependencies import (
        get_notification_orchestrator,
        get_signal_bus,
        get_signal_store,
        get_stock_registry,
        get_stock_service,
        get_trading_calendar,
    )

    logger.info("Initializing services...")
    # Install EastMoney proxy patch BEFORE any akshare call
    from src.data.eastmoney_proxy import init_proxy_patch

    init_proxy_patch()

    # Ensure data directories exist before any service tries to write
    get_data_dir("processed")
    get_data_dir("raw")
    registry = get_stock_registry()
    get_stock_service()
    get_trading_calendar()

    # Pre-warm the stock registry cache so first search isn't 60s+
    try:
        registry.fetch_all_stocks()
        logger.info("Stock registry pre-warmed")
    except Exception as exc:
        logger.warning("Stock registry pre-warm failed: %s", exc)

    # Wire and start the signal bus with consumers
    bus = get_signal_bus()
    store = get_signal_store()
    orchestrator = get_notification_orchestrator()

    async def _store_consumer(signal) -> None:
        store.store(signal)

    async def _orchestrator_consumer(signal) -> None:
        orchestrator.process(signal)

    bus.register_consumer("signal_store", _store_consumer)
    bus.register_consumer("notification_orchestrator", _orchestrator_consumer)
    bus.start()

    logger.info("Backend ready")
    yield
    logger.info("Shutting down...")
    await bus.stop()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI instance with all routes and middleware.
    """
    # Load .env for local development (no-op if vars already set, e.g. Docker)
    load_dotenv()

    web_config = load_config("web")
    server_cfg = web_config.get("server", {})

    app = FastAPI(
        title="A股智能分析系统",
        description="A-share Smart Stock Analysis System",
        version="0.1.0-dev",
        lifespan=lifespan,
        docs_url="/docs" if server_cfg.get("debug", False) else None,
        redoc_url=None,
    )

    # Store config in app state for dependency injection
    app.state.web_config = web_config

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # CORS middleware for React SPA dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:80",
            "http://localhost",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Symbol validation middleware — reject injection payloads early
    @app.middleware("http")
    async def symbol_validation_middleware(request: Request, call_next):
        path = request.url.path
        m = _SYMBOL_ROUTES.match(path)
        if m:
            symbol = m.group(1)
            if not _SYMBOL_RE.match(symbol):
                return JSONResponse(
                    status_code=400,
                    content={
                        "status": "error",
                        "message": "Invalid stock symbol format",
                    },
                )
        return await call_next(request)

    # Request timing middleware
    @app.middleware("http")
    async def timing_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        elapsed = time.perf_counter() - start
        response.headers["X-Process-Time"] = f"{elapsed:.3f}"
        if elapsed > _SLOW_REQUEST_THRESHOLD:
            logger.warning(
                "Slow request: %s %s %.2fs",
                request.method,
                request.url.path,
                elapsed,
            )
        return response

    # Health check endpoint (used by Docker healthcheck before routing traffic)
    @app.get("/health")
    async def health_check():
        return {"status": "ok"}

    @app.get("/health/deep")
    async def health_deep():
        """Deep health check — verifies all critical dependencies."""
        checks: dict[str, str] = {}

        # Redis (Celery broker)
        try:
            from src.web.dependencies import get_redis

            r = get_redis()
            if r:
                r.ping()
                checks["redis"] = "ok"
            else:
                checks["redis"] = "unavailable"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"

        # EventBus (Redis Streams)
        try:
            from src.event_bus.bus import EventBus

            EventBus()
            # EventBus lazily connects; just verify config resolves
            checks["eventbus"] = "ok"
        except Exception as exc:
            checks["eventbus"] = f"error: {exc}"

        # LLM Router
        try:
            from src.web.dependencies import get_llm_router

            router = get_llm_router()
            providers = [p.value for p in router._providers.keys()]
            checks["llm"] = f"ok ({', '.join(providers)})"
        except Exception as exc:
            checks["llm"] = f"error: {exc}"

        all_ok = all(v.startswith("ok") for v in checks.values())
        status_code = 200 if all_ok else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "ok" if all_ok else "degraded",
                "checks": checks,
            },
        )

    # JSON REST API v1 for React SPA
    app.include_router(api_v1.router)

    # Global exception handler — return structured JSON for unhandled errors
    # Never echo raw exception messages (may contain user input)
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled: %s %s — %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": "Internal server error",
                "error_type": type(exc).__name__,
            },
        )

    logger.info("A-share web app initialized")
    return app


app = create_app()


if __name__ == "__main__":
    web_config = load_config("web")
    server_cfg = web_config.get("server", {})

    uvicorn.run(
        "src.web.app:app",
        host=server_cfg.get("host", "127.0.0.1"),
        port=server_cfg.get("port", 8000),
        reload=server_cfg.get("reload", True),
    )
