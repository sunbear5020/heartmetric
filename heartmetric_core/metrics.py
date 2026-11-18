"""Cardiovascular and environmental metrics for HEARTMETRIC.

All indices here are *research* descriptors of a person's own time series. They
are not diagnostic thresholds and must not be read as a clinical assessment
(see NOTICE.md). Where a reference value is used it is named in the docstring.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

import numpy as np
import pandas as pd

from .schema import CONDITION, FLAGS, METRIC_COLUMNS, TIMESTAMP

#: Night window used for dipping and HRV recovery (local clock).
DEFAULT_NIGHT = (22, 6)

#: Reference values for the composite indices (documented, adjustable).
REFERENCE = {
    "rmssd_ms": 50.0,      # RMSSD ~50 ms: typical healthy adult nightly average
    "hr_low": 55.0,        # bpm
    "hr_high": 95.0,       # bpm
    "pm25_ugm3": 35.0,     # WHO interim target 1, 24-h mean
    "thermal_center_c": 22.0,
    "thermal_span_c": 15.0,
    "dipping_normal_pct": 15.0,
}

ENVIRONMENT_WEIGHTS = {
    "bp_load": 0.30,
    "hrv_suppression": 0.25,
    "pm25": 0.20,
    "thermal": 0.15,
    "hr_load": 0.10,
}


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce")


def pulse_pressure(sbp: Iterable[float] | pd.Series, dbp: Iterable[float] | pd.Series) -> pd.Series:
    """Systolic − diastolic pressure (mmHg)."""
    return pd.to_numeric(pd.Series(sbp), errors="coerce") - pd.to_numeric(pd.Series(dbp), errors="coerce")


def mean_arterial_pressure(
    sbp: Iterable[float] | pd.Series, dbp: Iterable[float] | pd.Series
) -> pd.Series:
    """MAP = DBP + (SBP − DBP)/3 (mmHg)."""
    s = pd.to_numeric(pd.Series(sbp), errors="coerce")
    d = pd.to_numeric(pd.Series(dbp), errors="coerce")
    return d + (s - d) / 3.0


def add_derived(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with ``map`` and ``pp`` columns added."""
    out = frame.copy()
    out["pp"] = pulse_pressure(out["sbp"], out["dbp"])
    out["map"] = mean_arterial_pressure(out["sbp"], out["dbp"])
    return out


def blood_pressure_load(
    frame: pd.DataFrame, *, sbp_threshold: float = 130.0, dbp_threshold: float = 80.0
) -> Dict[str, Any]:
    """Share of readings above the given thresholds (a load measure, not a diagnosis)."""
    sbp, dbp = _series(frame, "sbp"), _series(frame, "dbp")
    valid = sbp.notna() | dbp.notna()
    n = int(valid.sum())
    if n == 0:
        return {"n": 0, "sbp_load_pct": None, "dbp_load_pct": None, "either_load_pct": None}
    sbp_high = (sbp >= sbp_threshold).fillna(False)
    dbp_high = (dbp >= dbp_threshold).fillna(False)
    return {
        "n": n,
        "sbp_threshold": sbp_threshold,
        "dbp_threshold": dbp_threshold,
        "sbp_load_pct": round(float(sbp_high.sum()) / n * 100, 1),
        "dbp_load_pct": round(float(dbp_high.sum()) / n * 100, 1),
        "either_load_pct": round(float((sbp_high | dbp_high).sum()) / n * 100, 1),
    }


def _night_mask(times: pd.Series, night: tuple[int, int] = DEFAULT_NIGHT) -> pd.Series:
    start, end = night
    hours = pd.to_datetime(times).dt.hour
    if start > end:  # window crosses midnight
        return (hours >= start) | (hours < end)
    return (hours >= start) & (hours < end)


