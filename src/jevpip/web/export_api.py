from __future__ import annotations

from html import escape
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from jevpip.web.research_service import ResearchService


_DATASET_LABELS = {
    "decision_traces": "Decision trace",
    "fifty_outcomes": "Fifty+ outcomes",
}


def build_export_router(service: ResearchService) -> APIRouter:
    export_router = APIRouter(prefix="/api/export", tags=["export"])

    @export_router.get("/ui", response_class=HTMLResponse)
    async def export_ui(
        dataset: Literal["decision_traces", "fifty_outcomes"] = "decision_traces",
        instrument_id: str = "USD_JPY",
    ) -> HTMLResponse:
        try:
            dates = service.export_dates(dataset, instrument_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        options = "".join(
            f'<option value="{escape(day)}">{escape(day)}</option>' for day in dates
        ) or '<option value="">データなし</option>'
        dataset_options = "".join(
            f'<option value="{key}"{" selected" if key == dataset else ""}>{label}</option>'
            for key, label in _DATASET_LABELS.items()
        )
        safe_instrument = escape(instrument_id)
        body = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>JevPip Research Export</title>
<style>body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;color:#111827}}label{{display:block;margin:14px 0 5px;font-weight:700}}select,input,button{{font:inherit;padding:8px 10px}}.row{{display:flex;gap:10px;flex-wrap:wrap;align-items:end}}.muted{{color:#6b7280}}a{{display:inline-block;margin:14px 12px 0 0}}</style></head>
<body><h1>Research data export</h1><p class="muted">ローカル研究データをCSV / JSONLでダウンロードします。read-onlyです。</p>
<form method="get" action="/api/export/ui"><div class="row"><div><label>Dataset</label><select name="dataset">{dataset_options}</select></div><div><label>Instrument</label><input name="instrument_id" value="{safe_instrument}"></div><button type="submit">一覧を更新</button></div></form>
<label>Date</label><select id="date">{options}</select><div>
<a id="csv" href="#">CSVをダウンロード</a><a id="jsonl" href="#">JSONLをダウンロード</a></div>
<script>const d=document.getElementById('date');const ds={dataset!r};const inst={instrument_id!r};function u(f){{return '/api/export/research?dataset='+encodeURIComponent(ds)+'&instrument_id='+encodeURIComponent(inst)+'&date='+encodeURIComponent(d.value)+'&format='+f}}function sync(){{document.getElementById('csv').href=u('csv');document.getElementById('jsonl').href=u('jsonl')}}d.addEventListener('change',sync);sync();</script>
</body></html>"""
        return HTMLResponse(body)

    @export_router.get("/dates")
    async def get_export_dates(
        dataset: Literal["decision_traces", "fifty_outcomes"] = "decision_traces",
        instrument_id: str = "USD_JPY",
    ) -> dict[str, object]:
        try:
            return {
                "dataset": dataset,
                "instrument_id": instrument_id,
                "dates": service.export_dates(dataset, instrument_id),
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @export_router.get("/research")
    async def export_research_data(
        dataset: Literal["decision_traces", "fifty_outcomes"] = "decision_traces",
        instrument_id: str = "USD_JPY",
        date: str = "",
        format: Literal["csv", "jsonl"] = "csv",
    ) -> Response:
        if not date:
            raise HTTPException(status_code=400, detail="export date が必要です。")
        try:
            content, media_type, filename = service.export_research_data(
                dataset=dataset,
                instrument_id=instrument_id,
                date=date,
                format=format,
            )
        except (ValueError, OSError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return export_router
