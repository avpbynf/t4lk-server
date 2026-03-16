"""Application factory for the T4lk FastAPI server."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from stt.engine import WhisperEngine
from stt.middlewares import (
    AccessLogMiddleware,
    ExecutionTimeMiddleware,
    TraceMiddleware,
    add_exception_middleware,
)
from stt.models import HealthResponse
from stt.routes import router
from stt.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: load model on startup, unload on shutdown.

    Args:
        app: The FastAPI application instance.

    Yields:
        Nothing — control returns to FastAPI during the application lifetime.
    """
    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    engine = WhisperEngine(settings)
    await engine.load()
    app.state.engine = engine

    yield

    engine.unload()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Middleware registration order determines execution order (LIFO):
    - ExecutionTimeMiddleware wraps everything (outermost)
    - TraceMiddleware injects a trace ID per request
    - AccessLogMiddleware logs completed requests
    - add_exception_middleware handles all unhandled exceptions (innermost)
    - CORSMiddleware is added last when CORS origins are configured

    Returns:
        FastAPI: Configured application instance.
    """
    settings = get_settings()

    app = FastAPI(
        title="T4lk",
        description="T4lk Speech-to-Text API (OpenAI-compatible)",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware stack (registration order = inverse execution order)
    # 1. Exception handler (innermost - catches all errors)
    add_exception_middleware(app)
    # 2. Access log
    app.add_middleware(AccessLogMiddleware)
    # 3. Trace ID
    app.add_middleware(TraceMiddleware)
    # 4. Execution time (outermost)
    app.add_middleware(ExecutionTimeMiddleware)
    # 5. CORS (if configured)
    if settings.CORS_ALLOW_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ALLOW_ORIGINS,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    # Routes
    app.include_router(router)

    # Health endpoint (outside /v1)
    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        """Health check endpoint.

        Args:
            request: The current FastAPI request.

        Returns:
            HealthResponse with current model and queue status.
        """
        engine: WhisperEngine = request.app.state.engine
        return HealthResponse(
            status="ok" if engine.is_loaded else "degraded",
            model_loaded=engine.is_loaded,
            device=settings.DEVICE,
            queue_size=engine.queue_size,
        )

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run("stt.main:app", host=settings.HOST, port=settings.PORT, reload=True)
