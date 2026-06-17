from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse

from app.core.templates import template_context, templates


router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        template_context(request, page_title="Dashboard"),
    )
