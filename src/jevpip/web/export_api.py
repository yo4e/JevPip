from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from jevpip.web.research_service import ResearchService


router = APIRouter(prefix="/api/export", tags=["export"])


def build_export_router(service: ResearchService) -> APIRouter:
    export_router = APIRouter(prefix="/api/export", tags=["export"])

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
