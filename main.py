"""FastAPI entry point for Insight AI Agent service."""

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import get_settings

settings = get_settings()

app = FastAPI(
    title="Insight AI Agent",
    description="Educational AI Agent service with multi-model LLM support",
    version="0.2.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Register routers ────────────────────────────────────────
from api.health import router as health_router  # noqa: E402
from api.chat import router as chat_router  # noqa: E402
from api.models_routes import router as models_router  # noqa: E402
from api.workflow import router as workflow_router  # noqa: E402
from api.page import router as page_router  # noqa: E402

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(models_router)
app.include_router(workflow_router)
app.include_router(page_router)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=settings.debug,
    )
