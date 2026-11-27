"""End-to-end analysis pipeline shared by the CLI, the API and the exporter."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from . import __version__, cleaner, loader, metrics, provenance, stats
from .schema import CONDITION, SUBJECT, TIMESTAMP

#: Version of the exported bundle format (independent of the package version so a
#: reader can tell a schema change from a feature addition).
SCHEMA_VERSION = "0.3.0"

#: Metrics compared between conditions. They are tested as one family, so the
#: exported table carries BH-FDR q-values and Holm-adjusted p beside the raw p.
DEFAULT_METRICS = ["sbp", "dbp", "map", "pp", "hr", "rmssd", "sdnn", "env_load"]


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
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
    paired_by: str = "auto",
    subject_column: str = SUBJECT,
    night: tuple[int, int] = metrics.DEFAULT_NIGHT,
    gap_hours: float = cleaner.DEFAULT_GAP_HOURS,
    metadata: Optional[Dict[str, Any]] = None,
    alignment: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Clean a standard table and compute every metric HEARTMETRIC reports.

    ``paired_by`` is passed to :func:`heartmetric_core.stats.compare_table`:
    ``"auto"`` pairs by subject when a usable ``subject_id`` exists, otherwise
    pairs observations in time order and records that choice in the output.
    """
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
        paired_by=paired_by,
        subject_column=subject_column,
    )
    daily = metrics.daily_table(cleaned)
    correlations = stats.correlation_table(cleaned)
    series = metrics.time_series(cleaned)

    subject_count = (
        int(cleaned[SUBJECT].dropna().nunique()) if SUBJECT in cleaned.columns else 0
    )
    comparison_payload = comparison.to_dict(orient="records")
    multiple_comparison = comparison.attrs.get("multiple_comparison") or stats.multiple_comparison_summary(
        [row.get("p_value") for row in comparison_payload]
    )
    bundle: Dict[str, Any] = {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "heartmetric_version": __version__,
            "license": "MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University",
            "comparison": {
                "a": group_a,
                "b": group_b,
                "paired": paired,
                "paired_by": (
                    comparison.attrs.get("paired_by")
                    or (comparison_payload[0].get("paired_by") if comparison_payload else None)
                    or ("row" if paired else "unpaired")
                ),
                "subject_column": subject_column if subject_count else None,
                "n_subjects": subject_count,
            },
            "night_window": f"{night[0]:02d}:00–{night[1]:02d}:00",
            "multiple_comparison": multiple_comparison,
            "alignment": alignment,
            "disclaimer": "Research summary of the submitted series. Not a medical diagnosis; "
            "a cuff measurement and a clinician remain the reference.",
        },
        "quality": report.to_dict(),
        "summary": summary,
        "conditions": conditions.to_dict(orient="records"),
        "exposure": exposure.to_dict(orient="records"),
        "comparison": comparison_payload,
        "multiple_comparison": multiple_comparison,
        "daily": daily.to_dict(orient="records"),
        "correlations": correlations.to_dict(orient="records"),
        "series": series,
        "methodology": provenance.methodology(),
    }
    if comparison.attrs.get("skipped"):
        bundle["comparison_skipped"] = comparison.attrs["skipped"]
    if comparison.attrs.get("note"):
        bundle["meta"]["comparison"]["note"] = comparison.attrs["note"]
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


def analyze_streams(
    streams: Any,
    *,
    tolerance_minutes: float = 30.0,
    mode: str = "tolerance",
    anchor: str | None = None,
    conditions: Any = None,
    overnight_lookback_hours: float = 14.0,
    morning_window: tuple[int, int] = (5, 12),
    **kwargs: Any,
) -> Dict[str, Any]:
    """Align several streams/files and analyse the joined table in one call.

    ``streams`` may be paths, raw CSV/JSON text, load results or tables; when
    they are paths, ``conditions`` can label each file (``["forest", None]``).
    ``mode="overnight_morning"`` anchors on a morning cuff reading and looks back
    ``overnight_lookback_hours`` for the night's wearable and environment rows.
    """
    from . import align

    align_kwargs = dict(
        tolerance_minutes=tolerance_minutes,
        mode=mode,
        anchor=anchor,
        overnight_lookback_hours=overnight_lookback_hours,
        morning_window=morning_window,
    )
    if conditions is not None:
        results = []
        for index, item in enumerate(streams):
            condition = conditions[index] if index < len(conditions) else None
            results.append(loader.load_file(item, condition=condition) if isinstance(item, (str, bytes)) else item)
        aligned = align.align_streams(results, **align_kwargs)
        gap_map = align.build_timeline_gap_map(results, aligned.report)
    else:
        aligned = align.align_streams(streams, **align_kwargs)
        gap_map = align.build_timeline_gap_map(streams, aligned.report)

    bundle = analyze(aligned.frame, alignment=aligned.report.to_dict(), **kwargs)
    bundle["alignment"] = aligned.report.to_dict()
    bundle["timeline_gap_map"] = gap_map
    bundle["meta"]["timeline_gap_map"] = gap_map.get("summary", {})
    warnings = list(aligned.report.warnings)
    if gap_map.get("summary", {}).get("missing_dates"):
        warnings.append(
            f"{gap_map['summary']['missing_dates']} date(s) inside the study span had no observation "
            "from at least one stream — see the timeline gap map"
        )
    if warnings:
        bundle["warnings"] = list(dict.fromkeys(bundle.get("warnings", []) + warnings))
    return bundle


