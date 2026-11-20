"""Automatic loader for cuff blood pressure, wearable and exposure exports.

The loader never guesses a value it cannot see. It maps headers onto the
standard schema, converts clearly non-SI units (with a warning), normalizes
condition labels and returns the table plus a full mapping report so a
researcher can audit what was understood.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence
from xml.etree import ElementTree as ET

import pandas as pd

from . import schema
from .schema import CONDITION, FLAGS, METRIC_COLUMNS, NOTES, SOURCE, STANDARD_COLUMNS, SUBJECT, TIMESTAMP

DEFAULT_TIMEZONE = "Asia/Seoul"


@dataclass
class LoadResult:
    """Loaded table plus what the loader understood about it."""

    frame: pd.DataFrame
    source: str = "generic"
    mapping: Dict[str, str] = field(default_factory=dict)
    unmapped: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rows_read: int = 0
    format: str = ""
    has_condition: bool = False

    def summary(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "format": self.format,
            "rows_read": self.rows_read,
            "rows_kept": int(len(self.frame)),
            "columns": {k: v for k, v in self.mapping.items()},
            "unmapped": list(self.unmapped),
            "warnings": list(self.warnings),
            "has_condition": self.has_condition,
        }


# --------------------------------------------------------------- time parsing


def _parse_timestamps(values: pd.Series, timezone: str = DEFAULT_TIMEZONE) -> pd.Series:
    """Parse mixed timestamp formats into naive local time in ``timezone``."""
    if pd.api.types.is_numeric_dtype(values):
        num = pd.to_numeric(values, errors="coerce")
        finite = num.dropna()
        scale = 1.0
        if len(finite) and finite.abs().max() > 1e11:  # epoch milliseconds
            scale = 1e-3
        return (
            pd.to_datetime(num * scale, unit="s", utc=True, errors="coerce")
            .dt.tz_convert(timezone)
            .dt.tz_localize(None)
        )

    text = values.astype("string").str.strip()
    has_offset = text.str.contains(r"(?:Z|[+-]\d{2}:?\d{2}|UTC|GMT)\s*$", regex=True, na=False)

    if not bool(has_offset.any()):
        # Naive timestamps are already local clock time: no offset to apply.
        return pd.to_datetime(text, errors="coerce", format="mixed")

    if bool(has_offset.all()):
        parsed = pd.to_datetime(text, utc=True, errors="coerce", format="mixed")
        return parsed.dt.tz_convert(timezone).dt.tz_localize(None)

    # Mixed file: decide per value so a naive row is not shifted twice.
    out = pd.Series(pd.NaT, index=text.index, dtype="datetime64[ns]")
    for idx, raw in text.items():
        if pd.isna(raw) or str(raw) == "":
            continue
        try:
            stamp = pd.to_datetime(str(raw), errors="raise")
        except (ValueError, TypeError):
            continue
        if stamp.tzinfo is None:
            out.loc[idx] = stamp
        else:
            out.loc[idx] = stamp.tz_convert(timezone).tz_localize(None)
    return out


# ------------------------------------------------------------------ mapping


def _canonical_headers(columns: Iterable[object]) -> tuple[Dict[str, str], List[str]]:
    mapping: Dict[str, str] = {}
    unmapped: List[str] = []
    for raw in columns:
        canonical = schema.canonical_column(raw)
        if canonical and canonical not in mapping:
            mapping[canonical] = str(raw)
        else:
            unmapped.append(str(raw))
    return mapping, unmapped


def _find_header(columns: Iterable[object], aliases: Sequence[str]) -> str | None:
    wanted = {schema.normalize_key(a) for a in aliases}
    for raw in columns:
        if schema.normalize_key(raw) in wanted:
            return str(raw)
    return None


def _rename_to_standard(frame: pd.DataFrame, mapping: Mapping[str, str]) -> pd.DataFrame:
    inverse = {raw: canonical for canonical, raw in mapping.items()}
    renamed = frame.rename(columns=inverse)
    for column in STANDARD_COLUMNS:
        if column not in renamed.columns:
            renamed[column] = pd.NA
    return renamed[list(STANDARD_COLUMNS)]


def _pivot_long_format(
    frame: pd.DataFrame, warnings: List[str]
) -> tuple[pd.DataFrame | None, Dict[str, str]]:
    """Handle HealthKit-style long exports (one row per metric)."""
    name_col = _find_header(frame.columns, schema.METRIC_NAME_ALIASES)
    value_col = _find_header(frame.columns, schema.VALUE_ALIASES)
    if name_col is None or value_col is None:
        return None, {}
    frame = frame.copy()
    frame["__metric"] = frame[name_col].map(schema.canonical_metric_name)
    if not frame["__metric"].notna().any():
        return None, {}
    frame["__value"] = pd.to_numeric(frame[value_col], errors="coerce")

    mapping, _ = _canonical_headers(frame.columns)
    mapping = {k: v for k, v in mapping.items() if k in {TIMESTAMP, SOURCE, CONDITION}}
    mapped = _rename_to_standard(frame, mapping)
    mapped["__metric"] = frame["__metric"].to_numpy()
    mapped["__value"] = frame["__value"].to_numpy()

    # Values with different metrics can share a timestamp; pivot them into columns.
    time_col = mapping.get(TIMESTAMP)
    if time_col is None:
        warnings.append("long-format export has no recognizable timestamp column")
        return None, mapping

    keys = [TIMESTAMP]
    for extra in (SOURCE, CONDITION):
        if extra in mapping:
            keys.append(extra)

    wide = (
        mapped.dropna(subset=["__metric"])
        .pivot_table(
            index=keys, columns="__metric", values="__value", aggfunc="mean", dropna=False
        )
        .reset_index()
    )
    wide.columns.name = None
    # Drop the placeholder metric columns that came from _rename_to_standard.
    for metric in METRIC_COLUMNS:
        if metric in wide.columns and wide[metric].isna().all():
            wide = wide.drop(columns=[metric])
    for column in STANDARD_COLUMNS:
        if column not in wide.columns:
            wide[column] = pd.NA
    warnings.append(
        "long-format export detected: rows were pivoted by metric name "
        f"({name_col} → standard columns)"
    )
    return wide[list(STANDARD_COLUMNS)], mapping


# ------------------------------------------------------------- unit handling


def _apply_units(frame: pd.DataFrame, warnings: List[str]) -> pd.DataFrame:
    frame = frame.copy()

    def _max(column: str) -> float | None:
        if column not in frame:
            return None
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        return float(values.max()) if len(values) else None

    sbp_max, dbp_max = _max("sbp"), _max("dbp")
    if sbp_max is not None and 0 < sbp_max < 40 and (dbp_max is None or dbp_max < 30):
        # Kilopascal cuff exports (1 kPa = 7.50062 mmHg).
        for column in ("sbp", "dbp"):
            frame[column] = pd.to_numeric(frame[column], errors="coerce") * 7.50062
        warnings.append("blood pressure looked like kPa and was converted to mmHg")

    temp_max = _max("temp_c")
    if temp_max is not None and 60 < temp_max < 130:
        frame["temp_c"] = (pd.to_numeric(frame["temp_c"], errors="coerce") - 32) * 5 / 9
        warnings.append("temperature looked like °F and was converted to °C")

    for column in ("rmssd", "sdnn"):
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        if len(values) and float(values.max()) <= 1.5 and float(values.max()) > 0:
            frame[column] = pd.to_numeric(frame[column], errors="coerce") * 1000
            warnings.append(f"{column} looked like seconds and was converted to ms")

    if "green_index" in frame:
        green = pd.to_numeric(frame["green_index"], errors="coerce").dropna()
        if len(green) and float(green.max()) > 1.0 and float(green.max()) <= 100.0:
            frame["green_index"] = pd.to_numeric(frame["green_index"], errors="coerce") / 100
            warnings.append("green_index looked like a 0–100 scale and was rescaled to 0–1")
    return frame


def _finalize(
    frame: pd.DataFrame,
    *,
    source: str,
    mapping: Mapping[str, str],
    unmapped: List[str],
    warnings: List[str],
    timezone: str,
    format_name: str,
    rows_read: int,
) -> LoadResult:
    working = frame.copy()
    for column in STANDARD_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA
    if TIMESTAMP not in mapping and TIMESTAMP not in working.columns:
        warnings.append("no timestamp column was recognized; rows cannot be ordered in time")
    if TIMESTAMP in working.columns:
        working[TIMESTAMP] = _parse_timestamps(working[TIMESTAMP], timezone)
    else:
        working[TIMESTAMP] = pd.NaT

    for column in METRIC_COLUMNS:
        working[column] = pd.to_numeric(working[column], errors="coerce")

    if CONDITION in working.columns:
        working[CONDITION] = working[CONDITION].map(schema.normalize_condition)

    if SUBJECT in working.columns:
        working[SUBJECT] = working[SUBJECT].map(schema.normalize_subject)
    else:
        working[SUBJECT] = pd.NA

    if SOURCE in working.columns:
        filled = working[SOURCE].astype("string").str.strip()
        working[SOURCE] = filled.where(filled.notna() & (filled != ""), source)
    else:
        working[SOURCE] = source

    for column in (FLAGS, NOTES):
        working[column] = working[column].astype("string")

    working = working.dropna(subset=[TIMESTAMP])
    working = working.sort_values(TIMESTAMP, kind="mergesort").reset_index(drop=True)
    dropped = int(rows_read - len(working))
    if dropped > 0:
        warnings.append(f"{dropped} row(s) without a parsable timestamp were dropped")

    metric_present = [c for c in METRIC_COLUMNS if working[c].notna().any()]
    if not metric_present:
        warnings.append("no known metric column (BP, HR, HRV, environment) was found")

    condition_present = bool(working[CONDITION].notna().any()) if CONDITION in working.columns else False
    return LoadResult(
        frame=working,
        source=source,
        mapping=dict(mapping),
        unmapped=list(dict.fromkeys(unmapped)),
        warnings=warnings,
        rows_read=rows_read,
        format=format_name,
        has_condition=condition_present,
    )


# ------------------------------------------------------------------- readers


def load_csv(
    data: Any,
    *,
    source: str = "generic",
    timezone: str = DEFAULT_TIMEZONE,
    encoding: str | None = None,
) -> LoadResult:
    """Load a CSV/TSV export (path, bytes, file object or string)."""
    warnings: List[str] = []
    if isinstance(data, (bytes, bytearray)):
        buffer = io.BytesIO(data)
        probe = data[:4096]
    elif isinstance(data, (str, os.PathLike)) and Path(str(data)).exists():
        buffer = Path(str(data))
        probe = Path(str(data)).read_bytes()[:4096]
    elif hasattr(data, "read"):
        raw = data.read()
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        buffer = io.BytesIO(raw)
        probe = raw[:4096]
    else:
        raw = str(data)
        buffer = io.StringIO(raw)
        probe = raw[:4096].encode("utf-8", errors="ignore")

    text_probe = probe.decode("utf-8", errors="ignore") if isinstance(probe, bytes) else str(probe)
    sep = "\t" if text_probe.count("\t") > text_probe.count(",") else ","
    encoded = encoding
    if encoded is None:
        for candidate in ("utf-8-sig", "utf-8", "cp949", "euc-kr"):
            try:
                if isinstance(buffer, (Path, str)):
                    Path(buffer).read_text(encoding=candidate)  # type: ignore[arg-type]
                encoded = candidate
                break
            except (UnicodeDecodeError, OSError, TypeError):
                continue
        encoded = encoded or "utf-8"

    try:
        raw_frame = pd.read_csv(buffer, sep=sep, encoding=encoded, dtype=str, keep_default_na=False)
    except UnicodeDecodeError:
        if isinstance(buffer, (Path, str)):
            buffer = Path(str(buffer))
        raw_frame = pd.read_csv(buffer, sep=sep, encoding="cp949", dtype=str, keep_default_na=False)
        warnings.append("file decoded as CP949 after UTF-8 failed")
    except pd.errors.ParserError:
        if isinstance(buffer, (Path, str)):
            buffer = Path(str(buffer))
        raw_frame = pd.read_csv(buffer, sep=sep, engine="python", encoding=encoded, dtype=str)
        warnings.append("CSV parsed with the tolerant Python engine")

    rows_read = len(raw_frame)
    raw_frame = raw_frame.replace({"": pd.NA})
    raw_frame.columns = [str(c).strip() for c in raw_frame.columns]

    pivot, pivot_mapping = _pivot_long_format(raw_frame, warnings)
    if pivot is not None:
        mapping, unmapped = _canonical_headers(raw_frame.columns)
        mapping.update(pivot_mapping)
        frame = pivot
    else:
        mapping, unmapped = _canonical_headers(raw_frame.columns)
        frame = _rename_to_standard(raw_frame, mapping)

    if not mapping:
        warnings.append("no header matched a known alias; the table was left unmapped")
    frame = _apply_units(frame, warnings)
    return _finalize(
        frame,
        source=source,
        mapping=mapping,
        unmapped=unmapped,
        warnings=warnings,
        timezone=timezone,
        format_name="csv",
        rows_read=rows_read,
    )


def _flatten_json_records(payload: Any) -> tuple[list[dict], str]:
    """Find the record list in an Oura-style or generic JSON payload."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)], "records"
    if isinstance(payload, dict):
        for key in ("data", "records", "readings", "measurements", "items", "results", "samples"):
            value = payload.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return list(value), key
        # Single object with metric arrays: {timestamp: [...], sbp: [...], ...}
        if payload and all(isinstance(v, list) for v in payload.values()):
            length = max(len(v) for v in payload.values())
            rows = []
            for i in range(length):
                rows.append({k: (v[i] if i < len(v) else None) for k, v in payload.items()})
            return rows, "columns"
        if payload and any(isinstance(v, dict) for v in payload.values()):
            for value in payload.values():
                if isinstance(value, dict) and "data" in value:
                    nested = value["data"]
                    if isinstance(nested, list) and nested and isinstance(nested[0], dict):
                        return list(nested), "data"
        return [payload], "single"
    return [], "empty"


