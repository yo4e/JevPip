from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal

ContextKind = Literal["scheduled_event", "official_release", "official_news"]
ContextRisk = Literal["low", "medium", "high", "critical"]


def _require_aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ExternalContextItem:
    """Small, provenance-first context item safe to pass toward a supervisor.

    Raw article/release bodies intentionally do not live here. The public model is
    limited to timestamps, source identity, tags, and a short source-provided or
    locally-normalized title.
    """

    source: str
    source_id: str
    kind: ContextKind
    title: str
    observed_at: datetime
    source_url: str
    scheduled_at: datetime | None = None
    published_at: datetime | None = None
    expires_at: datetime | None = None
    currencies: tuple[str, ...] = ()
    instruments: tuple[str, ...] = ()
    risk: ContextRisk = "medium"

    def __post_init__(self) -> None:
        if not self.source.strip():
            raise ValueError("source is required")
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if not self.title.strip():
            raise ValueError("title is required")
        if not self.source_url.strip():
            raise ValueError("source_url is required")

        _require_aware(self.observed_at, "observed_at")
        if self.scheduled_at is not None:
            _require_aware(self.scheduled_at, "scheduled_at")
        if self.published_at is not None:
            _require_aware(self.published_at, "published_at")
        if self.expires_at is not None:
            _require_aware(self.expires_at, "expires_at")

        if self.kind == "scheduled_event" and self.scheduled_at is None:
            raise ValueError("scheduled_event requires scheduled_at")
        if self.kind in {"official_release", "official_news"} and self.published_at is None:
            raise ValueError(f"{self.kind} requires published_at")

    @property
    def key(self) -> tuple[str, str]:
        return self.source, self.source_id

    def known_at(self, as_of: datetime) -> bool:
        """Return whether this exact revision was knowable by as_of."""

        at = _require_aware(as_of, "as_of")
        if _require_aware(self.observed_at, "observed_at") > at:
            return False
        if self.published_at is not None and _require_aware(self.published_at, "published_at") > at:
            return False
        return True

    def relevant_to(
        self,
        *,
        instrument_id: str | None = None,
        currencies: Iterable[str] = (),
    ) -> bool:
        if not self.instruments and not self.currencies:
            return True

        if instrument_id and instrument_id in self.instruments:
            return True

        currency_set = {value.upper() for value in currencies}
        return bool(currency_set.intersection(value.upper() for value in self.currencies))

    def active_at(
        self,
        as_of: datetime,
        *,
        lead: timedelta = timedelta(minutes=60),
        lag: timedelta = timedelta(minutes=30),
    ) -> bool:
        """Return whether the item is inside the decision-time context window."""

        at = _require_aware(as_of, "as_of")
        if not self.known_at(at):
            return False

        if self.kind == "scheduled_event":
            assert self.scheduled_at is not None
            event_at = _require_aware(self.scheduled_at, "scheduled_at")
            return event_at - lead <= at <= event_at + lag

        assert self.published_at is not None
        if self.expires_at is not None and at > _require_aware(self.expires_at, "expires_at"):
            return False
        return _require_aware(self.published_at, "published_at") <= at


def select_context(
    items: Iterable[ExternalContextItem],
    *,
    as_of: datetime,
    instrument_id: str | None = None,
    currencies: Iterable[str] = (),
    lead: timedelta = timedelta(minutes=60),
    lag: timedelta = timedelta(minutes=30),
) -> tuple[ExternalContextItem, ...]:
    """Select latest knowable revisions without leaking future information.

    If a source revises the same source_id, only the latest revision observed on
    or before as_of is used. A later revision can therefore never rewrite a
    historical decision.
    """

    at = _require_aware(as_of, "as_of")
    latest: dict[tuple[str, str], ExternalContextItem] = {}

    for item in items:
        if not item.known_at(at):
            continue
        if not item.relevant_to(instrument_id=instrument_id, currencies=currencies):
            continue
        current = latest.get(item.key)
        if current is None or _require_aware(item.observed_at, "observed_at") > _require_aware(
            current.observed_at, "observed_at"
        ):
            latest[item.key] = item

    selected = [
        item
        for item in latest.values()
        if item.active_at(at, lead=lead, lag=lag)
    ]

    def sort_key(item: ExternalContextItem) -> datetime:
        return _require_aware(
            item.scheduled_at or item.published_at or item.observed_at,
            "context_time",
        )

    return tuple(sorted(selected, key=sort_key))


def to_jev_context_state(
    items: Iterable[ExternalContextItem],
    *,
    as_of: datetime,
) -> dict[str, object]:
    """Create the bounded, provenance-carrying context fragment for Jev."""

    at = _require_aware(as_of, "as_of")
    packed: list[dict[str, object]] = []

    for item in items:
        event_at = item.scheduled_at or item.published_at
        assert event_at is not None
        event_utc = _require_aware(event_at, "event_at")
        packed.append(
            {
                "kind": item.kind,
                "source": item.source,
                "source_id": item.source_id,
                "title": item.title,
                "source_url": item.source_url,
                "risk": item.risk,
                "currencies": list(item.currencies),
                "instruments": list(item.instruments),
                "event_at": event_utc.isoformat(),
                "seconds_from_now": int((event_utc - at).total_seconds()),
                "observed_at": _require_aware(item.observed_at, "observed_at").isoformat(),
            }
        )

    return {
        "as_of": at.isoformat(),
        "external_context": packed,
    }
