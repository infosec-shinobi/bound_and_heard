from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.bootstrap import DEFAULT_LOCAL_USER_ID
from app.core.database import Base
from app.models import Book, Series, SeriesBook, User
from app.services.libby_series import (
    apply_libby_series_population,
    build_libby_series_population_preview,
    parse_libby_series_page,
    preserve_libby_series_snapshot,
)


FIXTURE_PATH = Path(__file__).parent.parent / "data" / "scraped" / "scraped_series_lbby_reacher.html"


def make_session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with SessionLocal() as db:
        db.add(User(id=DEFAULT_LOCAL_USER_ID, display_name="Local User"))
        db.commit()
    return SessionLocal


def add_series(db: Session, name: str = "Jack Reacher") -> Series:
    series = Series(user_id=DEFAULT_LOCAL_USER_ID, name=name, status="active", wants_to_continue="yes")
    db.add(series)
    db.flush()
    return series


def add_book(
    db: Session,
    *,
    title: str,
    author: str | None,
    book_format: str = "ebook",
    libby_title_id: str | None = None,
) -> Book:
    book = Book(
        user_id=DEFAULT_LOCAL_USER_ID,
        title=title,
        primary_author_name=author,
        format=book_format,
        status="want_to_read",
        libby_title_id=libby_title_id,
    )
    db.add(book)
    db.flush()
    return book


def test_parse_libby_series_page_fixture_entries() -> None:
    page = parse_libby_series_page(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert page.series_name == "Jack Reacher"
    assert page.libby_series_key == "series-503231"
    assert len(page.entries) >= 40
    first = page.entries[0]
    assert first.title == "Killing Floor"
    assert first.author == "Lee Child"
    assert first.format == "ebook"
    assert first.position == 1
    assert first.libby_title_id == "203736"
    assert first.libby_title_url == "https://libbyapp.com/shelf/series-503231/page-1/203736"
    assert any(entry.title == "Second Son" and entry.position == 15.5 for entry in page.entries)
    assert any(
        entry.title == "Jack Reacher, Books 1-6" and entry.position == 1 and entry.position_end == 6
        for entry in page.entries
    )


def test_parse_libby_series_page_collection_range() -> None:
    html = """
    <div class="title-tile data-title-tile-format_book data-title_583009">
      <button class="series-number">1-3 in series</button>
      <div class="title-tile-author">Brad Thor</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-1/page-1/583009"><span class="title-tile-title">Brad Thor Collectors' Edition 1</span></a>
    </div>
    """

    page = parse_libby_series_page(html)

    assert page.entries[0].position == 1
    assert page.entries[0].position_end == 3
    assert page.entries[0].raw_position_label == "1-3 in series"


def test_preview_matches_libby_title_id_before_title_author() -> None:
    session_factory = make_session_factory()
    html = '<div class="title-tile data-title-tile-format_book data-title_203736"><button class="series-number">#1 in series</button><h3><div class="title-tile-author">Wrong Author</div><a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/203736" aria-label="Book: Wrong Title, by Wrong Author"><span class="title-tile-title">Wrong Title</span></a></h3></div>'
    with session_factory() as db:
        series = add_series(db)
        book = add_book(db, title="Killing Floor", author="Lee Child", libby_title_id="203736")
        db.commit()

        preview = build_libby_series_population_preview(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=html,
            include_unmatched=False,
        )

    assert preview.add_book_count == 1
    assert preview.items[0].matched_book is not None
    assert preview.items[0].matched_book.id == book.id


def test_apply_adds_matched_books_and_optional_planned_entries_without_duplicates() -> None:
    session_factory = make_session_factory()
    html = """
    <div class="title-tile data-title-tile-format_book data-title_203736">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/203736"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    <div class="title-tile data-title-tile-format_book data-title_213622">
      <button class="series-number">#2 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/213622"><span class="title-tile-title">Die Trying</span></a>
    </div>
    """
    with session_factory() as db:
        series = add_series(db)
        book = add_book(db, title="Killing Floor", author="Lee Child", libby_title_id="203736")
        db.add(
            SeriesBook(
                series_id=series.id,
                position=2,
                planned_title="Die Trying",
                planned_author_name="Lee Child",
                planned_format="ebook",
                notes="Manual note",
            )
        )
        db.commit()

        result = apply_libby_series_population(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=html,
            include_unmatched=True,
        )
        db.commit()

        entries = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id).order_by(SeriesBook.position)).all()

    assert result.added_books == 1
    assert result.added_planned == 0
    assert result.skipped == 1
    assert len(entries) == 2
    assert entries[0].book_id == book.id
    assert entries[0].position == 1
    assert entries[1].planned_title == "Die Trying"
    assert entries[1].notes == "Manual note"