def demo_bundle(**kwargs: Any) -> Dict[str, Any]:
    """The bundled 14-day urban vs forest demonstration analysis."""
    from . import synthetic

    frame = synthetic.generate()
    bundle = analyze(frame, metadata={"data": "synthetic", **synthetic.metadata()}, **kwargs)
    bundle["meta"]["demo"] = True
    return bundle


def demo_overnight(**kwargs: Any) -> Dict[str, Any]:
    """The demo split into a nightly wearable file, a morning cuff file and a
    morning environment file, joined with the ``overnight_morning`` preset.

    This is the pattern a single-subject Oura + cuff study actually produces:
    the ring writes one aggregate for the night, the person measures BP after
    waking, and nothing shares a timestamp.
    """
    from . import align, synthetic

    frame = synthetic.generate()
    night = frame[frame[TIMESTAMP].dt.hour == 3][[TIMESTAMP, "hr", "rmssd", "sdnn"]].dropna(subset=["rmssd"]).copy()
    morning = frame[frame[TIMESTAMP].dt.hour == 7][[TIMESTAMP, "condition", "sbp", "dbp"]].dropna(subset=["sbp"]).copy()
    evening = frame[frame[TIMESTAMP].dt.hour.isin([21, 3, 7])][
        [TIMESTAMP, "temp_c", "humidity_pct", "pm25", "pm10", "green_index", "forest"]
    ].copy()
    aligned = align.align_streams(
        [("cuff_morning.csv", morning), ("oura_night.json", night), ("morning_environment.csv", evening)],
        mode="overnight_morning",
    )
    gap_map = align.build_timeline_gap_map(
        [("cuff_morning.csv", morning), ("oura_night.json", night), ("morning_environment.csv", evening)],
        aligned.report,
    )
    bundle = analyze(aligned.frame, alignment=aligned.report.to_dict(), **kwargs)
    bundle["meta"]["demo"] = True
    bundle["meta"]["input"] = {"data": "synthetic", "streams": 3, "preset": "overnight_morning", **synthetic.metadata()}
    bundle["alignment"] = aligned.report.to_dict()
    bundle["timeline_gap_map"] = gap_map
    bundle["meta"]["timeline_gap_map"] = gap_map.get("summary", {})
    return bundle


def demo_streams(**kwargs: Any) -> Dict[str, Any]:
    """The demo split into three files (BP / wearable / environment) and re-joined.

    This exercises the v0.2 alignment path end to end: the same synthetic study
    is written as three separate streams with their own clocks and then aligned.
    """
    from . import align, synthetic

    frame = synthetic.generate()
    bp = frame[[TIMESTAMP, "sbp", "dbp", "condition"]].dropna(subset=["sbp"]).copy()
    wearable = frame[[TIMESTAMP, "hr", "rmssd", "sdnn", "condition"]].dropna(subset=["rmssd"]).copy()
    # the environmental logger writes on its own schedule: 5 minutes later
    environment = frame[[TIMESTAMP, "temp_c", "humidity_pct", "pm25", "pm10", "green_index", "forest", "condition"]].copy()
    environment[TIMESTAMP] = pd.to_datetime(environment[TIMESTAMP]) + pd.Timedelta(minutes=5)

    tolerance = kwargs.pop("tolerance_minutes", 30.0)
    streams = [("cuff_bp.csv", bp), ("wearable.json", wearable), ("environment.csv", environment)]
    aligned = align.align_streams(streams, tolerance_minutes=tolerance)
    bundle = analyze(aligned.frame, alignment=aligned.report.to_dict(), **kwargs)
    bundle["meta"]["demo"] = True
    bundle["meta"]["input"] = {"data": "synthetic", "streams": 3, **synthetic.metadata()}
    bundle["alignment"] = aligned.report.to_dict()
    bundle["timeline_gap_map"] = align.build_timeline_gap_map(streams, aligned.report)
    bundle["meta"]["timeline_gap_map"] = bundle["timeline_gap_map"].get("summary", {})
    return bundle
