"""FastAPI surface for HEARTMETRIC Core.

    uvicorn api.server:app --reload

Endpoints
    GET  /api/health   service and version information
    GET  /api/sample   the bundled synthetic 14-day series (urban vs forest)
    POST /api/analyze  analyse uploaded CSV/JSON/XML or posted records
    POST /api/export   same input, returns .xlsx / .csv / .json as a download

The browser workbench runs without this server; the API exists for scripts,
notebooks and lab pipelines that should produce the same numbers.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

# Allow running from the repository root (`uvicorn api.server:app`) as well as
# after `pip install -e .`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from heartmetric_core import __version__, about, exporter, loader, pipeline, synthetic  # noqa: E402

app = FastAPI(
    title="HEARTMETRIC API",
    version=__version__,
    description=about()["tagline"] + " · MIT · FEI · HEL Lab, Gyeongsang National University",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> Dict[str, Any]:
    return {
        "service": "HEARTMETRIC",
        "version": __version__,
        "docs": "/docs",
        "endpoints": ["/api/health", "/api/sample", "/api/analyze", "/api/export"],
        **about(),
    }


@app.get("/api/health")
async def health() -> Dict[str, Any]:
    return {"status": "ok", "version": __version__, "service": "heartmetric-api"}


@app.get("/api/sample")
async def sample(days: int = Query(14, ge=2, le=180), seed: int = Query(5020)) -> JSONResponse:
    """Synthetic demonstration table (never real participant data)."""
    frame = synthetic.generate(days=days, seed=seed)
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    return JSONResponse(
        {
            "meta": synthetic.metadata(days=days, seed=seed),
            "columns": list(frame.columns),
            "records": records,
        }
    )


def _frame_from_payload(payload: Any):
    """Accept {records|data: [...]}, a bare list, or a wide record list."""
    if isinstance(payload, list):
        return loader.load_json(json.dumps(payload), source="api")
    if isinstance(payload, dict):
        records = payload.get("records") or payload.get("data") or payload.get("readings")
        if records is None and "timestamp" in payload and isinstance(payload["timestamp"], list):
            records = payload
        if records is None:
            raise HTTPException(status_code=422, detail="body needs a 'records' array")
        condition = payload.get("condition")
        result = loader.load_json(json.dumps(records), source=str(payload.get("source", "api")))
        if condition:
            result.frame["condition"] = condition
        return result
    raise HTTPException(status_code=422, detail="unsupported payload")


async def _read_input(request: Request):
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file") or form.get("upload")
        if upload is None:
            raise HTTPException(status_code=422, detail="multipart body needs a 'file' field")
        data = await upload.read() if hasattr(upload, "read") else bytes(upload)
        name = str(getattr(upload, "filename", "upload.csv") or "upload.csv")
        result = loader.load_any(data, name=name)
        condition = form.get("condition")
        if condition:
            from heartmetric_core.schema import normalize_condition

            result.frame["condition"] = normalize_condition(str(condition))
        return result
    try:
        payload = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as error:  # pragma: no cover - defensive
        raise HTTPException(status_code=422, detail=f"invalid JSON body: {error}") from error
    if isinstance(payload, dict) and payload.get("demo"):
        return loader.LoadResult(frame=synthetic.generate(), source="synthetic")
    return _frame_from_payload(payload)


def _options(source: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "group_a": source.get("group_a", "forest"),
        "group_b": source.get("group_b", "urban"),
        "paired": bool(source.get("paired", False)),
    }


@app.post("/api/analyze")
async def analyze(request: Request) -> JSONResponse:
    """Clean the input and return the full analysis bundle."""
    body: Dict[str, Any] = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            body = {}
        if isinstance(body, dict) and body.get("demo"):
            bundle = pipeline.demo_bundle(**_options(body))
            return JSONResponse(bundle)
    result = await _read_input(request)
    bundle = pipeline.analyze_loaded(result, **_options(body if isinstance(body, dict) else {}))
    return JSONResponse(bundle)


@app.post("/api/export")
async def export(request: Request, fmt: str = Query("xlsx", pattern="^(xlsx|csv|json)$")) -> StreamingResponse:
    """Return the analysis as a downloadable workbook, CSV or JSON."""
    result = await _read_input(request)
    bundle = pipeline.analyze_loaded(result)

    if fmt == "xlsx":
        payload = exporter.to_excel(bundle)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "heartmetric_report.xlsx"
    elif fmt == "csv":
        frame = loader.merge([result])
        payload = exporter.to_csv(frame)
        media = "text/csv; charset=utf-8"
        filename = "heartmetric_readings.csv"
    else:
        payload = exporter.to_json(bundle)
        media = "application/json"
        filename = "heartmetric_report.json"
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    uvicorn.run("api.server:app", host="127.0.0.1", port=8000, reload=True)
