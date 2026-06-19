from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import User


router = APIRouter(prefix="/settings", tags=["settings"])

THEMES = {"dark", "light"}


def clean_display_name(value: str) -> str:
    return value.strip()


def normalize_theme(value: str) -> str:
    return value if value in THEMES else "dark"


def get_current_user(db: Session, default_display_name: str) -> User:
    user = db.get(User, DEFAULT_LOCAL_USER_ID)
    if user is None:
        user = User(id=DEFAULT_LOCAL_USER_ID, display_name=default_display_name)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def render_profile_page(
    request: Request,
    user: User,
    *,
    errors: list[str] | None = None,
    success: str | None = None,
    selected_theme: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "settings/profile.html",
        template_context(
            request,
            page_title="Settings",
            user=user,
            selected_theme=selected_theme or normalize_theme(request.cookies.get("theme", "dark")),
            errors=errors or [],
            success=success,
        ),
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def profile_settings(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    user = get_current_user(db, request.app.state.settings.default_user_name)
    return render_profile_page(request, user)


@router.post("", dependencies=[Depends(require_write_access)])
async def update_profile_settings(
    request: Request,
    display_name: str = Form(...),
    theme: str = Form("dark"),
    db: Session = Depends(get_db),
) -> Response:
    user = get_current_user(db, request.app.state.settings.default_user_name)
    cleaned_name = clean_display_name(display_name)
    selected_theme = normalize_theme(theme)
    errors: list[str] = []

    if not cleaned_name:
        errors.append("Display name is required.")
    if len(cleaned_name) > 200:
        errors.append("Display name must be 200 characters or fewer.")

    if errors:
        user.display_name = display_name
        response = render_profile_page(
            request,
            user,
            errors=errors,
            selected_theme=selected_theme,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        response.set_cookie("theme", selected_theme, samesite="lax")
        return response

    user.display_name = cleaned_name
    db.commit()

    response = RedirectResponse("/settings", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("theme", selected_theme, samesite="lax")
    return response
