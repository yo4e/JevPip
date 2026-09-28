from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jevpip.config import Settings
from jevpip.web.export_api import build_export_router
from jevpip.web.research_service import ResearchService


def _client(tmp_path: Path) -> TestClient:
    app = FastAPI()
    service = ResearchService(Settings(_env_file=None, data_dir=tmp_path))
    app.include_router(build_export_router(service))
    return TestClient(app)


def test_export_dates_api(tmp_path: Path):
    directory = tmp_path / "decision_traces" / "USD_JPY"
    directory.mkdir(parents=True)
    (directory / "2026-09-28.jsonl").write_text("{}\n", encoding="utf-8")

    response = _client(tmp_path).get(
        "/api/export/dates",
        params={"dataset": "decision_traces", "instrument_id": "USD_JPY"},
    )
    assert response.status_code == 200
    assert response.json()["dates"] == ["2026-09-28"]


def test_export_research_csv_download(tmp_path: Path):
    directory = tmp_path / "decision_traces" / "USD_JPY"
    directory.mkdir(parents=True)
    (directory / "2026-09-28.jsonl").write_text(
        json.dumps({"direction": "UP", "nested": {"price": 150.125}}) + "\n",
        encoding="utf-8",
    )

    response = _client(tmp_path).get(
        "/api/export/research",
        params={
            "dataset": "decision_traces",
            "instrument_id": "USD_JPY",
            "date": "2026-09-28",
            "format": "csv",
        },
    )
    assert response.status_code == 200
    assert response.headers["content-disposition"].endswith(
        'filename="jevpip-decision_traces-USD_JPY-2026-09-28.csv"'
    )
    assert "direction" in response.text
    assert "nested.price" in response.text


def test_export_research_missing_date_is_400(tmp_path: Path):
    response = _client(tmp_path).get("/api/export/research")
    assert response.status_code == 400
