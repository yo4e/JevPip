from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import re
from zoneinfo import ZoneInfo

import httpx

from jevpip.context import ContextRisk, ExternalContextItem

BLS_ICS_URL = "https://www.bls.gov/schedule/news_release/bls.ics"
BLS_SCHEDULE_URL = "https://www.bls.gov/schedule/"
BLS_MONTHLY_LIST_URL = "https://www.bls.gov/schedule/{year}/{month:02d}_sched_list.htm"
BOJ_MPM_URL = "https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm"
FED_FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
_BLS_TZ = ZoneInfo("America/New_York")
_BOJ_TZ = ZoneInfo("Asia/Tokyo")
_FED_TZ = ZoneInfo("America/New_York")
_TZ_ALIASES = {
    "Eastern Standard Time": "America/New_York",
    "US/Eastern": "America/New_York",
}

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
    if tzid:
        zone = ZoneInfo(_TZ_ALIASES.get(tzid, tzid))
    else:
        zone = _BLS_TZ
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


class _BLSListParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._row: list[str] | None = None
        self._in_cell = False
        self._cell_parts: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            if self._row is not None:
                self._row.append(" ".join(" ".join(self._cell_parts).split()))
            self._in_cell = False
        elif tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


def parse_bls_schedule_html(
    html: str,
    *,
    observed_at: datetime,
    source_url: str,
) -> tuple[ExternalContextItem, ...]:
    """Parse the official BLS monthly list view used as an ICS fallback."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    parser = _BLSListParser()
    parser.feed(html)
    events: list[ExternalContextItem] = []

    for row in parser.rows:
        if len(row) < 3:
            continue
        date_text = row[0].strip()
        time_text = row[1].strip()
        title = " ".join(row[2:]).strip()
        if not date_text or not time_text or not title:
            continue
        try:
            local_date = datetime.strptime(date_text, "%A, %B %d, %Y").date()
            local_time = datetime.strptime(time_text, "%I:%M %p").time()
        except ValueError:
            continue

        local_at = datetime.combine(local_date, local_time, tzinfo=_BLS_TZ)
        scheduled_at = local_at.astimezone(timezone.utc)
        source_id = "schedule-" + sha256(
            f"{title}|{scheduled_at.isoformat()}".encode("utf-8")
        ).hexdigest()[:24]
        events.append(
            ExternalContextItem(
                source="bls",
                source_id=source_id,
                kind="scheduled_event",
                title=title,
                observed_at=observed_at,
                source_url=source_url,
                scheduled_at=scheduled_at,
                currencies=("USD",),
                risk=bls_risk(title),
            )
        )

    unique = {item.key: item for item in events}
    return tuple(
        sorted(unique.values(), key=lambda item: item.scheduled_at or item.observed_at)
    )


def _bls_month_urls(observed_at: datetime, count: int = 3) -> tuple[str, ...]:
    local = observed_at.astimezone(_BLS_TZ)
    start = local.year * 12 + local.month - 1
    urls: list[str] = []
    for offset in range(count):
        serial = start + offset
        year, month0 = divmod(serial, 12)
        urls.append(BLS_MONTHLY_LIST_URL.format(year=year, month=month0 + 1))
    return tuple(urls)


def fetch_bls_events(
    observed_at: datetime | None = None,
    *,
    timeout_seconds: float = 8.0,
) -> tuple[ExternalContextItem, ...]:
    observed = observed_at or datetime.now(timezone.utc)
    headers = {
        "User-Agent": "JevPip/0.1 (+https://github.com/yo4e/JevPip)",
        "Accept": "text/calendar,text/html;q=0.9,text/plain;q=0.8,*/*;q=0.1",
    }
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        try:
            response = client.get(BLS_ICS_URL)
            response.raise_for_status()
            return parse_bls_ics(response.text, observed_at=observed)
        except httpx.HTTPStatusError as ics_error:
            # BLS documents the ICS URL publicly, but it can return 403 to
            # programmatic clients. Fall back to BLS's own monthly list view
            # instead of dropping the source or using a third-party calendar.
            events: list[ExternalContextItem] = []
            last_error: Exception = ics_error
            for url in _bls_month_urls(observed):
                try:
                    page = client.get(url, headers={"Accept": "text/html,*/*;q=0.1"})
                    page.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    continue
                events.extend(
                    parse_bls_schedule_html(
                        page.text,
                        observed_at=observed,
                        source_url=url,
                    )
                )
            if events:
                unique = {item.key: item for item in events}
                return tuple(
                    sorted(
                        unique.values(),
                        key=lambda item: item.scheduled_at or item.observed_at,
                    )
                )
            raise last_error


_MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}


class _BOJScheduleParser(HTMLParser):
    def __init__(self, year: int) -> None:
        super().__init__()
        self.target_year = year
        self.heading_year: int | None = None
        self._in_h2 = False
        self._h2_parts: list[str] = []
        self._target_table_depth = 0
        self._in_cell = False
        self._cell_parts: list[str] = []
        self._row: list[str] | None = None
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "h2":
            self._in_h2 = True
            self._h2_parts = []
        elif tag == "table" and self.heading_year == self.target_year:
            self._target_table_depth += 1
        elif self._target_table_depth and tag == "tr":
            self._row = []
        elif self._target_table_depth and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "h2" and self._in_h2:
            text = " ".join(self._h2_parts)
            match = re.search(r"\b(20\d{2})\b", text)
            self.heading_year = int(match.group(1)) if match else None
            self._in_h2 = False
        elif self._target_table_depth and tag in {"td", "th"} and self._in_cell:
            if self._row is not None:
                self._row.append(" ".join(" ".join(self._cell_parts).split()))
            self._in_cell = False
        elif self._target_table_depth and tag == "tr":
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table" and self._target_table_depth:
            self._target_table_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_h2:
            self._h2_parts.append(data)
        if self._target_table_depth and self._in_cell:
            self._cell_parts.append(data)


def _parse_boj_date(value: str, default_year: int) -> datetime | None:
    normalized = " ".join(value.replace("\xa0", " ").split())
    if not normalized or normalized == "-":
        return None
    match = re.search(
        r"(?P<month>[A-Za-z]+)\.?\s+(?P<day>\d{1,2})"
        r"(?:\s*\([^)]*\))?"
        r"(?:,?\s*(?P<year>20\d{2}))?",
        normalized,
    )
    if not match:
        return None
    month_name = match.group("month").lower().rstrip(".")
    month = _MONTHS.get(month_name)
    if month is None:
        return None
    year = int(match.group("year") or default_year)
    day = int(match.group("day"))
    return datetime(year, month, day, 8, 50, tzinfo=_BOJ_TZ).astimezone(timezone.utc)


def parse_boj_mpm_html(
    html: str,
    *,
    observed_at: datetime,
    year: int,
    source_url: str = BOJ_MPM_URL,
) -> tuple[ExternalContextItem, ...]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    parser = _BOJScheduleParser(year)
    parser.feed(html)
    events: list[ExternalContextItem] = []

    for row in parser.rows:
        # Data rows are: MPM date | Outlook | Summary of Opinions | MPM Minutes.
        if len(row) < 4:
            continue
        summary_at = _parse_boj_date(row[2], year)
        minutes_at = _parse_boj_date(row[3], year)

        if summary_at is not None:
            events.append(
                ExternalContextItem(
                    source="boj",
                    source_id=f"summary-opinions-{summary_at.astimezone(_BOJ_TZ).date().isoformat()}",
                    kind="scheduled_event",
                    title="BOJ Summary of Opinions",
                    observed_at=observed_at,
                    source_url=source_url,
                    scheduled_at=summary_at,
                    currencies=("JPY",),
                    risk="medium",
                )
            )
        if minutes_at is not None:
            events.append(
                ExternalContextItem(
                    source="boj",
                    source_id=f"mpm-minutes-{minutes_at.astimezone(_BOJ_TZ).date().isoformat()}",
                    kind="scheduled_event",
                    title="BOJ Monetary Policy Meeting Minutes",
                    observed_at=observed_at,
                    source_url=source_url,
                    scheduled_at=minutes_at,
                    currencies=("JPY",),
                    risk="medium",
                )
            )

    unique = {item.key: item for item in events}
    return tuple(sorted(unique.values(), key=lambda item: item.scheduled_at or item.observed_at))


def fetch_boj_events(
    observed_at: datetime | None = None,
    *,
    year: int | None = None,
    timeout_seconds: float = 8.0,
) -> tuple[ExternalContextItem, ...]:
    observed = observed_at or datetime.now(timezone.utc)
    target_year = year or observed.astimezone(_BOJ_TZ).year
    headers = {
        "User-Agent": "JevPip/0.1 (+https://github.com/yo4e/JevPip)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    }
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = client.get(BOJ_MPM_URL)
        response.raise_for_status()
    return parse_boj_mpm_html(
        response.text,
        observed_at=observed,
        year=target_year,
    )


_FED_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(data.replace("\xa0", " ").split())
        if text:
            self.parts.append(text)


def parse_fed_fomc_html(
    html: str,
    *,
    observed_at: datetime,
    year: int,
    source_url: str = FED_FOMC_URL,
) -> tuple[ExternalContextItem, ...]:
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")

    parser = _VisibleTextParser()
    parser.feed(html)
    parts = parser.parts

    heading = f"{year} FOMC Meetings"
    try:
        start = next(i for i, part in enumerate(parts) if heading in part)
    except StopIteration:
        return ()

    end = len(parts)
    for i in range(start + 1, len(parts)):
        part = parts[i]
        if re.fullmatch(r"20\d{2} FOMC Meetings", part) and heading not in part:
            end = i
            break

    events: list[ExternalContextItem] = []
    month: int | None = None
    for part in parts[start + 1 : end]:
        lower = part.lower()
        if lower in _FED_MONTHS:
            month = _FED_MONTHS[lower]
            continue
        if "/" in lower:
            candidates = [item.strip() for item in lower.split("/")]
            if all(item in _FED_MONTHS for item in candidates):
                month = _FED_MONTHS[candidates[-1]]
                continue
        if month is None:
            continue

        match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?\*?", part)
        if not match:
            continue
        final_day = int(match.group(2) or match.group(1))
        local_at = datetime(year, month, final_day, 14, 0, tzinfo=_FED_TZ)
        scheduled_at = local_at.astimezone(timezone.utc)
        events.append(
            ExternalContextItem(
                source="fed",
                source_id=f"fomc-statement-{local_at.date().isoformat()}",
                kind="scheduled_event",
                title="Federal Reserve FOMC statement",
                observed_at=observed_at,
                source_url=source_url,
                scheduled_at=scheduled_at,
                currencies=("USD",),
                risk="high",
            )
        )

    unique = {item.key: item for item in events}
    return tuple(sorted(unique.values(), key=lambda item: item.scheduled_at or item.observed_at))


def fetch_fed_events(
    observed_at: datetime | None = None,
    *,
    year: int | None = None,
    timeout_seconds: float = 8.0,
) -> tuple[ExternalContextItem, ...]:
    observed = observed_at or datetime.now(timezone.utc)
    target_year = year or observed.astimezone(_FED_TZ).year
    headers = {
        "User-Agent": "JevPip/0.1 (+https://github.com/yo4e/JevPip)",
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    }
    with httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=True,
        headers=headers,
    ) as client:
        response = client.get(FED_FOMC_URL)
        response.raise_for_status()
    return parse_fed_fomc_html(
        response.text,
        observed_at=observed,
        year=target_year,
    )
