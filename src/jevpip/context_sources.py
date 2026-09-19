from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import re
from zoneinfo import ZoneInfo

import httpx

from jevpip.context import ContextRisk, ExternalContextItem

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/"
_BLS_TZ = ZoneInfo("America/New_York")

_HIGH_RELEASES = (
    "consumer price index",
    "producer price index",
    "employment situation",
)
_MEDIUM_RELEASES = (
    "job openings and labor turnover",
    "employment cost index",
    "productivity and costs",
    "u.s. import and export price indexes",
)


def _unfold_ical(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape_ical(value: str) -> str:
    return (
        value.replace("\\n", "\n")
        .replace("\\N", "\n")
        .replace("\\,", ",")
        .replace("\\;", ";")
        .replace("\\\\", "\\")
        .strip()
    )


def _property(line: str) -> tuple[str, dict[str, str], str]:
    head, sep, value = line.partition(":")
    if not sep:
        return head.upper(), {}, ""
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for part in parts[1:]:
        key, equals, raw = part.partition("=")
        if equals:
            params[key.upper()] = raw.strip('"')
    return name, params, value


def _parse_datetime(value: str, params: dict[str, str]) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", raw):
        return None

    if raw.endswith("Z"):
        parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ")
        return parsed.replace(tzinfo=timezone.utc)

    fmt = "%Y%m%dT%H%M%S" if len(raw) >= 15 else "%Y%m%dT%H%M"
    parsed = datetime.strptime(raw[:15] if fmt.endswith("%S") else raw[:13], fmt)
    tzid = params.get("TZID")
    zone = ZoneInfo(tzid) if tzid else _BLS_TZ
    return parsed.replace(tzinfo=zone).astimezone(timezone.utc)


def bls_risk(summary: str) -> ContextRisk:
    normalized = " ".join(summary.lower().split())
    if any(name in normalized for name in _HIGH_RELEASES):
        return "high"
    if any(name in normalized for name in _MEDIUM_RELEASES):
        return "medium"
    return "low"


def parse_bls_ics(
    text: str,
    *,
    observed_at: datetime,
    source_url: str = BLS_SCHEDULE_URL,
) -> tuple[ExternalContextItem, ...]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    events: list[ExternalContextItem] = []
    current: dict[str, tuple[dict[str, str], str]] | None = None

    for line in _unfold_ical(text):
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            continue
        if upper == "END:VEVENT":
            if current is None:
                continue
            summary = _unescape_ical(current.get("SUMMARY", ({}, ""))[1])
            dt_params, dt_value = current.get("DTSTART", ({}, ""))
            scheduled_at = _parse_datetime(dt_value, dt_params)
            if summary and scheduled_at is not None:
                uid = _unescape_ical(current.get("UID", ({}, ""))[1])
                event_url = _unescape_ical(current.get("URL", ({}, ""))[1]) or source_url
                source_id = uid or sha256(
                    f"{summary}|{scheduled_at.isoformat()}".encode("utf-8")
                ).hexdigest()[:24]
                events.append(
                    ExternalContextItem(
                        source="bls",
                        source_id=source_id,
                        kind="scheduled_event",
                        title=summary,
                        observed_at=observed_at,
                        source_url=event_url,
                        scheduled_at=scheduled_at,
                        currencies=("USD",),
                        risk=bls_risk(summary),
                    )
                )
            current = None
            continue
        if current is None:
            continue
        name, params, value = _property(line)
        if name in {"SUMMARY", "DTSTART", "UID", "URL"}:
            current[name] = (params, value)

    return tuple(sorted(events, key=lambda item: item.scheduled_at or item.observed_at))


def fetch_bls_events(
    observed_at: datetime | None = None,
    *,
    timeout_seconds: float = 8.0,
) -> tuple[ExternalContextItem, ...]:
    observed = observed_at or datetime.now(timezone.utc)
    headers = {
        "User-Agent": "JevPip/0.1 (+https://github.com/yo4e/JevPip)",
        "Accept": "text/calendar,text/plain;q=0.9,*/*;q=0.1",
    }
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = client.get(BLS_ICS_URL)
        response.raise_for_status()
    return parse_bls_ics(response.text, observed_at=observed)
