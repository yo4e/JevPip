from datetime import datetime, timezone

from jevpip.context_sources import bls_risk, parse_bls_ics, parse_boj_mpm_html


UTC = timezone.utc


def test_parse_bls_ics_timezone_and_risk():
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:cpi-2026-09
DTSTART;TZID=America/New_York:20260911T083000
SUMMARY:Consumer Price Index for August 2026
URL:https://www.bls.gov/schedule/news_release/cpi.htm
END:VEVENT
BEGIN:VEVENT
UID:jolts-2026-09
DTSTART;TZID=America/New_York:20260929T100000
SUMMARY:Job Openings and Labor Turnover Survey for August 2026
END:VEVENT
END:VCALENDAR
"""
    observed = datetime(2026, 9, 1, tzinfo=UTC)
    items = parse_bls_ics(text, observed_at=observed)

    assert len(items) == 2
    assert items[0].source == "bls"
    assert items[0].source_id == "cpi-2026-09"
    assert items[0].scheduled_at == datetime(2026, 9, 11, 12, 30, tzinfo=UTC)
    assert items[0].risk == "high"
    assert items[0].currencies == ("USD",)
    assert items[1].risk == "medium"


def test_parse_bls_ics_unfolds_lines_and_skips_all_day_entries():
    text = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:holiday
DTSTART;VALUE=DATE:20260907
SUMMARY:Labor Day
END:VEVENT
BEGIN:VEVENT
UID:ppi
DTSTART:20260910T123000Z
SUMMARY:Producer Price Index for August 2026
 continued
END:VEVENT
END:VCALENDAR
"""
    items = parse_bls_ics(
        text,
        observed_at=datetime(2026, 9, 1, tzinfo=UTC),
    )

    assert len(items) == 1
    assert items[0].source_id == "ppi"
    assert items[0].scheduled_at == datetime(2026, 9, 10, 12, 30, tzinfo=UTC)
    assert "continued" in items[0].title


def test_bls_risk_is_local_classification():
    assert bls_risk("Employment Situation for August 2026") == "high"
    assert bls_risk("Employment Cost Index for Third Quarter 2026") == "medium"
    assert bls_risk("Employee Benefits in the United States") == "low"


def test_parse_boj_timed_summary_and_minutes():
    html = """
    <html><body>
      <h2>2026</h2>
      <table>
        <tr><th>Date of MPM</th><th>Outlook</th><th>Summary of Opinions</th><th>MPM Minutes</th></tr>
        <tr>
          <td>Sept. 17 (Thurs.), 18 (Fri.)</td>
          <td>-</td>
          <td>Oct. 1 (Thurs.)</td>
          <td>Nov. 5 (Thurs.)</td>
        </tr>
        <tr>
          <td>Dec. 17 (Thurs.), 18 (Fri.)</td>
          <td>-</td>
          <td>Dec. 28 (Mon.)</td>
          <td>Jan. 27 (Wed.), 2027</td>
        </tr>
      </table>
      <h2>2027</h2>
    </body></html>
    """
    items = parse_boj_mpm_html(
        html,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
        year=2026,
    )

    assert [item.source_id for item in items] == [
        "summary-opinions-2026-10-01",
        "mpm-minutes-2026-11-05",
        "summary-opinions-2026-12-28",
        "mpm-minutes-2027-01-27",
    ]
    assert all(item.source == "boj" for item in items)
    assert all(item.currencies == ("JPY",) for item in items)
    assert all(item.risk == "medium" for item in items)
    # 08:50 JST = 23:50 UTC on the previous calendar day.
    assert items[0].scheduled_at == datetime(2026, 9, 30, 23, 50, tzinfo=UTC)
