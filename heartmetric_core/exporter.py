"""Export a HEARTMETRIC analysis to Excel, CSV or JSON.

The Excel workbook is meant to be handed to a co-author: it opens on a README
sheet that states the license, the data source and what each sheet holds.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Dict, Mapping

import pandas as pd

from .schema import STANDARD_COLUMNS

LICENSE_LINE = "MIT License · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University"


def _frame_from_records(records: Any, columns: list[str] | None = None) -> pd.DataFrame:
    if records is None:
        return pd.DataFrame()
    if isinstance(records, pd.DataFrame):
        return records.copy()
    if isinstance(records, list) and records and isinstance(records[0], dict):
        frame = pd.DataFrame(records)
        if columns:
            for column in columns:
                if column not in frame.columns:
                    frame[column] = None
            frame = frame[[c for c in columns if c in frame.columns]]
        return frame
    return pd.DataFrame()


def bundle_frames(bundle: Mapping[str, Any]) -> Dict[str, pd.DataFrame]:
    """Turn an analysis bundle into the sheet set used by both exporters."""
    summary = bundle.get("summary") or {}
    summary_rows = []
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            continue
        summary_rows.append({"metric": key, "value": value})
    quality = bundle.get("quality") or {}
    quality_rows = [
        {"check": key, "result": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}
        for key, value in quality.items()
    ]

    frames = {
        "Summary": pd.DataFrame(summary_rows),
        "Quality": pd.DataFrame(quality_rows),
        "Conditions": _frame_from_records(bundle.get("conditions")),
        "Exposure": _frame_from_records(bundle.get("exposure")),
        "Comparison": _frame_from_records(bundle.get("comparison")),
        "Daily": _frame_from_records(bundle.get("daily")),
        "Correlations": _frame_from_records(bundle.get("correlations")),
        "Readings": _frame_from_records(bundle.get("series")),
    }
    return {name: frame for name, frame in frames.items() if not frame.empty}


def _readme_frame(bundle: Mapping[str, Any]) -> pd.DataFrame:
    meta = bundle.get("meta") or {}
    rows = [
        ("Project", "HEARTMETRIC — Environmental Cardiovascular Response Platform"),
        ("Lab", "FEI · HEL Lab, Gyeongsang National University"),
        ("License", LICENSE_LINE),
        ("Generated", meta.get("generated_at", "")),
        ("Version", meta.get("heartmetric_version", "")),
        ("Comparison", f"{meta.get('comparison', {}).get('b', '')} → {meta.get('comparison', {}).get('a', '')}"),
        ("Night window", meta.get("night_window", "")),
        ("Data", meta.get("input", {}).get("data", "user-supplied") if isinstance(meta.get("input"), dict) else "user-supplied"),
        ("", ""),
        ("Sheets", "Summary · Quality · Conditions · Exposure · Comparison · Daily · Correlations · Readings"),
        ("Indices", "MAP = DBP + (SBP−DBP)/3 · PP = SBP−DBP · Dipping = (day−night)/day × 100"),
        ("", "HRV recovery = night RMSSD / day RMSSD × 100 (name of the baseline in the Summary sheet)"),
        ("", "Stress index: 0.30 BP load + 0.25 HRV suppression + 0.20 PM2.5 + 0.15 thermal + 0.10 HR load"),
        ("", ""),
        (
            "Disclaimer",
            "These are research descriptors of the submitted time series, not a diagnosis. "
            "A cuff measurement and a clinician remain the reference. HEARTMETRIC is not "
            "affiliated with Oura Health Oy or Apple Inc.",
        ),
        ("Contact", "bkim5020@gnu.ac.kr"),
    ]
    return pd.DataFrame(rows, columns=["item", "detail"])


def to_excel(
    bundle: Mapping[str, Any] | pd.DataFrame,
    path: str | Path | None = None,
    *,
    sheet_order: list[str] | None = None,
) -> bytes | str:
    """Write a multi-sheet workbook; returns bytes when no path is given."""
    if isinstance(bundle, pd.DataFrame):
        bundle = {"series": bundle.to_dict(orient="records"), "meta": {}}
    frames = bundle_frames(bundle)
    order = sheet_order or ["Summary", "Quality", "Conditions", "Exposure", "Comparison", "Daily", "Correlations", "Readings"]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _readme_frame(bundle).to_excel(writer, sheet_name="README", index=False)
        for name in order:
            frame = frames.get(name)
            if frame is None or frame.empty:
                continue
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            worksheet = writer.sheets[name[:31]]
            for index, column in enumerate(frame.columns, start=1):
                width = max(10, min(42, int(max([len(str(column))] + [len(str(v)) for v in frame[column].head(200)]) + 2)))
                worksheet.column_dimensions[worksheet.cell(row=1, column=index).column_letter].width = width
            worksheet.freeze_panes = "A2"
    payload = buffer.getvalue()
    if path is None:
        return payload
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_bytes(payload)
    return str(path)


def to_csv(frame: pd.DataFrame, path: str | Path | None = None, *, encoding: str = "utf-8-sig") -> bytes | str:
    """Write one table as CSV (UTF-8 with BOM so Excel opens Korean text)."""
    working = frame.copy()
    for column in STANDARD_COLUMNS:
        if column not in working.columns and column == "timestamp":
            working[column] = None
    payload = working.to_csv(index=False, encoding=encoding)
    if path is None:
        return payload.encode(encoding)
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_text(payload, encoding=encoding)
    return str(path)


def to_csv_dir(bundle: Mapping[str, Any], directory: str | Path) -> list[str]:
    """Write each table of a bundle as its own CSV; returns the file paths."""
    target = Path(str(directory))
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in bundle_frames(bundle).items():
        path = target / f"heartmetric_{name.lower()}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        written.append(str(path))
    return written


def to_json(bundle: Mapping[str, Any], path: str | Path | None = None, *, indent: int = 2) -> bytes | str:
    payload = json.dumps(bundle, ensure_ascii=False, indent=indent, allow_nan=False)
    if path is None:
        return payload.encode("utf-8")
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_text(payload, encoding="utf-8")
    return str(path)


def save(
    bundle: Mapping[str, Any],
    path: str | Path,
    *,
    fmt: str | None = None,
) -> str:
    """Save by extension (``.xlsx`` / ``.csv`` / ``.json``)."""
    suffix = (fmt or Path(str(path)).suffix.lstrip(".")).lower()
    if suffix in ("xlsx", "xls", "excel"):
        return str(to_excel(bundle, path))
    if suffix == "csv":
        return str(to_csv(bundle_frames(bundle).get("Readings", pd.DataFrame()), path))
    if suffix == "json":
        return str(to_json(bundle, path))
    raise ValueError(f"unsupported export format: {suffix}")
