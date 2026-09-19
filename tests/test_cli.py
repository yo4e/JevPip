from __future__ import annotations

import json
from pathlib import Path

import pytest

from jevpip.cli import main


def _write_ticks(path: Path) -> None:
    rows = []
    for second, mid in enumerate([150.000, 150.010, 150.020, 150.030, 150.040, 150.050]):
        rows.append(
            {
                "instrument_id": "USD_JPY",
                "symbol": "USD_JPY",
                "market_timestamp": f"2026-09-19T00:00:{second:02d}+00:00",
                "received_at": f"2026-09-19T00:00:{second:02d}+00:00",
                "bid": f"{mid:.3f}",
                "ask": f"{mid + 0.002:.3f}",
                "status": "OPEN",
            }
        )
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )


def test_compare_cli_table_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = tmp_path / "ticks.jsonl"
    _write_ticks(path)

    rc = main(
        [
            "compare",
            "--instrument",
            "USD_JPY",
            "--file",
            str(path),
            "--strategies",
            "momentum,ma_trend",
        ]
    )
    assert rc == 0
    output = capsys.readouterr().out
    assert "USD/JPY" in output
    assert "momentum" in output
    assert "ma_trend" in output
    assert "net_pnl" in output
    assert "将来利益を示すものではありません" in output


def test_compare_cli_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    path = tmp_path / "ticks.jsonl"
    _write_ticks(path)

    rc = main(
        [
            "compare",
            "--instrument",
            "USD_JPY",
            "--file",
            str(path),
            "--strategies",
            "momentum",
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["momentum"]["ticks"] == 6
    assert "max_drawdown" in payload["momentum"]


def test_compare_cli_rejects_unknown_strategy(tmp_path: Path):
    path = tmp_path / "ticks.jsonl"
    _write_ticks(path)
    with pytest.raises(SystemExit, match="compare未対応strategy"):
        main(
            [
                "compare",
                "--instrument",
                "USD_JPY",
                "--file",
                str(path),
                "--strategies",
                "banana",
            ]
        )
