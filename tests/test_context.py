from datetime import datetime, timedelta, timezone

import pytest

from jevpip.context import (
    ExternalContextItem,
    select_context,
    to_jev_context_state,
)


UTC = timezone.utc


def dt(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 9, 19, hour, minute, tzinfo=UTC)


def scheduled(**overrides) -> ExternalContextItem:
    values = {
        "source": "bls",
        "source_id": "cpi-2026-09",
        "kind": "scheduled_event",
        "title": "Consumer Price Index",
        "observed_at": dt(10),
        "source_url": "https://example.test/cpi",
        "scheduled_at": dt(12),
        "currencies": ("USD",),
        "risk": "high",
    }
    values.update(overrides)
    return ExternalContextItem(**values)


def test_context_requires_timezone_aware_timestamps():
    with pytest.raises(ValueError, match="observed_at"):
        scheduled(observed_at=datetime(2026, 9, 19, 10, 0))


def test_future_observation_cannot_leak_into_past_decision():
    item = scheduled(observed_at=dt(11, 30))
    assert select_context(
        [item],
        as_of=dt(11),
        currencies=("USD",),
        lead=timedelta(hours=2),
    ) == ()


def test_latest_revision_is_selected_only_when_it_was_already_known():
    original = scheduled(
        observed_at=dt(9),
        scheduled_at=dt(12),
        title="Consumer Price Index - original",
    )
    revised = scheduled(
        observed_at=dt(11, 30),
        scheduled_at=dt(13),
        title="Consumer Price Index - revised",
    )

    before_revision = select_context(
        [original, revised],
        as_of=dt(11),
        currencies=("USD",),
        lead=timedelta(hours=2),
    )
    after_revision = select_context(
        [original, revised],
        as_of=dt(12),
        currencies=("USD",),
        lead=timedelta(hours=2),
    )

    assert before_revision == (original,)
    assert after_revision == (revised,)


def test_currency_and_instrument_relevance_filter():
    usd = scheduled(currencies=("USD",))
    btc = scheduled(
        source_id="btc-maintenance",
        title="BTC venue maintenance",
        currencies=(),
        instruments=("BTC",),
    )

    assert select_context(
        [usd, btc],
        as_of=dt(11, 30),
        instrument_id="BTC",
        currencies=("JPY",),
    ) == (btc,)


def test_scheduled_event_window_has_lead_and_lag():
    item = scheduled(scheduled_at=dt(12))

    assert select_context(
        [item],
        as_of=dt(10, 59),
        currencies=("USD",),
        lead=timedelta(hours=1),
    ) == ()
    assert select_context(
        [item],
        as_of=dt(11),
        currencies=("USD",),
        lead=timedelta(hours=1),
    ) == (item,)
    assert select_context(
        [item],
        as_of=dt(12, 31),
        currencies=("USD",),
        lag=timedelta(minutes=30),
    ) == ()


def test_unpublished_release_is_excluded_even_if_observed_early():
    release = ExternalContextItem(
        source="fed",
        source_id="fomc-statement",
        kind="official_release",
        title="FOMC statement",
        observed_at=dt(11),
        source_url="https://example.test/fomc",
        published_at=dt(12),
        currencies=("USD",),
        risk="high",
    )

    assert select_context([release], as_of=dt(11, 59), currencies=("USD",)) == ()
    assert select_context([release], as_of=dt(12), currencies=("USD",)) == (release,)


def test_jev_state_contains_provenance_and_relative_time_not_raw_body():
    item = scheduled()
    state = to_jev_context_state([item], as_of=dt(11, 30))
    packed = state["external_context"][0]

    assert packed["source"] == "bls"
    assert packed["source_id"] == "cpi-2026-09"
    assert packed["seconds_from_now"] == 1800
    assert "body" not in packed
