import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.importers.libby_json import LibbyExport, LibbyParseError, parse_libby_export
from app.models import Import, ImportFile


router = APIRouter(prefix="/imports", tags=["imports"])


def safe_filename(filename: str | None) -> str:
    name = Path(filename or "libby-export.json").name.strip()
    return name or "libby-export.json"


def libby_import_dir(request: Request) -> Path:
    return Path(request.app.state.settings.imports_dir) / "libby"


def calculate_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def render_upload_page(
    request: Request,
    *,
    imports: list[Import] | None = None,
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
            imports=imports or [],
            errors=errors or [],
            success=success,
            saved_path=saved_path,
        ),
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse, dependencies=[Depends(require_write_access)])
async def import_upload_form(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    imports = db.scalars(
        select(Import)
        .where(Import.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(Import.imported_at.desc(), Import.id.desc())
    ).all()
    return render_upload_page(request, imports=list(imports))


@router.post("/libby", dependencies=[Depends(require_write_access)])
async def upload_libby_json(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Response:
    filename = safe_filename(file.filename)
    errors: list[str] = []
    parsed_export: LibbyExport | None = None

    if Path(filename).suffix.lower() != ".json":
        errors.append("Libby export must be a .json file.")

    content = await file.read()
    if not content:
        errors.append("Libby export file is empty.")

    try:
        parsed_json = json.loads(content.decode("utf-8"))
        parsed_export = parse_libby_export(parsed_json)
    except (UnicodeDecodeError, json.JSONDecodeError):
        errors.append("Uploaded file must contain valid JSON.")
    except LibbyParseError as exc:
        errors.append(str(exc))

    if errors:
        return render_upload_page(
            request,
            errors=errors,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    checksum = calculate_checksum(content)
    existing_import = db.scalars(
        select(Import).where(
            Import.user_id == DEFAULT_LOCAL_USER_ID,
            Import.source == "libby",
            Import.checksum == checksum,
        )
    ).first()
    if existing_import is not None:
        return RedirectResponse(
            f"/imports?{urlencode({'duplicate_import_id': existing_import.id, 'checksum': checksum})}",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    target_dir = libby_import_dir(request)
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    target_path = target_dir / f"{timestamp}-{uuid4().hex[:8]}-{filename}"
    target_path.write_bytes(content)

    import_record = Import(
        user_id=DEFAULT_LOCAL_USER_ID,
        source="libby",
        filename=filename,
        checksum=checksum,
        row_count=len(parsed_export.timeline) if parsed_export else 0,
        status="uploaded",
        summary={"raw_json_preserved": True},
        raw_file_path=target_path.as_posix(),
    )
    db.add(import_record)
    db.flush()
    db.add(
        ImportFile(
            import_id=import_record.id,
            file_path=target_path.as_posix(),
            file_size=len(content),
            content_type=file.content_type,
        )
    )
    db.commit()

    return RedirectResponse(
        f"/imports?{urlencode({'import_id': import_record.id, 'saved_path': target_path.as_posix()})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
