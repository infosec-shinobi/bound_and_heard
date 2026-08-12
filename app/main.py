import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import URL
from starlette.middleware.sessions import SessionMiddleware

from app.api.admin import router as admin_router
from app.api.books import router as books_router
from app.api.imports import router as imports_router
from app.api.pages import router as pages_router
from app.api.scraping import router as scraping_router
from app.api.settings import router as settings_router
from app.core.bootstrap import bootstrap_default_user
from app.core.config import Settings, get_settings
from app.core.templates import template_context, templates


logger = logging.getLogger(__name__)

WRITE_PROTECTION_DETAILS = {
    "Admin login is required for write actions.",
    "Write actions are disabled because BOUND_AND_HEARD_ADMIN_PASSWORD is not set.",
}


def login_next_url(request: Request) -> str:
    url = URL(str(request.url))
    path = url.path
    if url.query:
        path = f"{path}?{url.query}"
    return path


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
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.state.settings = settings
    app.state.writes_enabled = settings.writes_enabled

    @app.exception_handler(HTTPException)
    async def html_write_protection_handler(request: Request, exc: HTTPException) -> Response:
        accept = request.headers.get("accept", "")
        if exc.status_code == 403 and exc.detail in WRITE_PROTECTION_DETAILS and "text/html" in accept:
            return templates.TemplateResponse(
                request,
                "admin/login.html",
                template_context(
                    request,
                    page_title="Admin Login",
                    error=str(exc.detail),
                    next_url=login_next_url(request),
                ),
                status_code=exc.status_code,
                headers=exc.headers,
            )

        return JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    app.include_router(admin_router)
    app.include_router(books_router)
    app.include_router(imports_router)
    app.include_router(scraping_router)
    app.include_router(settings_router)
    app.include_router(pages_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
