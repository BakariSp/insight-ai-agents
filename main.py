"""FastAPI entry point for Insight AI Agent service."""

import asyncio
import logging
from contextlib import asynccontextmanager

import litellm
import uvicorn

logger = logging.getLogger(__name__)
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings
from services.concurrency import ConcurrencyLimitMiddleware
from services.conversation_store import get_conversation_store, periodic_cleanup
from services.java_client import get_java_client
from services.middleware import RequestIdMiddleware
from insight_backend.rag_engine import init_rag_engine

# ── Global LiteLLM settings ──────────────────────────────────
litellm.request_timeout = 60  # 60s timeout for all LLM API calls

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle — start/stop shared resources."""
    client = get_java_client()
    await client.start()

    # Initialize RAG engine (non-blocking — parsing fails gracefully if DB is down)
    rag_engine = init_rag_engine()
    await rag_engine.initialize()

    # Initialize conversation store and start periodic cleanup
    store = get_conversation_store()
    cleanup_task = asyncio.create_task(periodic_cleanup(interval_seconds=300))

    # Verify Redis connectivity if using Redis store
    from services.conversation_store import RedisConversationStore
    if isinstance(store, RedisConversationStore):
        if await store.ping():
            logger.info("Redis connection verified")
        else:
            logger.warning("Redis connection failed — sessions may not persist")

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    # Close Redis connection if applicable
    if isinstance(store, RedisConversationStore):
        await store.close()

    await rag_engine.close()
    await client.close()


app = FastAPI(
    title="Insight AI Agent",
    description="Educational AI Agent service with multi-model LLM support",
    version="0.3.0",
    lifespan=lifespan,
)

# ── Middleware stack (outermost first) ─────────────────────────
# Order matters: CORS → RequestId → ConcurrencyLimit → route handler
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(ConcurrencyLimitMiddleware)

# ── Populate native tool registry (must happen before router import) ──
import tools.native_tools  # noqa: E402, F401  — registers tools via @register_tool

# ── Register routers ────────────────────────────────────────
from api.health import router as health_router  # noqa: E402
from api.models_routes import router as models_router  # noqa: E402
from api.workflow import router as workflow_router  # noqa: E402
from api.page import router as page_router  # noqa: E402
from api.conversation import router as conversation_router  # noqa: E402
from api.internal import router as internal_router  # noqa: E402
from api.files import router as files_router  # noqa: E402

app.include_router(health_router)
app.include_router(models_router)
app.include_router(workflow_router)
app.include_router(page_router)
app.include_router(conversation_router)
app.include_router(internal_router)
app.include_router(files_router)


if __name__ == "__main__":
    if settings.debug:
        # Development: single worker with reload
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=settings.service_port,
            reload=True,
        )
    else:
        # Production: multi-worker (prefer gunicorn on Linux; fallback to uvicorn multi-worker)
        # Best: gunicorn main:app -c deploy/gunicorn.conf.py
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=settings.service_port,
            workers=4,
            timeout_keep_alive=120,
        )
