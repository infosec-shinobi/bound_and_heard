from fastapi import APIRouter, Form, Request, status
from fastapi.responses import RedirectResponse, Response
from starlette.responses import HTMLResponse

from app.core.templates import template_context, templates
from app.core.write_protection import (
    ADMIN_SESSION_KEY,
    verify_admin_password,
)


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("")
async def admin_index() -> RedirectResponse:
    return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)


def render_login_page(
    request: Request,
    *,
    error: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "admin/login.html",
        template_context(request, page_title="Admin Login", error=error),
        status_code=status_code,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return render_login_page(request)


@router.post("/login")
async def login(request: Request, password: str = Form(...)) -> Response:
    settings = request.app.state.settings
    if not request.app.state.writes_enabled:
        return render_login_page(
            request,
            error="Write actions are disabled until an admin password is configured.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    if not verify_admin_password(password, settings.admin_password):
        return render_login_page(
            request,
            error="Invalid admin password.",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    request.session[ADMIN_SESSION_KEY] = True
    return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    request.session.pop(ADMIN_SESSION_KEY, None)
    return RedirectResponse("/admin/login", status_code=status.HTTP_303_SEE_OTHER)
