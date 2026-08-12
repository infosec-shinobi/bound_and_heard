from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse, Response
from starlette.responses import HTMLResponse

from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.services.libby_browser import LibbyBrowserError, open_libby_browser_session


router = APIRouter(prefix="/scraping", tags=["scraping"])


@router.get("/libby/session", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def libby_session_page(
    request: Request,
    launched: bool = False,
    error: str | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "scraping/libby_session.html",
        template_context(
            request,
            page_title="Libby Browser Session",
            profile_dir=request.app.state.settings.libby_browser_profile_dir,
            launched=launched,
            error=error,
        ),
    )


@router.post("/libby/session/open", dependencies=[Depends(require_write_access)])
async def open_libby_session(request: Request) -> Response:
    try:
        open_libby_browser_session(request.app.state.settings.libby_browser_profile_dir)
    except LibbyBrowserError as exc:
        query = urlencode({"error": str(exc)})
        return RedirectResponse(
            f"/scraping/libby/session?{query}",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    return RedirectResponse("/scraping/libby/session?launched=true", status_code=status.HTTP_303_SEE_OTHER)
