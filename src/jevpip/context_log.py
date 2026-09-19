from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from jevpip.context import ExternalContextItem
from jevpip.storage.jsonl import append_jsonl


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("context log timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def context_item_record(item: ExternalContextItem) -> dict[str, object]:
    """Serialize bounded provenance metadata, never raw article/calendar bodies."""

    return {
        "source": item.source,
        "source_id": item.source_id,
        "kind": item.kind,
        "title": item.title,
        "source_url": item.source_url,
        "observed_at": _utc(item.observed_at),
        "scheduled_at": _utc(item.scheduled_at),
        "published_at": _utc(item.published_at),
        "expires_at": _utc(item.expires_at),
        "currencies": list(item.currencies),
        "instruments": list(item.instruments),
        "risk": item.risk,
    }


def append_context_fetch(
    data_dir: Path,
    *,
    source: str,
    observed_at: datetime,
    events: Iterable[ExternalContextItem] = (),
    error: str | None = None,
) -> Path:
    """Append one source fetch observation so historical knowledge is reconstructable."""

    observed = observed_at.astimezone(timezone.utc)
    path = data_dir / "context" / source / f"{observed.date().isoformat()}.jsonl"
    event_records = [context_item_record(item) for item in events]
    append_jsonl(
        path,
        {
            "kind": "external_context_fetch",
            "source": source,
            "observed_at": observed.isoformat(),
            "status": "error" if error else "ok",
            "error": error,
            "event_count": len(event_records),
            "events": event_records,
        },
    )
    return path
