"""End-to-end analysis pipeline shared by the CLI, the API and the exporter."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import __version__, cleaner, loader, metrics, stats
from .schema import CONDITION, TIMESTAMP

DEFAULT_METRICS = ["sbp", "dbp", "map", "pp", "hr", "rmssd", "sdnn"]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat(sep=" ")
    if value is pd.NaT:
        return None
    return value


def analyze(
    frame: pd.DataFrame,
    *,
    group_a: str = "forest",
    group_b: str = "urban",
    paired: bool = False,
    night: tuple[int, int] = metrics.DEFAULT_NIGHT,
    gap_hours: float = cleaner.DEFAULT_GAP_HOURS,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clean a standard table and compute every metric HEARTMETRIC reports."""
    report = cleaner.clean(frame, gap_hours=gap_hours)
    cleaned = metrics.add_derived(report.frame)

    summary = metrics.summarize(cleaned)
    summary["dipping"] = metrics.nocturnal_dipping(cleaned, "sbp", night=night)
    summary["dipping_dbp"] = metrics.nocturnal_dipping(cleaned, "dbp", night=night)
    summary["hrv_recovery"] = metrics.hrv_recovery(cleaned, night=night)

    conditions = metrics.condition_summary(cleaned)
    exposure = metrics.exposure_profile(cleaned)
    comparison = stats.compare_table(
        cleaned,
        metric_columns=DEFAULT_METRICS,
        group_a=group_a,
        group_b=group_b,
        paired=paired,
    )
    daily = metrics.daily_table(cleaned)
    correlations = metrics.correlation_table(cleaned)
    series = metrics.time_series(cleaned)

    bundle: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "heartmetric_version": __version__,
            "license": "MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University",
            "comparison": {"a": group_a, "b": group_b, "paired": paired},
            "night_window": f"{night[0]:02d}:00–{night[1]:02d}:00",
            "disclaimer": "Research summary of the submitted series. Not a medical diagnosis; "
            "a cuff measurement and a clinician remain the reference.",
        },
        "quality": report.to_dict(),
        "summary": summary,
        "conditions": conditions.to_dict(orient="records"),
        "exposure": exposure.to_dict(orient="records"),
        "comparison": comparison.to_dict(orient="records"),
        "daily": daily.to_dict(orient="records"),
        "correlations": correlations.to_dict(orient="records"),
        "series": series,
    }
    if metadata:
        bundle["meta"]["input"] = metadata
    return _json_safe(bundle)


def analyze_loaded(
    result: loader.LoadResult,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Run :func:`analyze` on a loader result, keeping the load report."""
    bundle = analyze(
        result.frame,
        metadata={"loader": result.summary()},
        **kwargs,
    )
    bundle["loader"] = result.summary()
    bundle["warnings"] = list(dict.fromkeys(result.warnings + bundle["quality"].get("warnings", [])))
    return bundle


def analyze_file(path: str, **kwargs: Any) -> Dict[str, Any]:
    return analyze_loaded(loader.load_file(path), **kwargs)


def demo_bundle(**kwargs: Any) -> Dict[str, Any]:
    """The bundled 14-day urban vs forest demonstration analysis."""
    from . import synthetic

    frame = synthetic.generate()
    bundle = analyze(frame, metadata={"data": "synthetic", **synthetic.metadata()}, **kwargs)
    bundle["meta"]["demo"] = True
    return bundle
