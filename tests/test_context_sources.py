from datetime import datetime, timezone

import httpx
import jevpip.context_sources as context_sources
from jevpip.context_sources import (
    bls_risk,
    parse_bls_ics,
    parse_bls_schedule_html,
    parse_boj_mpm_html,
    parse_fed_fomc_html,
)


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


def test_parse_fed_fomc_statement_schedule():
    html = """
    <html><body>
      <h4>2026 FOMC Meetings</h4>
      <div>January</div><div>27-28</div>
      <div>March</div><div>17-18*</div>
      <div>September</div><div>15-16*</div>
      <div>October</div><div>27-28</div>
      <div>December</div><div>8-9*</div>
      <h4>2025 FOMC Meetings</h4>
    </body></html>
    """
    items = parse_fed_fomc_html(
        html,
        observed_at=datetime(2026, 9, 19, tzinfo=UTC),
        year=2026,
    )

    assert [item.source_id for item in items] == [
        "fomc-statement-2026-01-28",
        "fomc-statement-2026-03-18",
        "fomc-statement-2026-09-16",
        "fomc-statement-2026-10-28",
        "fomc-statement-2026-12-09",
    ]
    assert all(item.source == "fed" for item in items)
    assert all(item.risk == "high" for item in items)
    assert all(item.currencies == ("USD",) for item in items)
    # October is EDT: 14:00 Eastern = 18:00 UTC.
    assert items[3].scheduled_at == datetime(2026, 10, 28, 18, 0, tzinfo=UTC)



def test_parse_bls_monthly_schedule_html():
    html = """
    <html><body><table>
      <tr><th>Date</th><th>Time</th><th>Release</th></tr>
      <tr>
        <td>Tuesday, September 29, 2026</td>
        <td>10:00 AM</td>
        <td><a href="/schedule/news_release/jolts.htm">Job Openings and Labor Turnover Survey</a> for August 2026</td>
      </tr>
      <tr>
        <td>Friday, October 2, 2026</td>
        <td>08:30 AM</td>
        <td>Employment Situation for September 2026</td>
      </tr>
      <tr>
        <td>Monday, September 7, 2026</td>
        <td></td>
        <td>Labor Day</td>
      </tr>
    </table></body></html>
    """
    observed = datetime(2026, 9, 20, tzinfo=UTC)
    items = parse_bls_schedule_html(
        html,
        observed_at=observed,
        source_url="https://www.bls.gov/schedule/2026/09_sched_list.htm",
    )

    assert len(items) == 2
    assert items[0].title == "Job Openings and Labor Turnover Survey for August 2026"
    assert items[0].scheduled_at == datetime(2026, 9, 29, 14, 0, tzinfo=UTC)
    assert items[0].risk == "medium"
    assert items[1].title == "Employment Situation for September 2026"
    assert items[1].scheduled_at == datetime(2026, 10, 2, 12, 30, tzinfo=UTC)
    assert items[1].risk == "high"


def test_fetch_bls_events_falls_back_to_official_html_on_ics_403(monkeypatch):
    monthly_html = """
    <table>
      <tr><th>Date</th><th>Time</th><th>Release</th></tr>
      <tr>
        <td>Tuesday, September 29, 2026</td>
        <td>10:00 AM</td>
        <td>Job Openings and Labor Turnover Survey for August 2026</td>
      </tr>
    </table>
    """

    class FakeResponse:
        def __init__(self, url, status_code, text=""):
            self.request = httpx.Request("GET", url)
            self.status_code = status_code
            self.text = text

        def raise_for_status(self):
            if self.status_code >= 400:
                response = httpx.Response(
                    self.status_code,
                    request=self.request,
                )
                raise httpx.HTTPStatusError(
                    f"{self.status_code}",
                    request=self.request,
                    response=response,
                )

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url, **kwargs):
            if url == context_sources.BLS_ICS_URL:
                return FakeResponse(url, 403)
            return FakeResponse(url, 200, monthly_html)

    monkeypatch.setattr(context_sources.httpx, "Client", FakeClient)
    items = context_sources.fetch_bls_events(
        datetime(2026, 9, 20, tzinfo=UTC),
    )

    assert len(items) == 1
    assert items[0].source == "bls"
    assert items[0].title == "Job Openings and Labor Turnover Survey for August 2026"
