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

License: MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

from . import loader, schema
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

    @property
    def match_rate_pct(self) -> float:
        if not self.anchors:
            return 0.0
        return round(self.anchors_matched / self.anchors * 100, 1)

    def to_dict(self) -> Dict[str, Any]:
        return {
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
    anchor:
        Role whose rows become the output rows ("bp" by default). Rows of other
        streams that find no anchor within tolerance are kept separately,
        flagged ``align_unmatched``.
    subject_column:
        Column that must match before rows can be joined. Rows without a
        subject id are treated as one anonymous subject.

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
    if mode not in {"tolerance", "daily"}:
        raise ValueError(f"unsupported alignment mode: {mode}")

    roles_present = [role for _, role, _ in named]
    chosen_anchor = anchor or next((role for role in ROLE_ORDER if role in roles_present), roles_present[0])
    if mode == "daily":
        chosen_anchor_frame = next((f for _, r, f in named if r == chosen_anchor), named[0][2])
        return _align_daily(named, chosen_anchor, subject_column, chosen_anchor_frame)

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
        for index, row in enumerate(records):
            if row["__stream"] != entry["name"]:
                continue
            if row["__assigned"]:
                matched += 1
            elif row["__role"] == anchor_role and index in anchor_index:
                matched += 1 if roles_by_anchor.get(index) else 0
        entry["matched_rows"] = int(matched)
        entry["unmatched_rows"] = int(entry["rows"] - matched)
        entry["match_rate_pct"] = round(matched / entry["rows"] * 100, 1) if entry["rows"] else 0.0

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


def _align_daily(
    named: Sequence[Tuple[str, str, pd.DataFrame]],
    anchor_role: str,
    subject_column: str,
    anchor_frame: pd.DataFrame,
) -> AlignedStreams:
    stream_rows: List[Dict[str, Any]] = []
    daily: Dict[Tuple[str, str], Dict[str, Any]] = {}
    order: List[Tuple[str, str]] = []
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
    for key in order:
        row = daily[key]
        streams = list(dict.fromkeys(row.pop("__streams")))
        row.pop("__roles", None)
        row[SOURCE] = "+".join(streams)
        row["__streams"] = "+".join(streams)
        _add_flag(row, f"align:{row['__streams']}")
        out.append(row)

    frame = _records_to_frame(out)
    matched = sum(1 for row in out if len(str(row.get("__streams", "")).split("+")) > 1)
    for entry in stream_rows:
        entry["matched_rows"] = int(sum(1 for row in out if entry["name"] in str(row.get("__streams", "")).split("+")))
        entry["unmatched_rows"] = int(entry["rows"] - entry["matched_rows"])
        entry["match_rate_pct"] = None

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
