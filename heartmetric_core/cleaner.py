"""Data quality checks for the HEARTMETRIC standard table.

Rules are deliberately conservative: a value is removed from the analysis only
when it is physiologically impossible or internally contradictory. Everything
that is merely unusual (wide pulse pressure, reversed nocturnal dipping, a long
gap) is kept and flagged, because those are the observations the study is
looking for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .schema import CONDITION, FLAGS, METRIC_COLUMNS, SOURCE, STANDARD_COLUMNS, TIMESTAMP

#: Hard physiological plausibility windows. Outside these a reading is treated
#: as an entry/device error and removed (never silently — every removal is
#: counted in the report).
PHYSIOLOGICAL_RANGES: Dict[str, tuple[float, float]] = {
    "sbp": (60.0, 260.0),
    "dbp": (30.0, 160.0),
    "hr": (25.0, 220.0),
    "rmssd": (1.0, 300.0),
    "sdnn": (1.0, 400.0),
    "temp_c": (-40.0, 55.0),
    "humidity_pct": (0.0, 100.0),
    "pm25": (0.0, 1000.0),
    "pm10": (0.0, 1500.0),
    "green_index": (0.0, 1.0),
    "forest": (0.0, 1.0),
    "activity": (0.0, 300.0),
    "steps": (0.0, 100000.0),
}

#: A pulse pressure wider than this is flagged (not removed): arterial
#: stiffness signal, common in older adults.
WIDE_PULSE_PRESSURE = 100.0

#: Gaps longer than this are reported so a researcher knows a period is empty.
DEFAULT_GAP_HOURS = 6.0


@dataclass
class CleanReport:
    """Result of :func:`clean` — the cleaned frame and everything it lost."""

    frame: pd.DataFrame
    rows_in: int = 0
    rows_out: int = 0
    duplicates_removed: int = 0
    removed_out_of_range: Dict[str, int] = field(default_factory=dict)
    removed_inconsistent: int = 0
    flagged_rows: int = 0
    missing_pct: Dict[str, float] = field(default_factory=dict)
    max_gap_hours: float = 0.0
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    conditions: Dict[str, int] = field(default_factory=dict)
    span: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when the table is usable for at least one summary metric."""
        return self.rows_out > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "rows_removed": self.rows_in - self.rows_out,
            "duplicates_removed": self.duplicates_removed,
            "removed_out_of_range": dict(self.removed_out_of_range),
            "removed_inconsistent": self.removed_inconsistent,
            "flagged_rows": self.flagged_rows,
            "missing_pct": dict(self.missing_pct),
            "max_gap_hours": self.max_gap_hours,
            "gaps": list(self.gaps),
            "conditions": dict(self.conditions),
            "span": dict(self.span),
            "warnings": list(self.warnings),
            "passed": self.passed,
        }


