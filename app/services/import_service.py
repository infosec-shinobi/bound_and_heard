from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.importers.libby_json import LibbyTimelineItem, build_libby_source_event_id
from app.models import ReadingEvent


@dataclass(frozen=True)
class LibbyEventResult:
    event: ReadingEvent
    created: bool


def create_libby_reading_event(
    db: Session,
    *,
    user_id: int,
    book_id: int,
    item: LibbyTimelineItem,
    event_type: str,
) -> LibbyEventResult:
    if item.timestamp is None:
        raise ValueError("Libby timeline item must include a timestamp to create a reading event.")

    source_event_id = build_libby_source_event_id(item)
    existing_event = db.scalars(
        select(ReadingEvent).where(
            ReadingEvent.user_id == user_id,
            ReadingEvent.source == "libby",
            ReadingEvent.source_event_id == source_event_id,
        )
    ).first()
    if existing_event is not None:
        return LibbyEventResult(event=existing_event, created=False)

    event = ReadingEvent(
        user_id=user_id,
        book_id=book_id,
        source="libby",
        source_event_id=source_event_id,
        event_type=event_type,
        event_date=item.timestamp,
        raw_data={"libby": item.raw_item},
    )
    db.add(event)
    db.flush()
    return LibbyEventResult(event=event, created=True)
