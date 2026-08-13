from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import ScrapeJobItem, ScrapeSnapshot
from app.scrapers.libby_progress import LibbyProgressParseResult


@dataclass(frozen=True)
class PreservedSnapshot:
    snapshot: ScrapeSnapshot
    content: bytes


def snapshot_extension(snapshot_type: str, content_type: str | None) -> str:
    if snapshot_type == "html" or content_type == "text/html":
        return ".html"
    if snapshot_type == "text" or (content_type and content_type.startswith("text/")):
        return ".txt"
    if snapshot_type == "json" or content_type == "application/json":
        return ".json"
    return ".bin"


def snapshot_checksum(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def preserve_scrape_snapshot(
    db: Session,
    *,
    item: ScrapeJobItem,
    base_dir: str,
    snapshot_type: str,
    content: str | bytes,
    content_type: str | None = None,
    raw_data: dict | None = None,
    parsed_progress: LibbyProgressParseResult | None = None,
) -> PreservedSnapshot:
    content_bytes = content.encode("utf-8") if isinstance(content, str) else content
    checksum = snapshot_checksum(content_bytes)
    extension = snapshot_extension(snapshot_type, content_type)
    captured_at = datetime.now(timezone.utc)
    target_dir = Path(base_dir) / "libby" / f"job-{item.job_id}" / f"item-{item.id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{captured_at.strftime('%Y%m%d%H%M%S')}-{snapshot_type}-{checksum[:12]}{extension}"
    target_path.write_bytes(content_bytes)

    snapshot = ScrapeSnapshot(
        item_id=item.id,
        snapshot_type=snapshot_type,
        file_path=target_path.as_posix(),
        checksum=checksum,
        content_type=content_type,
        progress_percent=parsed_progress.progress_percent if parsed_progress else None,
        raw_data={**(raw_data or {}), "parsed_progress": parsed_progress.as_snapshot_raw_data()}
        if parsed_progress
        else raw_data,
    )
    db.add(snapshot)
    return PreservedSnapshot(snapshot=snapshot, content=content_bytes)