def _coerce(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    for column in STANDARD_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    for column in METRIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame[TIMESTAMP] = pd.to_datetime(frame[TIMESTAMP], errors="coerce")
    frame[FLAGS] = frame[FLAGS].astype("object")
    return frame[list(STANDARD_COLUMNS)]


def _add_flag(frame: pd.DataFrame, mask: pd.Series, code: str) -> None:
    if not mask.any():
        return
    positions = np.flatnonzero(np.asarray(mask.fillna(False), dtype=bool))
    column = frame[FLAGS].astype("object").to_numpy(copy=True)
    for position in positions:
        old = column[position]
        column[position] = f"{old}|{code}" if isinstance(old, str) and old else code
    frame[FLAGS] = pd.Series(column, index=frame.index, dtype="object")


def _gap_table(times: pd.Series, gap_hours: float) -> tuple[float, List[Dict[str, Any]]]:
    if len(times) < 2:
        return 0.0, []
    ordered = times.sort_values()
    deltas = ordered.diff().dt.total_seconds() / 3600.0
    deltas = deltas.dropna()
    if deltas.empty:
        return 0.0, []
    gaps = []
    for position, hours in deltas.items():
        if hours >= gap_hours:
            start = ordered.shift(1).loc[position]
            gaps.append(
                {
                    "from": start.isoformat(sep=" "),
                    "to": ordered.loc[position].isoformat(sep=" "),
                    "hours": round(float(hours), 2),
                }
            )
    return float(deltas.max()), gaps


def clean(
    frame: pd.DataFrame,
    *,
    gap_hours: float = DEFAULT_GAP_HOURS,
    dedupe_seconds: int = 60,
    drop_out_of_range: bool = True,
) -> CleanReport:
    """Check ranges, consistency, duplicates and time alignment.

    Parameters
    ----------
    frame:
        A standard-schema table (see :mod:`heartmetric_core.loader`).
    gap_hours:
        Report a coverage gap when two consecutive rows are this far apart.
    dedupe_seconds:
        Two rows of the same condition with identical values within this many
        seconds are treated as one measurement (a double-tapped sync).
    drop_out_of_range:
        When ``False`` the values are flagged but kept (audit mode).
    """
    working = _coerce(frame)
    rows_in = len(working)
    warnings: List[str] = []

    working = working.dropna(subset=[TIMESTAMP])
    if rows_in - len(working):
        warnings.append(f"{rows_in - len(working)} row(s) without a timestamp were dropped")

    working = working.sort_values(TIMESTAMP, kind="mergesort").reset_index(drop=True)

    # ---- exact duplicates -------------------------------------------------
    value_columns = [TIMESTAMP, CONDITION, *METRIC_COLUMNS]
    before = len(working)
    working = working.drop_duplicates(subset=value_columns, keep="first").reset_index(drop=True)
    duplicates_removed = before - len(working)

    # ---- near duplicates (repeated sync within dedupe_seconds) ------------
    if dedupe_seconds > 0 and len(working) > 1:
        key = working[["sbp", "dbp", "hr"]].round(1)
        signature = key.apply(
            lambda row: "|".join("" if pd.isna(v) else f"{float(v):.1f}" for v in row), axis=1
        )
        previous_time = working[TIMESTAMP].shift(1)
        within_window = (working[TIMESTAMP] - previous_time).dt.total_seconds().abs() <= dedupe_seconds
        same_signature = signature == signature.shift(1)
        same_condition = working[CONDITION].fillna("~") == working[CONDITION].fillna("~").shift(1)
        duplicate_mask = within_window & same_signature & same_condition
        duplicate_mask.fillna(False, inplace=True)
        if duplicate_mask.any():
            duplicates_removed += int(duplicate_mask.sum())
            working = working.loc[~duplicate_mask].reset_index(drop=True)

    # ---- physiological ranges --------------------------------------------
    removed_out_of_range: Dict[str, int] = {}
    for column, (low, high) in PHYSIOLOGICAL_RANGES.items():
        if column not in working.columns:
            continue
        values = working[column]
        invalid = values.notna() & ((values < low) | (values > high))
        count = int(invalid.sum())
        if not count:
            continue
        removed_out_of_range[column] = count
        _add_flag(working, invalid, f"{column}_range")
        if drop_out_of_range:
            working.loc[invalid, column] = np.nan

    # ---- internal consistency --------------------------------------------
    sbp, dbp = working["sbp"], working["dbp"]
    inverted = sbp.notna() & dbp.notna() & (sbp <= dbp)
    removed_inconsistent = int(inverted.sum())
    if removed_inconsistent:
        _add_flag(working, inverted, "sbp_le_dbp")
        working.loc[inverted, ["sbp", "dbp"]] = np.nan

    wide_pp = sbp.notna() & dbp.notna() & ((sbp - dbp) > WIDE_PULSE_PRESSURE)
    if wide_pp.any():
        _add_flag(working, wide_pp, "wide_pulse_pressure")

    hrv_conflict = (
        working["rmssd"].notna()
        & working["sdnn"].notna()
        & (working["rmssd"] > working["sdnn"] * 1.5)
    )
    if hrv_conflict.any():
        _add_flag(working, hrv_conflict, "rmssd_gt_sdnn")
        warnings.append(
            "RMSSD exceeded SDNN in some rows; usually a unit or device mismatch — flagged, not removed"
        )

    if "forest" in working.columns:
        forest = working["forest"].dropna()
        outside = forest[(forest != 0) & (forest != 1)]
        if len(outside):
            warnings.append("forest flag outside {0,1} was treated as missing")
            working.loc[working["forest"].notna() & ~working["forest"].isin([0, 1]), "forest"] = np.nan

    # ---- coverage ---------------------------------------------------------
    max_gap, gaps = _gap_table(working[TIMESTAMP], gap_hours)
    if gaps:
        warnings.append(
            f"{len(gaps)} coverage gap(s) of {gap_hours:g} h or more; comparisons across a gap are reported, not corrected"
        )

    missing_pct = {
        column: round(float(working[column].isna().mean() * 100), 1)
        for column in METRIC_COLUMNS
        if column in working.columns
    }

    conditions = (
        working[CONDITION].fillna("(unlabelled)").astype(str).value_counts().to_dict()
        if CONDITION in working.columns
        else {}
    )

    span: Dict[str, str] = {}
    if len(working):
        span = {
            "start": pd.Timestamp(working[TIMESTAMP].min()).isoformat(sep=" "),
            "end": pd.Timestamp(working[TIMESTAMP].max()).isoformat(sep=" "),
            "days": str(round((working[TIMESTAMP].max() - working[TIMESTAMP].min()).total_seconds() / 86400 + 1e-9, 2)),
        }

    flagged = int(working[FLAGS].notna().sum()) if FLAGS in working.columns else 0
    working = working.reset_index(drop=True)

    return CleanReport(
        frame=working,
        rows_in=rows_in,
        rows_out=len(working),
        duplicates_removed=duplicates_removed,
        removed_out_of_range=removed_out_of_range,
        removed_inconsistent=removed_inconsistent,
        flagged_rows=flagged,
        missing_pct=missing_pct,
        max_gap_hours=round(max_gap, 2),
        gaps=gaps,
        conditions=conditions,
        span=span,
        warnings=warnings,
    )


def quality_summary(frame: pd.DataFrame) -> Dict[str, Any]:
    """A quick coverage view (used by the web workbench's QC panel)."""
    if frame is None or frame.empty:
        return {"rows": 0, "metrics": {}}
    report = clean(frame)
    return report.to_dict()
