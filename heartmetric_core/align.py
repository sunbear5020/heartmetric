"""Time alignment of separate measurement streams onto one standard table.

A study usually arrives as three files, not one:

* a **cuff blood-pressure log** (CSV or an Apple Health export) — SBP/DBP,
* a **wearable HR/HRV export** (Oura JSON, Apple Watch CSV) — HR, RMSSD/SDNN,
* an **environmental exposure log** (temperature, humidity, PM2.5, greenery).

They were recorded by different devices on different clocks, so they almost
never share a timestamp. :func:`align_streams` joins them by *time proximity*
within a tolerance the researcher chooses (``tolerance_minutes``), or by
calendar day when the streams are daily aggregates, instead of forcing an
impossible same-second match.

The join is explicit and auditable
----------------------------------
* Every output row records which streams contributed to it in ``flags``
  (``align:bp+wearable``), so a reader can see what was joined and what was not.
* A row that found no partner is still kept and flagged ``align_unmatched``;
  nothing is dropped and nothing is interpolated.
* :func:`align_streams` returns a :class:`AlignmentReport` alongside the table
  with per-stream row counts, matched and unmatched rows, and the match rate.

No value is ever shifted, averaged across a gap, or copied from another metric:
alignment moves *columns* together in time, it does not change *measurements*.

Three join modes
----------------
``tolerance``
    Point-to-point join within ``tolerance_minutes`` (the v0.2 default).
``daily``
    Per-subject, per-calendar-day mean aggregation, then join on the date.
``overnight_morning`` (v0.3)
    Anchor on a morning cuff reading (default 05:00–12:00) and attach the rows of
the other streams that were recorded in the ``overnight_lookback_hours`` before
it (default 14 h) — the shape an Oura nightly aggregate (placed at 03:00 of its
day) plus a post-waking cuff actually have. The look-back is one-directional: a
reading taken after the cuff is never pulled back onto it, and the lag of every
match is written into the report.

:func:`build_timeline_gap_map` turns the inputs plus the alignment report into a
structured date × stream grid (matched / partial / unmatched / missing) so a
reader can see which days a stream actually covered. It reports; it does not
fill.

License: MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

from . import __version__, loader, schema
from .schema import CONDITION, FLAGS, METRIC_COLUMNS, NOTES, SOURCE, STANDARD_COLUMNS, SUBJECT, TIMESTAMP

#: Metric columns that identify what a stream is measuring.
ROLE_METRICS: Dict[str, Tuple[str, ...]] = {
    "bp": ("sbp", "dbp"),
    "wearable": ("hr", "rmssd", "sdnn"),
    "environment": ("temp_c", "humidity_pct", "pm25", "pm10", "green_index", "forest"),
}

#: Order used to break ties and to pick the default anchor.
ROLE_ORDER: Tuple[str, ...] = ("bp", "wearable", "environment")

#: Tolerances offered by the workbench, kept here so the CLI and the web share them.
TOLERANCE_CHOICES: Tuple[int, ...] = (0, 15, 30, 60, 120)

DEFAULT_TOLERANCE_MINUTES = 30.0


@dataclass
class AlignmentReport:
    """What the alignment understood and what it could not join."""

    mode: str
    tolerance_minutes: float
    anchor: str
    subject_column: str
    streams: List[Dict[str, Any]] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0
    anchors: int = 0
    anchors_matched: int = 0
    rows_with_multiple_streams: int = 0
    warnings: List[str] = field(default_factory=list)
    # --- v0.3 overnight preset -------------------------------------------------
    overnight_lookback_hours: float | None = None
    morning_window: Tuple[int, int] | None = None
    anchors_outside_window: int = 0
    lag_minutes: Dict[str, Any] = field(default_factory=dict)
    matches: List[Dict[str, Any]] = field(default_factory=list)
    unmatched: List[Dict[str, Any]] = field(default_factory=list)
    unmatched_reasons: Dict[str, int] = field(default_factory=dict)
    matches_truncated: bool = False

    @property
    def match_rate_pct(self) -> float:
        if not self.anchors:
            return 0.0
        return round(self.anchors_matched / self.anchors * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "mode": self.mode,
            "tolerance_minutes": self.tolerance_minutes,
            "anchor": self.anchor,
            "subject_column": self.subject_column,
            "streams": list(self.streams),
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "anchors": self.anchors,
            "anchors_matched": self.anchors_matched,
            "match_rate_pct": self.match_rate_pct,
            "rows_with_multiple_streams": self.rows_with_multiple_streams,
            "warnings": list(self.warnings),
        }
        if self.mode == "overnight_morning":
            payload["preset"] = "overnight_morning"
            payload["overnight_lookback_hours"] = self.overnight_lookback_hours
            payload["morning_window"] = list(self.morning_window) if self.morning_window else None
            payload["anchors_outside_window"] = self.anchors_outside_window
            payload["lag_minutes"] = dict(self.lag_minutes)
            payload["matches"] = list(self.matches)
            payload["matches_truncated"] = self.matches_truncated
            payload["unmatched"] = list(self.unmatched)
            payload["unmatched_reasons"] = dict(self.unmatched_reasons)
        return payload


@dataclass
class AlignedStreams:
    """Aligned table plus its audit report."""

    frame: pd.DataFrame
    report: AlignmentReport

    def summary(self) -> Dict[str, Any]:
        return {
            "alignment": self.report.to_dict(),
            "rows": int(len(self.frame)),
            "columns": [c for c in self.frame.columns if self.frame[c].notna().any()],
        }


# ------------------------------------------------------------------ utilities


def _standardize(frame: pd.DataFrame) -> pd.DataFrame:
    """Coerce any table into the standard columns (timestamps, numbers, text)."""
    working = frame.copy()
    for column in STANDARD_COLUMNS:
        if column not in working.columns:
            working[column] = pd.NA
    working[TIMESTAMP] = pd.to_datetime(working[TIMESTAMP], errors="coerce")
    for column in METRIC_COLUMNS:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    working[SUBJECT] = working[SUBJECT].map(schema.normalize_subject)
    working[CONDITION] = working[CONDITION].map(schema.normalize_condition)
    working[FLAGS] = working[FLAGS].astype("object")
    working[NOTES] = working[NOTES].astype("object")
    working = working.dropna(subset=[TIMESTAMP]).sort_values(TIMESTAMP, kind="mergesort").reset_index(drop=True)
    return working[list(STANDARD_COLUMNS)]


def stream_role(frame: pd.DataFrame) -> str:
    """Name the measurement role of a stream by the first metric family it holds.

    A full standard table holds all three families and is classified ``bp``: the
    cuff reading is the anchor of a study, and every other stream is joined to
    it. ``wearable`` wins over ``environment`` when a file carries both HR and
    weather columns, which is what a ring export with a temperature field is.
    """
    for role in ROLE_ORDER:
        if any(metric in frame.columns and frame[metric].notna().any() for metric in ROLE_METRICS[role]):
            return role
    return "other"


def _coerce_streams(
    streams: Iterable[Any],
    names: Sequence[str] | None = None,
) -> List[Tuple[str, str, pd.DataFrame]]:
    """Accept LoadResult / DataFrame / (name, object) and return named frames."""
    out: List[Tuple[str, str, pd.DataFrame]] = []
    for index, item in enumerate(streams):
        name: str
        payload: Any
        if isinstance(item, tuple) and len(item) == 2:
            name, payload = str(item[0]), item[1]
        else:
            payload = item
            name = ""
        if isinstance(payload, loader.LoadResult):
            frame = payload.frame
            name = name or payload.source or f"stream{index + 1}"
        elif isinstance(payload, pd.DataFrame):
            frame = payload
            name = name or (names[index] if names and index < len(names) else f"stream{index + 1}")
        else:
            if not name and isinstance(payload, (str, os.PathLike)):
                candidate = Path(str(payload))
                try:
                    if candidate.exists():
                        name = candidate.stem
                except OSError:
                    pass
            loaded = loader.load_any(payload, name=name or f"stream{index + 1}")
            frame = loaded.frame
            name = name or loaded.source or f"stream{index + 1}"
        if names and index < len(names) and not name:
            name = names[index]
        standardized = _standardize(frame)
        out.append((name, stream_role(standardized), standardized))

    # Two files loaded from the same source (both "generic") must stay distinct
    # in the report, or their match counts would be summed as one stream.
    seen: Dict[str, int] = {}
    unique: List[Tuple[str, str, pd.DataFrame]] = []
    for name, role, frame in out:
        seen[name] = seen.get(name, 0) + 1
        label = name if seen[name] == 1 else f"{name}#{seen[name]}"
        unique.append((label, role, frame))
    return unique


def _subject_key(value: Any) -> str:
    text = schema.normalize_subject(value)
    return text if text is not None else ""


def _day_of(timestamp: Any) -> str:
    """Calendar day of a timestamp as ``YYYY-MM-DD`` (the gap-map column)."""
    try:
        return pd.Timestamp(timestamp).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _in_window(timestamp: Any, window: Tuple[int, int]) -> bool:
    """Is the wall-clock time inside ``(start_hour, end_hour)`` (end exclusive)?"""
    start, end = int(window[0]), int(window[1])
    try:
        stamp = pd.Timestamp(timestamp)
    except (TypeError, ValueError):
        return False
    hour = stamp.hour + stamp.minute / 60.0 + stamp.second / 3600.0
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def _lag_summary(lags: Sequence[float]) -> Dict[str, Any]:
    """Describe the matched lags without inventing a value for an empty list."""
    values = [float(v) for v in lags if v is not None and np.isfinite(v)]
    if not values:
        return {"n": 0}
    array = np.asarray(values, dtype=float)
    return {
        "n": int(array.size),
        "min": round(float(array.min()), 1),
        "median": round(float(np.median(array)), 1),
        "mean": round(float(array.mean()), 1),
        "max": round(float(array.max()), 1),
        "unit": "minutes before the anchor (look-back only)",
    }


def _coalesce(target: Dict[str, Any], source: Dict[str, Any], conflicts: List[str]) -> None:
    """Fill only empty cells of ``target`` from ``source`` (never overwrite)."""
    for column in METRIC_COLUMNS:
        value = source.get(column)
        if value is None or (isinstance(value, float) and not np.isfinite(value)):
            continue
        current = target.get(column)
        if current is None or (isinstance(current, float) and not np.isfinite(current)):
            target[column] = value
        elif column in ("sbp", "dbp", "hr", "rmssd", "sdnn"):
            conflicts.append(column)
    if not target.get(CONDITION) and source.get(CONDITION):
        target[CONDITION] = source[CONDITION]
    if not target.get(SUBJECT) and source.get(SUBJECT):
        target[SUBJECT] = source[SUBJECT]
    if source.get(NOTES) and not target.get(NOTES):
        target[NOTES] = source[NOTES]


def _add_flag(row: Dict[str, Any], code: str) -> None:
    existing = row.get(FLAGS)
    if isinstance(existing, str) and existing and code not in existing.split("|"):
        row[FLAGS] = f"{existing}|{code}"
    elif not existing:
        row[FLAGS] = code


def _frames_to_records(frame: pd.DataFrame) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for row in frame.to_dict(orient="records"):
        payload = dict(row)
        payload[TIMESTAMP] = pd.Timestamp(row[TIMESTAMP])
        for column in METRIC_COLUMNS:
            value = payload.get(column)
            payload[column] = float(value) if value is not None and pd.notna(value) else None
        records.append(payload)
    return records


# ------------------------------------------------------------------ alignment


def align_streams(
    streams: Iterable[Any],
    *,
    tolerance_minutes: float = DEFAULT_TOLERANCE_MINUTES,
    mode: str = "tolerance",
    anchor: str | None = None,
    subject_column: str = SUBJECT,
    names: Sequence[str] | None = None,
    overnight_lookback_hours: float = 14.0,
    morning_window: Tuple[int, int] = (5, 12),
) -> AlignedStreams:
    """Join separate BP / wearable / environment streams into one table.

    Parameters
    ----------
    streams:
        Load results, standard tables or raw CSV/JSON text/paths. Each stream is
        classified by the metrics it carries (``bp``, ``wearable``,
        ``environment``).
    tolerance_minutes:
        Maximum absolute time difference, in minutes, for two rows to be joined.
        ``0`` joins only rows with exactly the same timestamp.
    mode:
        ``"tolerance"`` joins single measurements by time proximity.
        ``"daily"`` aggregates each stream per subject and calendar day first
        (mean of each metric) and joins on the date.
        ``"overnight_morning"`` anchors on a morning cuff reading and joins only
        the rows recorded in the hours *before* it (see below).
    anchor:
        Role whose rows become the output rows ("bp" by default). Rows of other
        streams that find no anchor within tolerance are kept separately,
        flagged ``align_unmatched``.
    subject_column:
        Column that must match before rows can be joined. Rows without a
        subject id are treated as one anonymous subject.
    overnight_lookback_hours:
        With ``mode="overnight_morning"``, how far back from a morning cuff the
        night's rows may be attached (default 14 h). The window is one-sided: an
        observation after the cuff is never pulled onto it.
    morning_window:
        ``(start_hour, end_hour)`` in local wall-clock hours that a cuff reading
        must fall inside to become an overnight anchor (default ``(5, 12)``).
        The end hour is exclusive.

    Returns
    -------
    AlignedStreams
        ``frame`` (the standard table) and ``report`` (match counts).
    """
    named = _coerce_streams(streams, names)
    if not named:
        empty = schema.empty_frame()
        return AlignedStreams(empty, AlignmentReport(mode=mode, tolerance_minutes=tolerance_minutes, anchor="—", subject_column=subject_column))

    mode = str(mode or "tolerance").lower()
    if mode not in {"tolerance", "daily", "overnight_morning"}:
        raise ValueError(f"unsupported alignment mode: {mode}")

    roles_present = [role for _, role, _ in named]
    chosen_anchor = anchor or next((role for role in ROLE_ORDER if role in roles_present), roles_present[0])
    if mode == "daily":
        chosen_anchor_frame = next((f for _, r, f in named if r == chosen_anchor), named[0][2])
        return _align_daily(named, chosen_anchor, subject_column, chosen_anchor_frame)
    if mode == "overnight_morning":
        return _align_overnight_morning(
            named,
            chosen_anchor,
            subject_column,
            overnight_lookback_hours=overnight_lookback_hours,
            morning_window=morning_window,
        )

    return _align_tolerance(named, chosen_anchor, float(tolerance_minutes), subject_column)


def _align_tolerance(
    named: Sequence[Tuple[str, str, pd.DataFrame]],
    anchor_role: str,
    tolerance_minutes: float,
    subject_column: str,
) -> AlignedStreams:
    tolerance = float(max(tolerance_minutes, 0.0)) * 60.0
    records: List[Dict[str, Any]] = []
    stream_rows: List[Dict[str, Any]] = []
    for name, role, frame in named:
        for record in _frames_to_records(frame):
            record["__stream"] = name
            record["__role"] = role
            record["__assigned"] = False
            records.append(record)
        stream_rows.append(
            {
                "name": name,
                "role": role,
                "rows": int(len(frame)),
                "metrics": [m for m in METRIC_COLUMNS if m in frame.columns and frame[m].notna().any()],
            }
        )

    warnings: List[str] = []
    if not records:
        return AlignedStreams(schema.empty_frame(), AlignmentReport(
            mode="tolerance", tolerance_minutes=float(tolerance_minutes), anchor=anchor_role,
            subject_column=subject_column, streams=stream_rows, warnings=["no rows to align"],
        ))

    anchor_index = [i for i, r in enumerate(records) if r["__role"] == anchor_role]
    if not anchor_index:
        warnings.append(f"anchor role '{anchor_role}' has no rows; the first stream was used instead")
        anchor_index = [i for i, r in enumerate(records) if r["__stream"] == records[0]["__stream"]]

    # Subject matching: two rows carrying subject ids must agree. A stream with
    # no subject id at all (a single-subject device export) may join only when
    # the table describes one subject — otherwise guessing would mix people.
    known_subjects = {_subject_key(r.get(SUBJECT)) for r in records if _subject_key(r.get(SUBJECT))}
    single_subject = len(known_subjects) <= 1
    unlabelled_joins = 0
    blocked_unlabelled = 0

    def _subjects_compatible(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        nonlocal unlabelled_joins, blocked_unlabelled
        a, b = _subject_key(left.get(SUBJECT)), _subject_key(right.get(SUBJECT))
        if a and b:
            return a == b
        if a or b:
            if single_subject:
                unlabelled_joins += 1
                return True
            blocked_unlabelled += 1
            return False
        return True

    # Greedy nearest-first matching: each non-anchor row is joined to at most
    # one anchor and each anchor receives at most one row per role.
    roles = [role for role in ROLE_ORDER if role in {r["__role"] for r in records} and role != anchor_role]
    roles += sorted({r["__role"] for r in records} - set(roles) - {anchor_role})
    partner_of: Dict[int, List[int]] = {i: [] for i in anchor_index}
    for role in roles:
        candidates = []
        for index, row in enumerate(records):
            if row["__role"] != role or row["__assigned"]:
                continue
            for anchor_idx in anchor_index:
                anchor_row = records[anchor_idx]
                if not _subjects_compatible(anchor_row, row):
                    continue
                delta = abs((row[TIMESTAMP] - anchor_row[TIMESTAMP]).total_seconds())
                if delta <= tolerance:
                    candidates.append((delta, anchor_idx, index))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        taken_anchor: set[int] = set()
        taken_row: set[int] = set()
        for delta, anchor_idx, index in candidates:
            if index in taken_row or anchor_idx in taken_anchor:
                continue
            partner_of[anchor_idx].append(index)
            taken_anchor.add(anchor_idx)
            taken_row.add(index)
            records[index]["__assigned"] = True

    out: List[Dict[str, Any]] = []
    matched_anchors = 0
    multi = 0
    conflicts = 0
    roles_by_anchor: Dict[int, List[str]] = {}
    for anchor_idx in anchor_index:
        base = {k: v for k, v in records[anchor_idx].items() if not k.startswith("__")}
        partners = partner_of[anchor_idx]
        roles_by_anchor[anchor_idx] = [records[p]["__role"] for p in partners]
        if partners:
            matched_anchors += 1
            local_conflicts: List[str] = []
            for partner in partners:
                _coalesce(base, {k: v for k, v in records[partner].items() if not k.startswith("__")}, local_conflicts)
            conflicts += len(local_conflicts)
            if local_conflicts:
                _add_flag(base, "align_conflict")
        base[SOURCE] = "+".join(
            dict.fromkeys(
                [str(base.get(SOURCE) or "")]
                + [str(records[p].get(SOURCE) or "") for p in partners]
            )
        ).strip("+") or base.get(SOURCE)
        base["__streams"] = "+".join(dict.fromkeys([records[anchor_idx]["__stream"]] + [records[p]["__stream"] for p in partners]))
        _add_flag(base, f"align:{base['__streams']}")
        if len(set(roles_by_anchor[anchor_idx])) > 1 or len(partners) > 1:
            multi += 1
        if not partners:
            _add_flag(base, "align_unmatched")
        out.append(base)

    for index, row in enumerate(records):
        if row["__role"] == anchor_role and index in anchor_index:
            continue
        if row["__assigned"]:
            continue
        base = {k: v for k, v in row.items() if not k.startswith("__")}
        base["__streams"] = row["__stream"]
        _add_flag(base, f"align:{row['__stream']}")
        _add_flag(base, "align_unmatched")
        out.append(base)

    for entry in stream_rows:
        matched = 0
        by_date: Dict[str, Dict[str, int]] = {}
        for index, row in enumerate(records):
            if row["__stream"] != entry["name"]:
                continue
            date = _day_of(row[TIMESTAMP])
            cell = by_date.setdefault(date, {"rows": 0, "matched": 0})
            cell["rows"] += 1
            if row["__assigned"]:
                matched += 1
                cell["matched"] += 1
            elif row["__role"] == anchor_role and index in anchor_index:
                if roles_by_anchor.get(index):
                    matched += 1
                    cell["matched"] += 1
        entry["matched_rows"] = int(matched)
        entry["unmatched_rows"] = int(entry["rows"] - matched)
        entry["match_rate_pct"] = round(matched / entry["rows"] * 100, 1) if entry["rows"] else 0.0
        entry["by_date"] = by_date

    frame = _records_to_frame(out)
    report = AlignmentReport(
        mode="tolerance",
        tolerance_minutes=float(tolerance_minutes),
        anchor=anchor_role,
        subject_column=subject_column,
        streams=stream_rows,
        rows_in=len(records),
        rows_out=len(frame),
        anchors=len(anchor_index),
        anchors_matched=matched_anchors,
        rows_with_multiple_streams=multi,
        warnings=warnings,
    )
    if conflicts:
        report.warnings.append(
            f"{conflicts} value(s) from a second device were kept out because the anchor row already had that metric"
        )
    if unlabelled_joins:
        report.warnings.append(
            f"{unlabelled_joins} row(s) had no subject_id and were joined as the single subject of the table"
        )
    if blocked_unlabelled:
        report.warnings.append(
            f"{blocked_unlabelled} candidate join(s) were refused because one side had no subject_id "
            "while the table holds several subjects — label the stream and align again"
        )
    return AlignedStreams(frame, report)


MATCH_LOG_LIMIT = 500


def _align_overnight_morning(
    named: Sequence[Tuple[str, str, pd.DataFrame]],
    anchor_role: str,
    subject_column: str,
    *,
    overnight_lookback_hours: float = 14.0,
    morning_window: Tuple[int, int] = (5, 12),
) -> AlignedStreams:
    """Attach the night's rows to each morning cuff reading (v0.3 preset).

    The anchor is a cuff row whose wall-clock time falls inside ``morning_window``.
    A row of another stream may join only when it is recorded **at or before** the
    anchor and no further back than ``overnight_lookback_hours``, nearest first and
    at most one row per role per anchor. A night without an observation stays
    empty; the lag of every match and the reason of every miss are reported.
    """
    lookback_hours = float(overnight_lookback_hours) if overnight_lookback_hours is not None else 14.0
    if lookback_hours < 0:
        raise ValueError("overnight_lookback_hours must not be negative")
    window = (int(morning_window[0]), int(morning_window[1]))
    if window[0] == window[1]:
        raise ValueError("morning_window start and end hours must differ")
    lookback_seconds = lookback_hours * 3600.0

    records: List[Dict[str, Any]] = []
    stream_rows: List[Dict[str, Any]] = []
    for name, role, frame in named:
        for record in _frames_to_records(frame):
            record["__stream"] = name
            record["__role"] = role
            record["__assigned"] = False
            records.append(record)
        stream_rows.append(
            {
                "name": name,
                "role": role,
                "rows": int(len(frame)),
                "metrics": [m for m in METRIC_COLUMNS if m in frame.columns and frame[m].notna().any()],
            }
        )

    warnings: List[str] = []
    if not records:
        return AlignedStreams(
            schema.empty_frame(),
            AlignmentReport(
                mode="overnight_morning",
                tolerance_minutes=round(lookback_hours * 60.0, 1),
                anchor=anchor_role,
                subject_column=subject_column,
                streams=stream_rows,
                warnings=["no rows to align"],
                overnight_lookback_hours=lookback_hours,
                morning_window=window,
            ),
        )

    anchor_index = [
        i for i, row in enumerate(records)
        if row["__role"] == anchor_role and _in_window(row[TIMESTAMP], window)
    ]
    anchor_set = set(anchor_index)
    outside_index = [
        i for i, row in enumerate(records)
        if row["__role"] == anchor_role and i not in anchor_set
    ]
    if not anchor_index:
        warnings.append(
            f"no {anchor_role} row fell inside {window[0]:02d}:00–{window[1]:02d}:00; "
            "the overnight preset needs a morning cuff reading as its anchor"
        )

    known_subjects = {_subject_key(r.get(SUBJECT)) for r in records if _subject_key(r.get(SUBJECT))}
    single_subject = len(known_subjects) <= 1
    unlabelled_joins = 0

    def _compatible(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        a, b = _subject_key(left.get(SUBJECT)), _subject_key(right.get(SUBJECT))
        if a and b:
            return a == b
        if a or b:
            return single_subject
        return True

    role_set = {row["__role"] for row in records}
    roles = [role for role in ROLE_ORDER if role in role_set and role != anchor_role]
    roles += sorted(role_set - set(roles) - {anchor_role})

    partner_of: Dict[int, List[int]] = {i: [] for i in anchor_index}
    for role in roles:
        candidates: List[Tuple[float, int, int]] = []
        for index, row in enumerate(records):
            if row["__role"] != role or row["__assigned"]:
                continue
            for anchor_idx in anchor_index:
                anchor_row = records[anchor_idx]
                if not _compatible(anchor_row, row):
                    continue
                lag_seconds = (anchor_row[TIMESTAMP] - row[TIMESTAMP]).total_seconds()
                # One-sided: a reading after the cuff is never pulled back onto it.
                if 0.0 <= lag_seconds <= lookback_seconds:
                    candidates.append((lag_seconds, anchor_idx, index))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        taken_anchor: set[int] = set()
        taken_row: set[int] = set()
        for lag_seconds, anchor_idx, index in candidates:
            if index in taken_row or anchor_idx in taken_anchor:
                continue
            partner_of[anchor_idx].append(index)
            taken_anchor.add(anchor_idx)
            taken_row.add(index)
            records[index]["__assigned"] = True
            records[index]["__lag_minutes"] = round(lag_seconds / 60.0, 1)
            if not (_subject_key(records[anchor_idx].get(SUBJECT)) and _subject_key(records[index].get(SUBJECT))):
                unlabelled_joins += 1

    out: List[Dict[str, Any]] = []
    matched_anchors = 0
    multi = 0
    conflicts = 0
    matches: List[Dict[str, Any]] = []
    lags: List[float] = []
    roles_by_anchor: Dict[int, List[str]] = {}
    for anchor_idx in anchor_index:
        anchor_row = records[anchor_idx]
        base = {k: v for k, v in anchor_row.items() if not k.startswith("__")}
        partners = partner_of[anchor_idx]
        roles_by_anchor[anchor_idx] = [records[p]["__role"] for p in partners]
        if partners:
            matched_anchors += 1
            local_conflicts: List[str] = []
            for partner in partners:
                _coalesce(base, {k: v for k, v in records[partner].items() if not k.startswith("__")}, local_conflicts)
            conflicts += len(local_conflicts)
            if local_conflicts:
                _add_flag(base, "align_conflict")
            for partner in partners:
                lag = float(records[partner].get("__lag_minutes") or 0.0)
                lags.append(lag)
                if len(matches) < MATCH_LOG_LIMIT:
                    matches.append(
                        {
                            "subject_id": base.get(SUBJECT),
                            "anchor": pd.Timestamp(anchor_row[TIMESTAMP]).isoformat(sep=" "),
                            "stream": records[partner]["__stream"],
                            "role": records[partner]["__role"],
                            "observed_at": pd.Timestamp(records[partner][TIMESTAMP]).isoformat(sep=" "),
                            "lag_minutes": lag,
                        }
                    )
        base[SOURCE] = "+".join(
            dict.fromkeys(
                [str(base.get(SOURCE) or "")]
                + [str(records[p].get(SOURCE) or "") for p in partners]
            )
        ).strip("+") or base.get(SOURCE)
        base["__streams"] = "+".join(
            dict.fromkeys([anchor_row["__stream"]] + [records[p]["__stream"] for p in partners])
        )
        _add_flag(base, f"align:{base['__streams']}")
        _add_flag(base, "align:overnight_morning")
        if not partners:
            _add_flag(base, "align_unmatched")
        if len(set(roles_by_anchor[anchor_idx])) > 1 or len(partners) > 1:
            multi += 1
        out.append(base)

    # Why an anchor got no row from a stream — computed, not guessed.
    unmatched: List[Dict[str, Any]] = []
    reason_counts: Dict[str, int] = {}
    for anchor_idx in anchor_index:
        anchor_row = records[anchor_idx]
        have = {records[p]["__role"] for p in partner_of[anchor_idx]}
        for role in roles:
            if role in have:
                continue
            role_rows = [row for row in records if row["__role"] == role]
            same_subject = [row for row in role_rows if _compatible(anchor_row, row)]
            in_window = False
            after_only = False
            for row in same_subject:
                delta = (anchor_row[TIMESTAMP] - row[TIMESTAMP]).total_seconds()
                if 0.0 <= delta <= lookback_seconds:
                    in_window = True
                    break
                if -lookback_seconds <= delta < 0.0:
                    after_only = True
            if in_window:
                reason = "already_matched_to_another_anchor"
            elif after_only:
                reason = "only_after_anchor"
            elif not role_rows:
                reason = "stream_not_present"
            elif not same_subject:
                reason = "no_row_for_this_subject"
            else:
                reason = "outside_lookback_window"
            key = f"{role}:{reason}"
            reason_counts[key] = reason_counts.get(key, 0) + 1
            if len(unmatched) < MATCH_LOG_LIMIT:
                unmatched.append(
                    {
                        "subject_id": anchor_row.get(SUBJECT),
                        "anchor": pd.Timestamp(anchor_row[TIMESTAMP]).isoformat(sep=" "),
                        "role": role,
                        "reason": reason,
                    }
                )

    for index in outside_index:
        row = records[index]
        base = {k: v for k, v in row.items() if not k.startswith("__")}
        base["__streams"] = row["__stream"]
        _add_flag(base, f"align:{row['__stream']}")
        _add_flag(base, "align:overnight_morning")
        _add_flag(base, "align_outside_morning_window")
        _add_flag(base, "align_unmatched")
        out.append(base)

    for index, row in enumerate(records):
        if row["__role"] == anchor_role or row["__assigned"]:
            continue
        base = {k: v for k, v in row.items() if not k.startswith("__")}
        base["__streams"] = row["__stream"]
        _add_flag(base, f"align:{row['__stream']}")
        _add_flag(base, "align:overnight_morning")
        _add_flag(base, "align_unmatched")
        out.append(base)

    for entry in stream_rows:
        matched = 0
        by_date: Dict[str, Dict[str, int]] = {}
        for index, row in enumerate(records):
            if row["__stream"] != entry["name"]:
                continue
            date = _day_of(row[TIMESTAMP])
            cell = by_date.setdefault(date, {"rows": 0, "matched": 0})
            cell["rows"] += 1
            if row["__assigned"]:
                matched += 1
                cell["matched"] += 1
            elif row["__role"] == anchor_role and index in anchor_set and roles_by_anchor.get(index):
                matched += 1
                cell["matched"] += 1
        entry["matched_rows"] = int(matched)
        entry["unmatched_rows"] = int(entry["rows"] - matched)
        entry["match_rate_pct"] = round(matched / entry["rows"] * 100, 1) if entry["rows"] else 0.0
        entry["by_date"] = by_date

    frame = _records_to_frame(out)
    total_matches = sum(len(v) for v in partner_of.values())
    report = AlignmentReport(
        mode="overnight_morning",
        tolerance_minutes=round(lookback_hours * 60.0, 1),
        anchor=anchor_role,
        subject_column=subject_column,
        streams=stream_rows,
        rows_in=len(records),
        rows_out=len(frame),
        anchors=len(anchor_index),
        anchors_matched=matched_anchors,
        rows_with_multiple_streams=multi,
        warnings=warnings,
        overnight_lookback_hours=lookback_hours,
        morning_window=window,
        anchors_outside_window=len(outside_index),
        lag_minutes=_lag_summary(lags),
        matches=matches,
        unmatched=unmatched,
        unmatched_reasons=reason_counts,
        matches_truncated=total_matches > MATCH_LOG_LIMIT,
    )
    if conflicts:
        report.warnings.append(
            f"{conflicts} value(s) from a second device were kept out because the anchor row already had that metric"
        )
    if unlabelled_joins:
        report.warnings.append(
            f"{unlabelled_joins} row(s) had no subject_id and were joined as the single subject of the table"
        )
    if outside_index:
        report.warnings.append(
            f"{len(outside_index)} {anchor_role} row(s) fell outside "
            f"{window[0]:02d}:00–{window[1]:02d}:00 and were kept as separate rows "
            "flagged align_outside_morning_window"
        )
    return AlignedStreams(frame, report)


def _align_daily(
    named: Sequence[Tuple[str, str, pd.DataFrame]],
    anchor_role: str,
    subject_column: str,
    anchor_frame: pd.DataFrame,
) -> AlignedStreams:
    stream_rows: List[Dict[str, Any]] = []
    daily: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
    bucket_rows: Dict[Tuple[str, str, str], int] = {}
    stream_rows_by_date: Dict[str, Dict[str, Dict[str, int]]] = {}
    for name, role, frame in named:
        stream_rows.append(
            {
                "name": name,
                "role": role,
                "rows": int(len(frame)),
                "metrics": [m for m in METRIC_COLUMNS if m in frame.columns and frame[m].notna().any()],
            }
        )
        if frame.empty:
            continue
        working = frame.copy()
        working["__date"] = working[TIMESTAMP].dt.strftime("%Y-%m-%d")
        for (subject, date), group in working.groupby([SUBJECT, "__date"], dropna=False):
            key = (_subject_key(subject), str(date))
            bucket_rows[(name, key[0], key[1])] = int(len(group))
            cell = stream_rows_by_date.setdefault(name, {}).setdefault(str(date), {"rows": 0, "matched": 0})
            cell["rows"] += int(len(group))
            if key not in daily:
                daily[key] = {
                    TIMESTAMP: pd.Timestamp(f"{date} 00:00:00"),
                    SUBJECT: schema.normalize_subject(subject),
                    CONDITION: None,
                    SOURCE: None,
                    FLAGS: None,
                    NOTES: None,
                    "__streams": [],
                    "__roles": [],
                }
                order.append(key)
            target = daily[key]
            local_conflicts: List[str] = []
            _coalesce(
                target,
                {
                    **{column: group[column].mean() if column in group else np.nan for column in METRIC_COLUMNS},
                    CONDITION: next((v for v in group[CONDITION] if isinstance(v, str) and v), None) if CONDITION in group else None,
                    NOTES: next((v for v in group[NOTES] if isinstance(v, str) and v), None) if NOTES in group else None,
                },
                local_conflicts,
            )
            target["__streams"].append(name)
            target["__roles"].append(role)

    out: List[Dict[str, Any]] = []
    joined_keys: List[Tuple[Tuple[str, str], List[str]]] = []
    for key in order:
        row = daily[key]
        streams = list(dict.fromkeys(row.pop("__streams")))
        row.pop("__roles", None)
        row[SOURCE] = "+".join(streams)
        row["__streams"] = "+".join(streams)
        _add_flag(row, f"align:{row['__streams']}")
        if len(streams) < 2:
            _add_flag(row, "align_unmatched")
        joined_keys.append((key, streams))
        out.append(row)

    # A day is joined for a stream when that stream's rows of the day went into
    # an output row that also carries another stream. Input rows stay the unit,
    # so a stream's count here is comparable with its raw row count.
    for key, streams in joined_keys:
        if len(streams) < 2:
            continue
        subject, date = key
        for stream in streams:
            count = bucket_rows.get((stream, subject, date), 0)
            stream_rows_by_date.setdefault(stream, {}).setdefault(date, {"rows": count, "matched": 0})["matched"] += count

    frame = _records_to_frame(out)
    matched = sum(1 for row in out if len(str(row.get("__streams", "")).split("+")) > 1)
    for entry in stream_rows:
        by_date = stream_rows_by_date.get(entry["name"], {})
        entry["matched_rows"] = int(sum(cell["matched"] for cell in by_date.values()))
        entry["unmatched_rows"] = int(entry["rows"] - entry["matched_rows"])
        entry["match_rate_pct"] = (
            round(entry["matched_rows"] / entry["rows"] * 100, 1) if entry["rows"] else 0.0
        )
        entry["by_date"] = by_date

    report = AlignmentReport(
        mode="daily",
        tolerance_minutes=0.0,
        anchor="date",
        subject_column=subject_column,
        streams=stream_rows,
        rows_in=int(sum(len(f) for _, _, f in named)),
        rows_out=len(frame),
        anchors=len(out),
        anchors_matched=matched,
        rows_with_multiple_streams=matched,
        warnings=["daily aggregation used the mean of each metric per subject and calendar day"],
    )
    return AlignedStreams(frame, report)


def _records_to_frame(records: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Build a typed standard table from aligned record dictionaries."""
    if not records:
        return schema.empty_frame()
    frame = pd.DataFrame(records)
    for column in STANDARD_COLUMNS:
        if column not in frame.columns:
            frame[column] = pd.NA
    frame[TIMESTAMP] = pd.to_datetime(frame[TIMESTAMP], errors="coerce")
    for column in METRIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame[SUBJECT] = frame[SUBJECT].map(schema.normalize_subject)
    frame[CONDITION] = frame[CONDITION].map(schema.normalize_condition)
    for column in (FLAGS, NOTES, SOURCE):
        frame[column] = frame[column].astype("object")
    frame = frame.dropna(subset=[TIMESTAMP]).sort_values([SUBJECT, TIMESTAMP], kind="mergesort", na_position="first")
    return frame[list(STANDARD_COLUMNS)].reset_index(drop=True)


