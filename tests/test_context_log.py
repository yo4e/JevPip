import json
from datetime import datetime, timezone

from jevpip.context import ExternalContextItem
from jevpip.context_log import append_context_fetch


UTC = timezone.utc


def test_context_fetch_log_preserves_revisions(tmp_path):
    first = ExternalContextItem(
        source="bls",
        source_id="cpi-2026-09",
        kind="scheduled_event",
        title="Consumer Price Index",
        observed_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        source_url="https://example.test/cpi",
        scheduled_at=datetime(2026, 9, 11, 12, 30, tzinfo=UTC),
        currencies=("USD",),
        risk="high",
    )
    revised = ExternalContextItem(
        source="bls",
        source_id="cpi-2026-09",
        kind="scheduled_event",
        title="Consumer Price Index",
        observed_at=datetime(2026, 9, 2, 0, 0, tzinfo=UTC),
        source_url="https://example.test/cpi",
        scheduled_at=datetime(2026, 9, 11, 13, 30, tzinfo=UTC),
        currencies=("USD",),
        risk="high",
    )

    path = append_context_fetch(
        tmp_path,
        source="bls",
        observed_at=datetime(2026, 9, 1, 0, 0, tzinfo=UTC),
        events=[first],
    )
    append_context_fetch(
        tmp_path,
        source="bls",
        observed_at=datetime(2026, 9, 1, 12, 0, tzinfo=UTC),
        events=[revised],
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    assert rows[0]["events"][0]["scheduled_at"] == "2026-09-11T12:30:00+00:00"
    assert rows[1]["events"][0]["scheduled_at"] == "2026-09-11T13:30:00+00:00"
    assert rows[0]["events"][0]["source_id"] == rows[1]["events"][0]["source_id"]
    assert "body" not in rows[0]["events"][0]


def test_context_fetch_log_records_source_error(tmp_path):
    path = append_context_fetch(
        tmp_path,
        source="fed",
        observed_at=datetime(2026, 9, 19, 14, 0, tzinfo=UTC),
        error="TimeoutError: source unavailable",
    )

    row = json.loads(path.read_text(encoding="utf-8").strip())
    assert row["status"] == "error"
    assert row["event_count"] == 0
    assert "TimeoutError" in row["error"]