def load_json(
    data: Any,
    *,
    source: str = "generic",
    timezone: str = DEFAULT_TIMEZONE,
) -> LoadResult:
    warnings: List[str] = []
    if isinstance(data, (bytes, bytearray)):
        payload = json.loads(data.decode("utf-8-sig"))
    elif isinstance(data, str) or isinstance(data, os.PathLike):
        text = str(data)
        is_path = False
        if len(text) < 4096:
            try:
                is_path = Path(text).exists()
            except OSError:
                is_path = False
        payload = json.loads(Path(text).read_text(encoding="utf-8-sig")) if is_path else json.loads(text)
    else:
        payload = data

    records, container = _flatten_json_records(payload)
    if not records:
        warnings.append("JSON payload contained no record objects")
    raw_frame = pd.DataFrame(records)
    rows_read = len(raw_frame)

    if "average_hrv" in raw_frame.columns or "average_heart_rate" in raw_frame.columns:
        source = "oura" if source == "generic" else source
        if "bedtime_start" in raw_frame.columns:
            raw_frame["__timestamp"] = raw_frame["bedtime_start"]
        elif "day" in raw_frame.columns:
            warnings.append(
                "Oura nightly aggregates: each row was placed at 03:00 local time of its 'day' "
                "(the nightly window is aggregated by the ring; no per-beat data is available)"
            )
            raw_frame["__timestamp"] = (
                pd.to_datetime(raw_frame["day"], errors="coerce").dt.strftime("%Y-%m-%d")
                + " 03:00:00"
            )
        else:
            raw_frame["__timestamp"] = None

    pivot, pivot_mapping = _pivot_long_format(raw_frame, warnings)
    mapping, unmapped = _canonical_headers(raw_frame.columns)
    if pivot is not None:
        mapping.update(pivot_mapping)
        frame = pivot
    else:
        frame = _rename_to_standard(raw_frame, mapping)
        if "__timestamp" in raw_frame.columns:
            frame[TIMESTAMP] = raw_frame["__timestamp"].to_numpy()
            mapping[TIMESTAMP] = "bedtime_start/day"

    if not mapping:
        warnings.append("no JSON field matched a known alias; the table was left unmapped")
    frame = _apply_units(frame, warnings)
    result = _finalize(
        frame,
        source=source,
        mapping=mapping,
        unmapped=unmapped,
        warnings=warnings,
        timezone=timezone,
        format_name=f"json({container})",
        rows_read=rows_read,
    )
    return result