def nocturnal_dipping(
    frame: pd.DataFrame,
    metric: str = "sbp",
    *,
    night: tuple[int, int] = DEFAULT_NIGHT,
    min_readings: int = 2,
) -> Dict[str, Any]:
    """Nocturnal dipping (%): (day mean − night mean) / day mean × 100.

    Classification follows the usual ambulatory-BP convention:
    normal 10–20 %, non-dipper 0–10 %, reverse dipper < 0 %, extreme dipper > 20 %.
    """
    if frame is None or frame.empty or metric not in frame.columns:
        return {"metric": metric, "available": False, "reason": "no data"}
    values = _series(frame, metric)
    times = pd.to_datetime(frame[TIMESTAMP], errors="coerce")
    is_night = _night_mask(times, night)
    day_values = values[~is_night].dropna()
    night_values = values[is_night].dropna()
    if len(day_values) < min_readings or len(night_values) < min_readings:
        return {
            "metric": metric,
            "available": False,
            "reason": f"needs at least {min_readings} day and {min_readings} night readings "
            f"(have {len(day_values)} / {len(night_values)})",
            "n_day": int(len(day_values)),
            "n_night": int(len(night_values)),
        }
    day_mean = float(day_values.mean())
    night_mean = float(night_values.mean())
    dipping = (day_mean - night_mean) / day_mean * 100.0 if day_mean else float("nan")
    if dipping < 0:
        category = "reverse dipper"
    elif dipping < 10:
        category = "non-dipper"
    elif dipping <= 20:
        category = "normal dipping"
    else:
        category = "extreme dipper"
    return {
        "metric": metric,
        "available": True,
        "day_mean": round(day_mean, 1),
        "night_mean": round(night_mean, 1),
        "dipping_pct": round(float(dipping), 1),
        "category": category,
        "n_day": int(len(day_values)),
        "n_night": int(len(night_values)),
        "night_window": f"{night[0]:02d}:00–{night[1]:02d}:00",
    }


def hrv_recovery(
    frame: pd.DataFrame,
    *,
    metric: str = "rmssd",
    night: tuple[int, int] = DEFAULT_NIGHT,
    min_readings: int = 2,
) -> Dict[str, Any]:
    """Night-to-day HRV ratio as a recovery index (100 = no night rise).

    When a table has no night readings (for example a daytime-only wearable
    export) the first reading of each day is used as the resting baseline.
    """
    if frame is None or frame.empty or metric not in frame.columns:
        return {"metric": metric, "available": False, "reason": "no data"}
    values = _series(frame, metric)
    if not values.notna().any():
        return {"metric": metric, "available": False, "reason": "all values missing"}
    times = pd.to_datetime(frame[TIMESTAMP], errors="coerce")
    is_night = _night_mask(times, night)
    night_values = values[is_night].dropna()
    day_values = values[~is_night].dropna()

    baseline_used = "night"
    if len(night_values) < min_readings or len(day_values) < min_readings:
        baseline_used = "first-of-day"
        working = frame.assign(__value=values).dropna(subset=[TIMESTAMP, "__value"])
        if working.empty:
            return {"metric": metric, "available": False, "reason": "no timestamped values"}
        daily_first = working.sort_values(TIMESTAMP).groupby(working[TIMESTAMP].dt.date)["__value"].first()
        resting = daily_first.dropna()
        daytime = day_values if len(day_values) >= min_readings else values.dropna()
        if len(resting) < min_readings or len(daytime) < min_readings:
            return {"metric": metric, "available": False, "reason": "not enough readings"}
        night_values, day_values = resting, daytime

    resting_mean = float(pd.Series(night_values).mean())
    day_mean = float(pd.Series(day_values).mean())
    if day_mean <= 0:
        return {"metric": metric, "available": False, "reason": "day mean is zero"}
    ratio = resting_mean / day_mean
    index = ratio * 100.0
    if index >= 110:
        band = "enhanced recovery"
    elif index >= 95:
        band = "maintained"
    else:
        band = "blunted"
    return {
        "metric": metric,
        "available": True,
        "baseline": baseline_used,
        "resting_mean_ms": round(resting_mean, 1),
        "day_mean_ms": round(day_mean, 1),
        "ratio": round(float(ratio), 3),
        "index": round(float(index), 1),
        "band": band,
        "n_resting": int(len(night_values)),
        "n_day": int(len(day_values)),
    }


def _clamp01(value: float) -> float:
    if value is None or not np.isfinite(value):
        return float("nan")
    return float(min(max(value, 0.0), 1.0))