def test_apply_preserves_existing_book_assignment_position() -> None:
    session_factory = make_session_factory()
    html = '<div class="title-tile data-title-tile-format_book data-title_203736"><button class="series-number">#1 in series</button><div class="title-tile-author">Lee Child</div><a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/203736"><span class="title-tile-title">Killing Floor</span></a></div>'
    with session_factory() as db:
        series = add_series(db)
        book = add_book(db, title="Killing Floor", author="Lee Child", libby_title_id="203736")
        db.add(SeriesBook(series_id=series.id, book_id=book.id, position=99))
        db.commit()

        result = apply_libby_series_population(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=html,
            include_unmatched=False,
        )
        db.commit()
        entry = db.scalars(select(SeriesBook).where(SeriesBook.series_id == series.id)).one()

    assert result.added_books == 0
    assert result.skipped == 1
    assert entry.position == 99


def test_preview_collapses_ebook_and_audiobook_rows_to_unique_work() -> None:
    session_factory = make_session_factory()
    html = """
    <div class="title-tile data-title-tile-format_book data-title_111">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/111"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    <div class="title-tile data-title-tile-format_audiobook data-title_222">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/222"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    """
    with session_factory() as db:
        series = add_series(db)
        db.commit()

        preview = build_libby_series_population_preview(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=html,
            include_unmatched=True,
        )

    assert len(preview.page.entries) == 1
    assert preview.planned_count == 1
    assert preview.items[0].entry.title == "Killing Floor"
    assert preview.items[0].entry.format == "unknown"
    assert preview.items[0].entry.available_formats == ("audiobook", "ebook")
    assert preview.items[0].entry.display_format == "Audiobook, Ebook"


def test_fixture_preview_shows_mixed_formats_for_unique_work() -> None:
    session_factory = make_session_factory()
    with session_factory() as db:
        series = add_series(db)
        db.commit()

        preview = build_libby_series_population_preview(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=FIXTURE_PATH.read_text(encoding="utf-8"),
            include_unmatched=False,
        )

    killing_floor = next(item.entry for item in preview.items if item.entry.title == "Killing Floor")
    assert killing_floor.available_formats == ("audiobook", "ebook")
    assert killing_floor.display_format == "Audiobook, Ebook"


def test_preview_matches_single_local_book_without_requiring_same_format() -> None:
    session_factory = make_session_factory()
    html = """
    <div class="title-tile data-title-tile-format_book data-title_111">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/111"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    """
    with session_factory() as db:
        series = add_series(db)
        book = add_book(db, title="Killing Floor", author="Lee Child", book_format="audiobook")
        db.commit()

        preview = build_libby_series_population_preview(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=html,
            include_unmatched=False,
        )

    assert preview.add_book_count == 1
    assert preview.items[0].matched_book is not None
    assert preview.items[0].matched_book.id == book.id


def test_preview_skips_ambiguous_multi_format_local_matches() -> None:
    session_factory = make_session_factory()
    html = """
    <div class="title-tile data-title-tile-format_book data-title_111">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/111"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    """
    with session_factory() as db:
        series = add_series(db)
        add_book(db, title="Killing Floor", author="Lee Child", book_format="ebook")
        add_book(db, title="Killing Floor", author="Lee Child", book_format="audiobook")
        db.commit()

        preview = build_libby_series_population_preview(
            db,
            user_id=DEFAULT_LOCAL_USER_ID,
            series_id=series.id,
            content=html,
            include_unmatched=False,
        )

    assert preview.add_book_count == 0
    assert preview.skip_count == 1
    assert preview.items[0].reason == "No local book matched"


def test_preserved_snapshot_counts_unique_works_not_raw_format_rows(tmp_path: Path) -> None:
    session_factory = make_session_factory()
    html = """
    <div class="title-tile data-title-tile-format_book data-title_111">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/111"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    <div class="title-tile data-title-tile-format_audiobook data-title_222">
      <button class="series-number">#1 in series</button>
      <div class="title-tile-author">Lee Child</div>
      <a class="title-tile-action" href="https://libbyapp.com/shelf/series-503231/page-1/222"><span class="title-tile-title">Killing Floor</span></a>
    </div>
    """
    with session_factory() as db:
        series = add_series(db)
        preserved = preserve_libby_series_snapshot(
            db,
            series=series,
            base_dir=tmp_path.as_posix(),
            libby_series_url="https://libbyapp.com/shelf/series-503231/page-1",
            content=html,
        )

    assert preserved.snapshot.parsed_entry_count == 1
    assert preserved.snapshot.raw_data is not None
    assert preserved.snapshot.raw_data["raw_tile_count"] == 2
