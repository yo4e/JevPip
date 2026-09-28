from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from jevpip.config import Settings
from jevpip.web.export_api import build_export_router
from jevpip.web.research_service import ResearchService


def test_export_ui_lists_dates_and_download_links(tmp_path: Path):
    directory = tmp_path / "decision_traces" / "USD_JPY"
    directory.mkdir(parents=True)
    (directory / "2026-09-28.jsonl").write_text("{}\n", encoding="utf-8")

    app = FastAPI()
    app.include_router(
        build_export_router(ResearchService(Settings(_env_file=None, data_dir=tmp_path)))
    )
    response = TestClient(app).get(
        "/api/export/ui",
        params={"dataset": "decision_traces", "instrument_id": "USD_JPY"},
    )

    assert response.status_code == 200
    assert "Research data export" in response.text
    assert "2026-09-28" in response.text
    assert "CSVをダウンロード" in response.text
    assert "JSONLをダウンロード" in response.text