def environmental_stress_index(
    frame: pd.DataFrame,
    *,
    weights: Dict[str, float] | None = None,
) -> Dict[str, Any]:
    """Composite 0–100 index of environmental + cardiovascular load.

    Components (weights in :data:`ENVIRONMENT_WEIGHTS`):
      * ``bp_load``          share of readings at or above 130/80 mmHg
      * ``hrv_suppression``  1 − RMSSD / 50 ms
      * ``pm25``             mean PM2.5 / 35 µg/m³ (WHO interim target 1)
      * ``thermal``          |mean temperature − 22 °C| / 15 °C
      * ``hr_load``          mean HR on the 55–95 bpm span
    Components without data are dropped and the remaining weights renormalized.
    This is a laboratory summary, not a health risk score.
    """
    weights = dict(weights or ENVIRONMENT_WEIGHTS)
    components: Dict[str, float] = {}

    load = blood_pressure_load(frame)
    if load["either_load_pct"] is not None:
        components["bp_load"] = load["either_load_pct"]

    rmssd = _series(frame, "rmssd").dropna()
    if len(rmssd):
        components["hrv_suppression"] = _clamp01(1.0 - rmssd.mean() / REFERENCE["rmssd_ms"]) * 100

    pm25 = _series(frame, "pm25").dropna()
    if len(pm25):
        components["pm25"] = _clamp01(pm25.mean() / REFERENCE["pm25_ugm3"]) * 100

    temp = _series(frame, "temp_c").dropna()
    if len(temp):
        deviation = abs(temp.mean() - REFERENCE["thermal_center_c"])
        components["thermal"] = _clamp01(deviation / REFERENCE["thermal_span_c"]) * 100

    hr = _series(frame, "hr").dropna()
    if len(hr):
        span = REFERENCE["hr_high"] - REFERENCE["hr_low"]
        components["hr_load"] = _clamp01((hr.mean() - REFERENCE["hr_low"]) / span) * 100

    if not components:
        return {"available": False, "reason": "no usable component", "components": {}, "index": None}

    active = {k: weights.get(k, 0.0) for k in components}
    total_weight = sum(active.values())
    if total_weight <= 0:
        active = {k: 1.0 for k in components}
        total_weight = float(len(components))
    index = sum(components[k] * active[k] for k in components) / total_weight
    if index < 25:
        band = "low"
    elif index < 50:
        band = "moderate"
    elif index < 75:
        band = "high"
    else:
        band = "very high"
    return {
        "available": True,
        "index": round(float(index), 1),
        "band": band,
        "components": {k: round(float(v), 1) for k, v in components.items()},
        "weights": {k: round(active[k] / total_weight, 3) for k in components},
        "reference": dict(REFERENCE),
        "note": "laboratory summary of the user's own series; not a clinical risk score",
    }


def summarize(frame: pd.DataFrame) -> Dict[str, Any]:
    """One-dictionary overview used by the summary cards and the API."""
    if frame is None or frame.empty:
        return {"available": False, "rows": 0}
    values = {
        "rows": int(len(frame)),
        "days": int(pd.to_datetime(frame[TIMESTAMP]).dt.date.nunique())
        if TIMESTAMP in frame.columns
        else 0,
    }
    for column in ("sbp", "dbp", "hr", "rmssd", "sdnn", "pp", "map", "pm25", "temp_c", "green_index"):
        series = _series(frame, column).dropna()
        if not len(series):
            values[column] = None
            continue
        values[column] = round(float(series.mean()), 1)
        values[f"{column}_sd"] = round(float(series.std(ddof=1)), 1) if len(series) > 1 else 0.0
        values[f"{column}_n"] = int(len(series))
    values.update(
        {
            "bp_load": blood_pressure_load(frame),
            "dipping": nocturnal_dipping(frame, "sbp"),
            "hrv_recovery": hrv_recovery(frame),
            "stress_index": environmental_stress_index(frame),
            "conditions": (
                {str(k): int(v) for k, v in frame[CONDITION].fillna("(unlabelled)").value_counts().items()}
                if CONDITION in frame.columns
                else {}
            ),
        }
    )
    return {"available": True, **values}


