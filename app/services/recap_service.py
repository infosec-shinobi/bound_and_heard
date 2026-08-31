from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recap
from app.services.analytics import (
    PeriodRange,
    audiobook_seconds,
    books_completed_by_month,
    books_completed_by_period,
    format_breakdown,
    lifetime_enjoyed_seconds,
    pages_read,
    quarter_range,
    repeat_counts,
    series_activity_summary,
    top_authors,
    top_genres,
    year_range,
    _unique_completed_books,
)


class RecapAlreadyExistsError(ValueError):
    pass


@dataclass(frozen=True)
class RecapPeriod:
    period_type: str
    year: int
    quarter: int
    period: PeriodRange

    @property
    def slug(self) -> str:
        if self.period_type == "quarter":
            return f"{self.year}-q{self.quarter}"
        return str(self.year)

    @property
    def title(self) -> str:
        if self.period_type == "quarter":
            return f"Q{self.quarter} {self.year} Recap"
        return f"{self.year} Recap"


def generate_quarterly_recap(
    db: Session,
    *,
    user_id: int,
    year: int,
    quarter: int,
    output_dir: str | Path = "data/recaps",
    overwrite: bool = False,
) -> Recap:
    if quarter < 1 or quarter > 4:
        raise ValueError("quarter must be between 1 and 4")
    return generate_recap(
        db,
        user_id=user_id,
        recap_period=RecapPeriod("quarter", year, quarter, quarter_range(year, quarter)),
        output_dir=output_dir,
        overwrite=overwrite,
    )


def generate_yearly_recap(
    db: Session,
    *,
    user_id: int,
    year: int,
    output_dir: str | Path = "data/recaps",
    overwrite: bool = False,
) -> Recap:
    return generate_recap(
        db,
        user_id=user_id,
        recap_period=RecapPeriod("year", year, 0, year_range(year)),
        output_dir=output_dir,
        overwrite=overwrite,
    )


def generate_recap(
    db: Session,
    *,
    user_id: int,
    recap_period: RecapPeriod,
    output_dir: str | Path,
    overwrite: bool = False,
) -> Recap:
    existing = _existing_recap(db, user_id=user_id, recap_period=recap_period)
    if existing is not None and not overwrite:
        raise RecapAlreadyExistsError(f"{recap_period.title} already exists")

    payload = build_recap_payload(db, user_id=user_id, recap_period=recap_period)
    output_path = _write_recap_artifact(payload, output_dir=output_dir, recap_period=recap_period)
    generated_at = datetime.now(timezone.utc)

    if existing is None:
        recap = Recap(
            user_id=user_id,
            period_type=recap_period.period_type,
            year=recap_period.year,
            quarter=recap_period.quarter,
            generated_at=generated_at,
            title=recap_period.title,
            summary=payload["summary"],
            output_path=output_path,
            payload=payload,
        )
        db.add(recap)
    else:
        recap = existing
        recap.generated_at = generated_at
        recap.title = recap_period.title
        recap.summary = payload["summary"]
        recap.output_path = output_path
        recap.payload = payload
    db.flush()
    return recap


def build_recap_payload(db: Session, *, user_id: int, recap_period: RecapPeriod) -> dict[str, object]:
    completed_count = books_completed_by_period(db, user_id=user_id, period=recap_period.period)
    authors = top_authors(db, user_id=user_id, period=recap_period.period, limit=5)
    genres = top_genres(db, user_id=user_id, period=recap_period.period, limit=5)
    series_summary = series_activity_summary(db, user_id=user_id, period=recap_period.period, limit=5)
    repeats = repeat_counts(db, user_id=user_id, period=recap_period.period)
    months = books_completed_by_month(db, user_id=user_id, year=recap_period.year)
    period_months = [item for item in months if recap_period.period.contains(datetime(item.year, item.month, 1).date())]
    most_active_month = max(period_months, key=lambda item: (item.count, -item.month), default=None)
    longest_book = _longest_completed_book(db, user_id=user_id, period=recap_period.period)

    summary = f"{recap_period.title}: {completed_count} completed book(s)."
    return {
        "period": {
            "type": recap_period.period_type,
            "year": recap_period.year,
            "quarter": recap_period.quarter if recap_period.period_type == "quarter" else None,
            "start": recap_period.period.start.isoformat() if recap_period.period.start else None,
            "end": recap_period.period.end.isoformat() if recap_period.period.end else None,
        },
        "title": recap_period.title,
        "summary": summary,
        "completed_count": completed_count,
        "format_breakdown": format_breakdown(db, user_id=user_id, period=recap_period.period),
        "favorite_authors": [{"label": item.label, "count": item.count} for item in authors],
        "favorite_genres": [{"label": item.label, "count": item.count} for item in genres],
        "favorite_series": [
            {"id": item.series_id, "name": item.name, "completed_entries": item.completed_entries}
            for item in series_summary.most_active_series
        ],
        "series_progress": {
            "total_series": series_summary.total_series,
            "completed_series_entries": series_summary.completed_series_entries,
            "active_series_count": series_summary.active_series_count,
            "planned_entries": series_summary.planned_entries,
            "collection_range_entries": series_summary.collection_range_entries,
            "collection_covered_positions": series_summary.collection_covered_positions,
        },
        "longest_book": longest_book,
        "most_active_month": None
        if most_active_month is None
        else {"year": most_active_month.year, "month": most_active_month.month, "count": most_active_month.count},
        "pages_read": pages_read(db, user_id=user_id, period=recap_period.period),
        "audiobook_seconds": audiobook_seconds(db, user_id=user_id, period=recap_period.period),
        "lifetime_enjoyed_seconds": lifetime_enjoyed_seconds(db, user_id=user_id),
        "repeats": {
            "rereads": repeats.rereads,
            "relistens": repeats.relistens,
            "repeat_completions": repeats.repeat_completions,
            "likely_relistens": repeats.likely_relistens,
        },
    }


def _existing_recap(db: Session, *, user_id: int, recap_period: RecapPeriod) -> Recap | None:
    return db.scalar(
        select(Recap).where(
            Recap.user_id == user_id,
            Recap.period_type == recap_period.period_type,
            Recap.year == recap_period.year,
            Recap.quarter == recap_period.quarter,
        )
    )


def _write_recap_artifact(payload: dict[str, object], *, output_dir: str | Path, recap_period: RecapPeriod) -> str:
    directory = Path(output_dir) / recap_period.period_type
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{recap_period.slug}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return str(path)


def _longest_completed_book(db: Session, *, user_id: int, period: PeriodRange) -> dict[str, object] | None:
    candidates = []
    for completed in _unique_completed_books(db, user_id=user_id, period=period):
        book = completed.book
        if book.format == "audiobook" and book.audio_seconds is not None:
            candidates.append((book.audio_seconds, book.title.casefold(), book, "seconds", book.audio_seconds))
        elif book.page_count is not None:
            candidates.append((book.page_count, book.title.casefold(), book, "pages", book.page_count))
    if not candidates:
        return None
    _, _, book, metric, value = max(candidates, key=lambda item: (item[0], item[1]))
    return {"id": book.id, "title": book.title, "author": book.primary_author_name, "metric": metric, "value": value}
