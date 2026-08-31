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


def export_recap_markdown(recap: Recap, *, output_dir: str | Path = "data/exports") -> str:
    directory = Path(output_dir) / "recaps" / recap.period_type
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{_recap_slug(recap)}.md"
    path.write_text(_recap_markdown(recap), encoding="utf-8")
    return str(path)


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


def _recap_slug(recap: Recap) -> str:
    if recap.period_type == "quarter":
        return f"{recap.year}-q{recap.quarter}"
    return str(recap.year)


def _recap_markdown(recap: Recap) -> str:
    payload = recap.payload or {}
    lines = [
        f"# {recap.title}",
        "",
        f"Generated: {recap.generated_at.isoformat()}",
        f"Period: {_recap_period_label(recap)}",
        f"Source artifact: {recap.output_path}",
        "",
        recap.summary,
        "",
        "## Totals",
        "",
        f"- Books completed: {payload.get('completed_count', 'Not available')}",
        f"- Pages read: {payload.get('pages_read', 'Not available')}",
        f"- Audiobook seconds: {payload.get('audiobook_seconds', 'Not available')}",
        f"- Lifetime enjoyed seconds: {payload.get('lifetime_enjoyed_seconds', 'Not available')}",
        "",
        "## Favorites",
        "",
        f"- Favorite author: {_first_label(payload.get('favorite_authors'))}",
        f"- Favorite genre: {_first_label(payload.get('favorite_genres'))}",
        f"- Favorite series: {_first_name(payload.get('favorite_series'))}",
        "",
        "## Highlights",
        "",
        f"- Longest book: {_longest_book_label(payload.get('longest_book'))}",
        f"- Most active month: {_month_label(payload.get('most_active_month'))}",
        "",
        "## Format Mix",
        "",
    ]
    format_breakdown = payload.get("format_breakdown")
    if isinstance(format_breakdown, dict) and format_breakdown:
        lines.extend(f"- {label}: {count}" for label, count in sorted(format_breakdown.items()))
    else:
        lines.append("- Not available")
    repeats = payload.get("repeats") if isinstance(payload.get("repeats"), dict) else {}
    series_progress = payload.get("series_progress") if isinstance(payload.get("series_progress"), dict) else {}
    lines.extend(
        [
            "",
            "## Repeats",
            "",
            f"- Re-reads: {repeats.get('rereads', 0)}",
            f"- Re-listens: {repeats.get('relistens', 0)}",
            f"- Likely re-listens: {repeats.get('likely_relistens', 0)} (estimated)",
            "",
            "## Series Progress",
            "",
            f"- Active series: {series_progress.get('active_series_count', 0)}",
            f"- Completed series entries: {series_progress.get('completed_series_entries', 0)}",
            f"- Planned entries: {series_progress.get('planned_entries', 0)}",
            f"- Collection ranges: {series_progress.get('collection_range_entries', 0)}",
            "",
        ]
    )
    return "\n".join(str(line) for line in lines)


def _recap_period_label(recap: Recap) -> str:
    if recap.period_type == "quarter":
        return f"Q{recap.quarter} {recap.year}"
    return str(recap.year)


def _first_label(value: object) -> str:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0].get("label") or "Not available")
    return "Not available"


def _first_name(value: object) -> str:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0].get("name") or "Not available")
    return "Not available"


def _longest_book_label(value: object) -> str:
    if not isinstance(value, dict):
        return "Not available"
    title = value.get("title") or "Unknown title"
    metric = value.get("metric") or "value"
    metric_value = value.get("value") or "Not available"
    return f"{title} ({metric_value} {metric})"


def _month_label(value: object) -> str:
    if not isinstance(value, dict):
        return "Not available"
    year = value.get("year")
    month = value.get("month")
    count = value.get("count")
    if not isinstance(year, int) or not isinstance(month, int):
        return "Not available"
    return f"{year}-{month:02d} ({count} completed)"


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