def condition_summary(
    frame: pd.DataFrame,
    *,
    metrics: Sequence[str] | None = None,
    by: str = CONDITION,
) -> pd.DataFrame:
    """Mean (and SD) of each metric per condition."""
    if frame is None or frame.empty or by not in frame.columns:
        return pd.DataFrame()
    metrics = list(metrics or ["sbp", "dbp", "map", "pp", "hr", "rmssd", "sdnn", "pm25", "temp_c"])
    metrics = [m for m in metrics if m in frame.columns]
    if not metrics:
        return pd.DataFrame()
    grouped = frame.groupby(frame[by].fillna("(unlabelled)"), dropna=False)
    rows = []
    for name, group in grouped:
        row: Dict[str, Any] = {"condition": str(name), "n": int(len(group))}
        for metric in metrics:
            series = pd.to_numeric(group[metric], errors="coerce").dropna()
            row[metric] = round(float(series.mean()), 1) if len(series) else None
            row[f"{metric}_n"] = int(len(series))
        rows.append(row)
    return pd.DataFrame(rows)


def exposure_profile(frame: pd.DataFrame, by: str = CONDITION) -> pd.DataFrame:
    """Environmental exposure per condition (greenery, particulates, thermal)."""
    columns = ["green_index", "forest", "pm25", "temp_c", "humidity_pct"]
    present = [c for c in columns if c in frame.columns and _series(frame, c).notna().any()]
    if not present:
        return pd.DataFrame()
    return condition_summary(frame, metrics=present, by=by)


def daily_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Per-day aggregates for the time-series charts."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    working = frame.copy()
    working["date"] = pd.to_datetime(working[TIMESTAMP], errors="coerce").dt.strftime("%Y-%m-%d")
    working = working.dropna(subset=["date"])
    if working.empty:
        return pd.DataFrame()
    aggregations: Dict[str, str] = {}
    for column in ("sbp", "dbp", "map", "pp", "hr", "rmssd", "sdnn", "pm25", "temp_c", "green_index"):
        if column in working.columns:
            aggregations[column] = "mean"
    grouped = working.groupby("date", as_index=False).agg(aggregations)
    counts = working.groupby("date", as_index=False).size().rename(columns={"size": "n"})
    result = grouped.merge(counts, on="date", how="left")
    if CONDITION in working.columns:
        labels = (
            working.dropna(subset=[CONDITION])
            .groupby(["date", CONDITION], as_index=False)
            .size()
            .sort_values("size", ascending=False)
            .drop_duplicates("date")[["date", CONDITION]]
            .rename(columns={CONDITION: "dominant_condition"})
        )
        result = result.merge(labels, on="date", how="left")
    for column in result.columns:
        if column in ("date", "dominant_condition", "n"):
            continue
        result[column] = result[column].astype(float).round(1)
    return result


def correlation_table(frame: pd.DataFrame, pairs: Sequence[tuple[str, str]] | None = None) -> pd.DataFrame:
    """Pearson correlation between environmental and cardiovascular columns."""
    pairs = pairs or [
        ("pm25", "sbp"),
        ("pm25", "rmssd"),
        ("temp_c", "hr"),
        ("green_index", "rmssd"),
        ("green_index", "sbp"),
    ]
    rows = []
    for left, right in pairs:
        if left not in frame.columns or right not in frame.columns:
            continue
        a = pd.to_numeric(frame[left], errors="coerce")
        b = pd.to_numeric(frame[right], errors="coerce")
        valid = a.notna() & b.notna()
        if int(valid.sum()) < 3:
            continue
        r = float(np.corrcoef(a[valid], b[valid])[0, 1])
        rows.append({"x": left, "y": right, "r": round(r, 2), "n": int(valid.sum())})
    return pd.DataFrame(rows)


def time_series(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    """Row-wise series for charts (ISO timestamp, condition, metric values)."""
    if frame is None or frame.empty:
        return []
    columns = [TIMESTAMP, CONDITION, "sbp", "dbp", "hr", "rmssd", "pm25", "temp_c", "green_index", FLAGS]
    present = [c for c in columns if c in frame.columns]
    working = frame[present].copy()
    working[TIMESTAMP] = pd.to_datetime(working[TIMESTAMP], errors="coerce")
    working = working.dropna(subset=[TIMESTAMP]).sort_values(TIMESTAMP)
    records = []
    for row in working.itertuples(index=False):
        payload = {"timestamp": row.timestamp.isoformat(sep=" ")}
        for column in present:
            if column == TIMESTAMP:
                continue
            value = getattr(row, column)
            if value is None or (isinstance(value, float) and np.isnan(value)):
                continue
            if column == CONDITION:
                payload["condition"] = str(value)
            elif column == FLAGS:
                payload["flags"] = str(value)
            else:
                payload[column] = round(float(value), 2)
        records.append(payload)
    return records
