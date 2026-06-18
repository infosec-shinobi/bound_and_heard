from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload
from starlette.responses import HTMLResponse

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import get_db
from app.core.templates import template_context, templates
from app.core.write_protection import require_write_access
from app.models import Book


router = APIRouter(prefix="/books", tags=["books"])


def apply_book_filters(
    statement: Select[tuple[Book]],
    *,
    q: str | None,
    status: str | None,
    book_format: str | None,
    include_archived: bool,
) -> Select[tuple[Book]]:
    if not include_archived:
        statement = statement.where(Book.archived_at.is_(None))

    if q:
        search = f"%{q.strip()}%"
        statement = statement.where(
            or_(
                Book.title.ilike(search),
                Book.subtitle.ilike(search),
                Book.primary_author_name.ilike(search),
            )
        )

    if status:
        statement = statement.where(Book.status == status)

    if book_format:
        statement = statement.where(Book.format == book_format)

    return statement


@router.get("", response_class=HTMLResponse)
async def book_list(
    request: Request,
    db: Session = Depends(get_db),
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    format: str | None = Query(default=None),
    include_archived: bool = Query(default=False),
) -> HTMLResponse:
    statement = (
        select(Book)
        .options(joinedload(Book.progress))
        .where(Book.user_id == DEFAULT_LOCAL_USER_ID)
        .order_by(Book.title.asc())
    )
    statement = apply_book_filters(
        statement,
        q=q,
        status=status,
        book_format=format,
        include_archived=include_archived,
    )
    books = db.scalars(statement).unique().all()

    return templates.TemplateResponse(
        request,
        "books/list.html",
        template_context(
            request,
            page_title="Books",
            books=books,
            q=q or "",
            selected_status=status or "",
            selected_format=format or "",
            include_archived=include_archived,
        ),
    )


@router.get("/new", response_class=HTMLResponse)
async def new_book_placeholder(
    request: Request,
    _: None = Depends(require_write_access),
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "books/new_placeholder.html",
        template_context(request, page_title="Add Book"),
        status_code=501,
    )