def align_files(
    paths: Sequence[Any],
    *,
    conditions: Sequence[str | None] | None = None,
    **kwargs: Any,
) -> AlignedStreams:
    """Load each path with :func:`heartmetric_core.loader.load_file` and align.

    ``conditions`` optionally labels each file's rows (for example
    ``["forest", None, None]`` when only the BP log belongs to a condition).
    """
    results = []
    for index, path in enumerate(paths):
        condition = conditions[index] if conditions and index < len(conditions) else None
        results.append(loader.load_file(path, condition=condition))
    return align_streams(results, **kwargs)


def _date_runs(dates: Sequence[str]) -> List[Dict[str, Any]]:
    """Group sorted consecutive ISO dates into runs (a gap is a run)."""
    runs: List[Dict[str, Any]] = []
    previous: pd.Timestamp | None = None
    for value in dates:
        stamp = pd.Timestamp(value)
        if previous is not None and (stamp - previous).days == 1:
            runs[-1]["end"] = value
            runs[-1]["days"] = int(runs[-1]["days"] + 1)
        else:
            runs.append({"start": value, "end": value, "days": 1})
        previous = stamp
    return runs


def build_timeline_gap_map(
    streams: Iterable[Any],
    alignment_report: AlignmentReport | Mapping[str, Any] | None = None,
    *,
    subject_column: str = SUBJECT,
    max_days: int = 1000,
) -> Dict[str, Any]:
    """Date × stream coverage grid from the inputs and an alignment report.

    Each cell states how many rows a stream wrote on that calendar day and how
    many of them were joined to an anchor:

    ``matched``
        every row of the stream that day was joined,
    ``partial``
        some rows joined and some did not,
    ``unmatched``
        rows exist but none joined (the reason is in the alignment report),
    ``missing``
        the stream wrote nothing that day, including days inside the study span.

    A day is listed for the union of all streams and every calendar day between
    the first and the last observation, so a dropped logger shows as a band of
    missing cells rather than disappearing. Nothing is interpolated: a gap is
    reported as a gap.

    Returns a JSON-ready dict (``dates``, ``streams``, ``cells``, ``summary``).
    """
    named = _coerce_streams(streams)
    if isinstance(alignment_report, AlignmentReport):
        report = alignment_report.to_dict()
    else:
        report = dict(alignment_report or {})
    report_streams = {str(item.get("name")): item for item in report.get("streams", []) if isinstance(item, dict)}

    rows_by_date: Dict[str, Dict[str, int]] = {}
    subjects_by_date: Dict[str, Dict[str, List[str]]] = {}
    dates_seen: set[str] = set()
    for name, _role, frame in named:
        rows_by_date[name] = {}
        subjects_by_date[name] = {}
        if frame.empty:
            continue
        days = frame[TIMESTAMP].dt.strftime("%Y-%m-%d")
        counts = days.value_counts()
        rows_by_date[name] = {str(day): int(count) for day, count in counts.items()}
        grouped = frame.assign(__day=days).groupby("__day")[SUBJECT]
        subjects_by_date[name] = {
            str(day): sorted({str(v) for v in values.dropna()}) for day, values in grouped
        }
        dates_seen.update(rows_by_date[name])

    if not dates_seen:
        return {
            "generated_by": f"heartmetric {__version__}",
            "mode": report.get("mode"),
            "alignment_known": bool(report_streams),
            "span": {"start": None, "end": None, "days": 0, "truncated": False},
            "streams": [{"name": name, "role": role} for name, role, _ in named],
            "dates": [],
            "cells": [],
            "summary": {
                "dates": 0, "streams": len(named), "cells": 0, "missing_dates": 0,
                "coverage_pct": 0.0, "join_rate_pct": 0.0, "per_stream": {}, "gaps": [],
            },
            "note": "no timestamped observation was found in any stream",
        }

    first = min(dates_seen)
    last = max(dates_seen)
    full_span = [
        stamp.strftime("%Y-%m-%d")
        for stamp in pd.date_range(pd.Timestamp(first), pd.Timestamp(last), freq="D")
    ]
    truncated = len(full_span) > max_days
    dates = full_span[-max_days:] if truncated else full_span

    cells: List[Dict[str, Any]] = []
    for date in dates:
        for name, role, _frame in named:
            rows = int(rows_by_date.get(name, {}).get(date, 0))
            info = (report_streams.get(name) or {}).get("by_date") or {}
            day_info = info.get(date)
            matched: int | None
            if rows == 0:
                status = "missing"
                matched = 0
            elif not isinstance(day_info, dict):
                status = "present"
                matched = None
            else:
                matched = int(day_info.get("matched", 0))
                if matched >= rows:
                    status = "matched"
                elif matched <= 0:
                    status = "unmatched"
                else:
                    status = "partial"
            cells.append(
                {
                    "date": date,
                    "stream": name,
                    "role": role,
                    "rows": rows,
                    "matched_rows": matched,
                    "unmatched_rows": (rows - matched) if matched is not None else None,
                    "status": status,
                    "subjects": subjects_by_date.get(name, {}).get(date, []),
                }
            )

    per_stream: Dict[str, Dict[str, Any]] = {}
    for name, role, _frame in named:
        stream_cells = [cell for cell in cells if cell["stream"] == name]
        rows_total = int(sum(cell["rows"] for cell in stream_cells))
        matched_total = int(sum(cell["matched_rows"] or 0 for cell in stream_cells))
        missing_dates = [cell["date"] for cell in stream_cells if cell["status"] == "missing"]
        gaps = _date_runs(missing_dates)
        per_stream[name] = {
            "role": role,
            "dates_present": sum(1 for cell in stream_cells if cell["rows"] > 0),
            "dates_missing": len(missing_dates),
            "cells_matched": sum(1 for cell in stream_cells if cell["status"] == "matched"),
            "cells_partial": sum(1 for cell in stream_cells if cell["status"] == "partial"),
            "cells_unmatched": sum(1 for cell in stream_cells if cell["status"] == "unmatched"),
            "cells_missing": len(missing_dates),
            "rows": rows_total,
            "matched_rows": matched_total,
            "join_rate_pct": round(matched_total / rows_total * 100, 1) if rows_total else 0.0,
            "longest_gap_days": max((gap["days"] for gap in gaps), default=0),
            "gaps": gaps,
        }

    total_cells = len(cells)
    covered = sum(1 for cell in cells if cell["status"] in {"matched", "partial"})
    missing_dates = len({cell["date"] for cell in cells if cell["status"] == "missing"})
    rows_total = sum(entry["rows"] for entry in per_stream.values())
    matched_total = sum(entry["matched_rows"] for entry in per_stream.values())
    summary = {
        "dates": len(dates),
        "streams": len(named),
        "cells": total_cells,
        "cells_matched": sum(1 for cell in cells if cell["status"] == "matched"),
        "cells_partial": sum(1 for cell in cells if cell["status"] == "partial"),
        "cells_unmatched": sum(1 for cell in cells if cell["status"] == "unmatched"),
        "cells_missing": sum(1 for cell in cells if cell["status"] == "missing"),
        "missing_dates": missing_dates,
        "coverage_pct": round(covered / total_cells * 100, 1) if total_cells else 0.0,
        "join_rate_pct": round(matched_total / rows_total * 100, 1) if rows_total else 0.0,
        "per_stream": per_stream,
        "gaps": [gap for entry in per_stream.values() for gap in entry["gaps"]],
    }
    return {
        "generated_by": f"heartmetric {__version__}",
        "mode": report.get("mode"),
        "parameters": {
            "tolerance_minutes": report.get("tolerance_minutes"),
            "overnight_lookback_hours": report.get("overnight_lookback_hours"),
            "morning_window": report.get("morning_window"),
            "anchor": report.get("anchor"),
            "subject_column": subject_column,
        },
        "alignment_known": bool(report_streams),
        "span": {"start": first, "end": last, "days": len(full_span), "truncated": truncated},
        "streams": [{"name": name, "role": role} for name, role, _ in named],
        "dates": dates,
        "cells": cells,
        "summary": summary,
        "note": "A missing cell means the stream wrote nothing that day; nothing is interpolated, "
        "shifted or filled from another stream. `present` means the row count is known but no "
        "alignment report was supplied for that day.",
    }
