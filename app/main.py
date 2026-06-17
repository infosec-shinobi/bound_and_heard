import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.api.admin import router as admin_router
from app.core.bootstrap import bootstrap_default_user
from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


def build_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if not settings.writes_enabled:
            logger.warning(
                "BOUND_AND_HEARD_ADMIN_PASSWORD is not set; write actions are disabled."
            )
        bootstrap_default_user(settings.default_user_name)
        yield

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, lifespan=build_lifespan(settings))
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret)
    app.state.settings = settings
    app.state.writes_enabled = settings.writes_enabled
    app.include_router(admin_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
