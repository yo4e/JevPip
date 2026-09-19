import asyncio
from datetime import datetime, timezone
from decimal import Decimal

import jevpip.observer as observer_module
from jevpip.market.models import MarketTick
from jevpip.observer import observe


UTC = timezone.utc


class FakeJevClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def decide(
        self,
        state,
        horizon="5s",
        *,
        supervisor_strategies=(),
        instrument_label="the instrument",
    ):
        self.calls.append(
            {
                "state": state,
                "horizon": horizon,
                "supervisor_strategies": supervisor_strategies,
                "instrument_label": instrument_label,
            }
        )
        return self.response


async def one_tick(_instrument_id):
    yield MarketTick(
        instrument_id="USD_JPY",
        symbol="USD_JPY",
        display_symbol="USD/JPY",
        bid=Decimal("150.000"),
        ask=Decimal("150.010"),
        market_timestamp=datetime(2026, 9, 19, 14, 0, tzinfo=UTC),
        received_at=datetime(2026, 9, 19, 14, 0, tzinfo=UTC),
        status="OPEN",
    )


def supervisor_response(*, complete=True):
    answers = {
        "supervisor_pause_entry": {"type": "noul", "noul": 0.82},
        "supervisor_strategy": {
            "type": "choice",
            "choice": "ma_trend",
            "confidence": 0.91,
            "probabilities": {"ma_trend": 0.91},
        },
    }
    if complete:
        answers["supervisor_caution"] = {"type": "noul", "noul": 0.4}
    return {"answers": answers}


def test_observer_uses_one_jev_call_for_context_and_supervisor(tmp_path, monkeypatch):
    monkeypatch.setattr(observer_module, "stream_ticker", one_tick)
    client = FakeJevClient(supervisor_response())
    events = []

    def context_provider(at, instrument_id):
        assert instrument_id == "USD_JPY"
        return {
            "as_of": at.isoformat(),
            "external_context": [
                {
                    "source": "fed",
                    "source_id": "fomc-test",
                    "kind": "scheduled_event",
                    "risk": "high",
                }
            ],
        }

    asyncio.run(
        observe(
            {},
            tmp_path,
            client,
            jev_every_seconds=0,
            max_ticks=1,
            instrument_id="USD_JPY",
            on_update=events.append,
            emit_console=False,
            jev_state_context_provider=context_provider,
            jev_supervisor_strategies=("momentum", "ma_trend"),
        )
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["supervisor_strategies"] == ("momentum", "ma_trend")
    assert call["instrument_label"] == "USD/JPY"
    assert call["state"]["external_context"][0]["source_id"] == "fomc-test"

    decision = next(event for event in events if event["kind"] == "decision")
    assert decision["jev_supervisor"]["state"] == "PAUSE_ENTRY"
    assert decision["jev_supervisor"]["strategy"] is None
    assert decision["jev_supervisor_error"] is None
    assert decision["state"]["external_context"][0]["source"] == "fed"


def test_observer_keeps_decision_when_supervisor_answer_is_incomplete(tmp_path, monkeypatch):
    monkeypatch.setattr(observer_module, "stream_ticker", one_tick)
    client = FakeJevClient(supervisor_response(complete=False))
    events = []

    asyncio.run(
        observe(
            {},
            tmp_path,
            client,
            jev_every_seconds=0,
            max_ticks=1,
            instrument_id="USD_JPY",
            on_update=events.append,
            emit_console=False,
            jev_state_context_provider=lambda at, instrument_id: {
                "as_of": at.isoformat(),
                "external_context": [],
            },
            jev_supervisor_strategies=("momentum",),
        )
    )

    decision = next(event for event in events if event["kind"] == "decision")
    assert decision["jev_supervisor"] is None
    assert "missing required" in decision["jev_supervisor_error"]
    assert not any(event["kind"] == "error" for event in events)



async def two_ticks(_instrument_id):
    for second in (0, 1):
        yield MarketTick(
            instrument_id="USD_JPY",
            symbol="USD_JPY",
            display_symbol="USD/JPY",
            bid=Decimal(f"150.00{second}"),
            ask=Decimal(f"150.01{second}"),
            market_timestamp=datetime(2026, 9, 20, 0, 0, second, tzinfo=UTC),
            received_at=datetime(2026, 9, 20, 0, 0, second, tzinfo=UTC),
            status="OPEN",
        )
        await asyncio.sleep(0)


def test_observer_does_not_block_ticks_while_jev_is_running(tmp_path, monkeypatch):
    monkeypatch.setattr(observer_module, "stream_ticker", two_ticks)
    original_to_thread = asyncio.to_thread

    async def delayed_to_thread(func, /, *args, **kwargs):
        await asyncio.sleep(0.01)
        return await original_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(observer_module.asyncio, "to_thread", delayed_to_thread)
    client = FakeJevClient(supervisor_response())
    events = []

    asyncio.run(
        observe(
            {},
            tmp_path,
            client,
            jev_every_seconds=0,
            max_ticks=2,
            instrument_id="USD_JPY",
            on_update=events.append,
            emit_console=False,
        )
    )

    kinds = [event["kind"] for event in events]
    assert kinds[:2] == ["tick", "tick"]
    assert kinds.count("decision") == 1
    decision = next(event for event in events if event["kind"] == "decision")
    assert decision["basis_market_timestamp"] == "2026-09-20T00:00:00+00:00"
    assert decision["requested_at"] <= decision["available_at"]