def load_apple_health_xml(
    path: Any,
    *,
    timezone: str = DEFAULT_TIMEZONE,
    include_heart_rate: bool = True,
) -> LoadResult:
    """Stream an Apple Health ``export.xml`` and keep BP / HR / HRV records.

    Only the record types HEARTMETRIC uses are read; the file is streamed so a
    multi-hundred-megabyte HealthKit export does not have to fit in memory.
    """
    wanted = {
        "HKQuantityTypeIdentifierBloodPressureSystolic": "sbp",
        "HKQuantityTypeIdentifierBloodPressureDiastolic": "dbp",
        "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "sdnn",
        "HKQuantityTypeIdentifierHeartRate": "hr",
        "HKQuantityTypeIdentifierRestingHeartRate": "hr",
    }
    if not include_heart_rate:
        wanted.pop("HKQuantityTypeIdentifierHeartRate", None)
        wanted.pop("HKQuantityTypeIdentifierRestingHeartRate", None)

    warnings: List[str] = []
    rows: dict[str, dict[str, Any]] = {}
    rows_read = 0
    source_path = Path(str(path))

    for event, element in ET.iterparse(source_path, events=("end",)):
        if not element.tag.endswith("Record"):
            continue
        kind = element.get("type", "")
        metric = wanted.get(kind)
        if metric is None:
            continue
        if element.get("value") in (None, ""):
            element.clear()
            continue
        rows_read += 1
        start = element.get("startDate") or element.get("creationDate")
        unit = (element.get("unit") or "").lower()
        value = float(str(element.get("value")).replace(",", ""))
        if metric in ("sbp", "dbp") and unit in ("kpa",):
            value *= 7.50062
        record = rows.setdefault(start, {TIMESTAMP: start, SOURCE: "apple_health"})
        # A single measurement session writes systolic and diastolic with the
        # same startDate; HRV/HR records keep the finest value of the moment.
        if metric in record and metric in ("hr", "sdnn"):
            continue
        record[metric] = value
        element.clear()

    frame = pd.DataFrame(list(rows.values()))
    if frame.empty:
        frame = schema.empty_frame()
        warnings.append("no blood pressure, heart rate or HRV record was found in the XML")
    else:
        if not (frame.get("sbp", pd.Series(dtype=float)).notna().any()):
            warnings.append("XML contained no systolic/diastolic pairs (no cuff BP records)")
        if "rmssd" not in frame.columns or not frame.get("rmssd", pd.Series(dtype=float)).notna().any():
            warnings.append(
                "Apple Health stores HRV as SDNN, not RMSSD; only SDNN is available from this file"
            )
    mapping = {TIMESTAMP: "startDate", SOURCE: "export.xml"}
    hk_types = {
        "sbp": "HKQuantityTypeIdentifierBloodPressureSystolic",
        "dbp": "HKQuantityTypeIdentifierBloodPressureDiastolic",
        "hr": "HKQuantityTypeIdentifierHeartRate",
        "sdnn": "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    }
    for column in ("sbp", "dbp", "hr", "sdnn"):
        if column in frame.columns:
            mapping[column] = hk_types[column]
    return _finalize(
        frame,
        source="apple_health",
        mapping=mapping,
        unmapped=[],
        warnings=warnings,
        timezone=timezone,
        format_name="apple_health_xml",
        rows_read=rows_read,
    )


def detect_source(name: str, frame: pd.DataFrame | None = None) -> str:
    lowered = str(name).lower()
    if "oura" in lowered:
        return "oura"
    if "apple" in lowered or "health" in lowered:
        return "apple_health"
    if frame is not None:
        columns = {schema.normalize_key(c) for c in frame.columns}
        if {"averagehrv", "averageheartrate"} & columns:
            return "oura"
    return "generic"


def load_file(
    path: Any,
    *,
    source: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    condition: str | None = None,
) -> LoadResult:
    """Load any supported file by extension (CSV, TSV, JSON, Apple Health XML)."""
    path = Path(str(path))
    if not path.exists():
        raise FileNotFoundError(f"input file not found: {path}")
    guessed = source or detect_source(path.name)
    suffix = path.suffix.lower()
    if suffix in (".csv", ".tsv", ".txt"):
        result = load_csv(path, source=guessed, timezone=timezone)
    elif suffix == ".json":
        result = load_json(path, source=guessed, timezone=timezone)
    elif suffix == ".xml":
        result = load_apple_health_xml(path, timezone=timezone)
    else:
        raise ValueError(f"unsupported file type: {suffix or path.name}")
    if condition:
        result.frame[CONDITION] = schema.normalize_condition(condition)
        result.mapping[CONDITION] = "argument"
        result.has_condition = True
    return result


def load_any(
    data: Any,
    *,
    name: str = "input",
    source: str | None = None,
    timezone: str = DEFAULT_TIMEZONE,
    condition: str | None = None,
) -> LoadResult:
    """Load from bytes/text/path, guessing the format from content."""
    guessed = source or detect_source(name)
    if isinstance(data, (bytes, bytearray)):
        head = bytes(data[:400]).lstrip()
        text = head.decode("utf-8", errors="ignore")
        if head.startswith(b"<") or text.startswith("<?xml"):
            # Write to a temporary buffer because iterparse needs a file.
            import tempfile

            with tempfile.NamedTemporaryFile("wb", suffix=".xml", delete=False) as handle:
                handle.write(bytes(data))
                temp_path = handle.name
            try:
                return load_apple_health_xml(temp_path, timezone=timezone)
            finally:
                os.unlink(temp_path)
        if text.startswith("{") or text.startswith("["):
            return load_json(data, source=guessed, timezone=timezone)
        return load_csv(data, source=guessed, timezone=timezone)
    if isinstance(data, (str, os.PathLike)) and Path(str(data)).exists():
        return load_file(data, source=source, timezone=timezone, condition=condition)
    if isinstance(data, str):
        stripped = data.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return load_json(data, source=guessed, timezone=timezone)
        if stripped.startswith("<"):
            return load_apple_health_xml(data, timezone=timezone)
        return load_csv(data, source=guessed, timezone=timezone)
    raise TypeError(f"unsupported input type: {type(data)!r}")


def merge(results: Sequence[LoadResult], how: str = "outer") -> pd.DataFrame:
    """Merge several loaded tables into one standard table on timestamp.

    Streams are combined row-wise (a long table already), not wide-joined, so a
    cuff reading at 07:00 and an Oura HRV aggregate at 03:00 stay distinct rows;
    the analysis joins them per time window instead of forcing a same-second
    match. Values that share an exact timestamp and condition are coalesced.
    """
    frames = [r.frame for r in results if not r.frame.empty]
    if not frames:
        return schema.empty_frame()
    combined = pd.concat(frames, ignore_index=True)
    for column in STANDARD_COLUMNS:
        if column not in combined.columns:
            combined[column] = pd.NA
    combined = combined[list(STANDARD_COLUMNS)]
    combined = combined.sort_values(TIMESTAMP, kind="mergesort").reset_index(drop=True)
    if how == "outer":
        return combined
    if how == "inner":
        keys = [TIMESTAMP, CONDITION]
        grouped = combined.groupby(keys, dropna=False, as_index=False).first()
        return grouped
    raise ValueError(f"unsupported merge strategy: {how}")
