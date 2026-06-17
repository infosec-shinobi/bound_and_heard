from fastapi import APIRouter, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.write_protection import (
    ADMIN_SESSION_KEY,
    is_admin_authenticated,
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
    writes_enabled = bool(request.app.state.writes_enabled)
    is_authenticated = is_admin_authenticated(request)

    disabled_message = ""
    if not writes_enabled:
        disabled_message = (
            "<p><strong>Write actions are disabled.</strong> Set "
            "<code>BOUND_AND_HEARD_ADMIN_PASSWORD</code> to enable admin login.</p>"
        )

    error_message = f"<p><strong>{error}</strong></p>" if error else ""
    auth_message = "<p>You are signed in as admin.</p>" if is_authenticated else ""
    login_disabled = "disabled" if not writes_enabled else ""

    html = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Admin Login</title>
      </head>
      <body>
        <main>
          <h1>Admin Login</h1>
          {disabled_message}
          {error_message}
          {auth_message}
          <form method="post" action="/admin/login">
            <label for="password">Admin password</label>
            <input id="password" name="password" type="password" required {login_disabled}>
            <button type="submit" {login_disabled}>Log in</button>
          </form>
          <form method="post" action="/admin/logout">
            <button type="submit">Log out</button>
          </form>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(html, status_code=status_code)


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
