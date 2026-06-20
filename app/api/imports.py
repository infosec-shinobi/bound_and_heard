import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from starlette.responses import HTMLResponse

from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access


router = APIRouter(prefix="/imports", tags=["imports"])


def safe_filename(filename: str | None) -> str:
    name = Path(filename or "libby-export.json").name.strip()
    return name or "libby-export.json"


def libby_import_dir(request: Request) -> Path:
    return Path(request.app.state.settings.imports_dir) / "libby"


def render_upload_page(
    request: Request,
    *,
    errors: list[str] | None = None,
    success: str | None = None,
    saved_path: str | None = None,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "imports/libby_upload.html",
        template_context(
            request,
            page_title="Imports",
            errors=errors or [],
            success=success,
            saved_path=saved_path,
        ),
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def import_upload_form(request: Request) -> HTMLResponse:
    return render_upload_page(request)


@router.post("/libby", dependencies=[Depends(require_write_access)])
async def upload_libby_json(request: Request, file: UploadFile = File(...)) -> Response:
    filename = safe_filename(file.filename)
    errors: list[str] = []

    if Path(filename).suffix.lower() != ".json":
        errors.append("Libby export must be a .json file.")

    content = await file.read()
    if not content:
        errors.append("Libby export file is empty.")

    try:
        json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append("Uploaded file must contain valid JSON.")

    if errors:
        return render_upload_page(
            request,
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    target_dir = libby_import_dir(request)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target_path = target_dir / f"{timestamp}-{uuid4().hex[:8]}-{filename}"
    target_path.write_bytes(content)

    return RedirectResponse(
        f"/imports?saved_path={target_path.as_posix()}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
