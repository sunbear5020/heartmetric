"""v0.3 — overnight_morning preset and the stream timeline gap map."""

from __future__ import annotations

import pandas as pd
import pytest

from heartmetric_core import align, pipeline


def _cuff(rows):
    return pd.DataFrame(rows, columns=["timestamp", "subject_id", "condition", "sbp", "dbp"])


def _night(rows):
    return pd.DataFrame(rows, columns=["timestamp", "subject_id", "hr", "rmssd"])


def _env(rows):
    return pd.DataFrame(rows, columns=["timestamp", "subject_id", "pm25", "green_index", "temp_c"])


def _streams():
    """Morning cuffs plus the night that precedes them."""
    bp = _cuff(
        [
            ["2026-05-06 07:10", "S-01", "forest", 126, 78],
            ["2026-05-07 07:05", "S-01", "urban", 134, 84],
            ["2026-05-09 07:20", "S-01", "forest", 130, 82],
        ]
    )
    # Oura nightly aggregates are placed at 03:00 of their day.
    wearable = _night(
        [
            ["2026-05-06 03:00", "S-01", 53, 54.0],
            ["2026-05-07 03:00", "S-01", 57, 49.0],
            ["2026-05-08 03:00", "S-01", 49, 51.0],
            ["2026-05-09 03:00", "S-01", 55, 52.0],
            ["2026-05-06 13:00", "S-01", 88, 30.0],  # after the cuff: must not be pulled back
        ]
    )
    environment = _env(
        [
            ["2026-05-05 21:00", "S-01", 20.0, 0.10, 25.0],  # previous evening
            ["2026-05-06 07:00", "S-01", 8.0, 0.80, 23.0],
            ["2026-05-07 07:00", "S-01", 9.0, 0.79, 22.6],
            ["2026-05-09 07:15", "S-01", 8.5, 0.80, 23.0],
        ]
    )
    return [("cuff_morning.csv", bp), ("oura_night.json", wearable), ("morning_env.csv", environment)]


def test_overnight_morning_joins_night_rows_to_the_morning_cuff():
    aligned = align.align_streams(_streams(), mode="overnight_morning")
    report = aligned.report
    assert report.mode == "overnight_morning"
    assert report.anchors == 3
    assert report.anchors_matched == 3
    assert report.match_rate_pct == 100.0
    assert report.overnight_lookback_hours == 14.0
    assert list(report.morning_window) == [5, 12]

    frame = aligned.frame
    first = frame[frame["timestamp"] == pd.Timestamp("2026-05-06 07:10")].iloc[0]
    assert first["sbp"] == 126
    assert first["rmssd"] == 54.0
    assert first["pm25"] == 8.0  # the 07:00 row is nearer than the 21:00 row
    assert "align:overnight_morning" in str(first["flags"])


def test_overnight_morning_records_lag_minutes_per_match():
    report = align.align_streams(_streams(), mode="overnight_morning").report
    lags = {(m["stream"], m["anchor"]): m["lag_minutes"] for m in report.matches}
    assert lags[("oura_night.json", "2026-05-06 07:10:00")] == 250.0
    assert lags[("morning_env.csv", "2026-05-06 07:10:00")] == 10.0
    assert report.lag_minutes["n"] == len(report.matches)
    assert report.lag_minutes["min"] <= report.lag_minutes["median"] <= report.lag_minutes["max"]


def test_overnight_morning_never_pulls_a_later_reading_back():
    report = align.align_streams(_streams(), mode="overnight_morning").report
    anchors_for_wearable = [
        match["anchor"] for match in report.matches if match["stream"] == "oura_night.json"
    ]
    # the 13:00 wearable row is after every morning cuff and must not be matched
    assert "2026-05-06 13:00:00" not in [m["observed_at"] for m in report.matches]
    first = next(m for m in report.matches if m["anchor"] == anchors_for_wearable[0])
    assert first["observed_at"] < first["anchor"]
    assert first["lag_minutes"] >= 0


def test_overnight_lookback_limit_is_reported_not_silently_dropped():
    bp = _cuff([["2026-05-06 07:10", "S-01", None, 126, 78]])
    wearable = _night([["2026-05-05 11:00", "S-01", 60, 40.0]])  # 20 h earlier
    aligned = align.align_streams(
        [("cuff.csv", bp), ("night.csv", wearable)], mode="overnight_morning"
    )
    assert aligned.report.anchors_matched == 0
    assert aligned.report.unmatched_reasons["wearable:outside_lookback_window"] == 1
    # the night row is kept as its own row, not discarded
    assert len(aligned.frame) == 2
    assert "align_unmatched" in str(aligned.frame.iloc[0]["flags"] + "|" + str(aligned.frame.iloc[1]["flags"]))

    wider = align.align_streams(
        [("cuff.csv", bp), ("night.csv", wearable)],
        mode="overnight_morning",
        overnight_lookback_hours=24,
    )
    assert wider.report.anchors_matched == 1


def test_overnight_morning_keeps_cuff_rows_outside_the_morning_window():
    bp = _cuff(
        [
            ["2026-05-06 03:00", "S-01", None, 115, 70],
            ["2026-05-06 07:10", "S-01", None, 126, 78],
            ["2026-05-06 21:40", "S-01", None, 130, 84],
        ]
    )
    wearable = _night([["2026-05-06 03:00", "S-01", 53, 54.0]])
    aligned = align.align_streams([("cuff.csv", bp), ("night.csv", wearable)], mode="overnight_morning")
    assert aligned.report.anchors == 1
    assert aligned.report.anchors_outside_window == 2
    assert len(aligned.frame) == 3
    flags = " ".join(str(v) for v in aligned.frame["flags"])
    assert "align_outside_morning_window" in flags


def test_overnight_morning_does_not_join_two_subjects():
    bp = _cuff([["2026-05-06 07:10", "S-01", None, 126, 78]])
    wearable = _night([["2026-05-06 03:00", "S-02", 53, 54.0]])
    aligned = align.align_streams([("cuff.csv", bp), ("night.csv", wearable)], mode="overnight_morning")
    assert aligned.report.anchors_matched == 0
    assert aligned.report.unmatched_reasons["wearable:no_row_for_this_subject"] == 1


def test_overnight_morning_needs_a_cuff_in_the_window():
    bp = _cuff([["2026-05-06 15:00", "S-01", None, 126, 78]])
    wearable = _night([["2026-05-06 03:00", "S-01", 53, 54.0]])
    aligned = align.align_streams([("cuff.csv", bp), ("night.csv", wearable)], mode="overnight_morning")
    assert aligned.report.anchors == 0
    assert any("morning" in warning for warning in aligned.report.warnings)


def test_unknown_mode_is_rejected():
    with pytest.raises(ValueError):
        align.align_streams(_streams(), mode="nearest-night")


# --------------------------------------------------------------- gap map


def test_timeline_gap_map_marks_matched_unmatched_and_missing_days():
    streams = _streams()
    aligned = align.align_streams(streams, mode="overnight_morning")
    gap = align.build_timeline_gap_map(streams, aligned.report)
    summary = gap["summary"]
    assert gap["dates"][0] == "2026-05-05"
    assert gap["dates"][-1] == "2026-05-09"
    assert summary["dates"] == 5
    assert summary["streams"] == 3
    assert summary["cells"] == 15

    def cell(date, stream):
        return next(c for c in gap["cells"] if c["date"] == date and c["stream"] == stream)

    assert cell("2026-05-06", "cuff_morning.csv")["status"] == "matched"
    assert cell("2026-05-08", "cuff_morning.csv")["status"] == "missing"
    assert cell("2026-05-08", "oura_night.json")["status"] == "unmatched"
    assert cell("2026-05-08", "oura_night.json")["rows"] == 1
    assert cell("2026-05-08", "oura_night.json")["matched_rows"] == 0
    assert cell("2026-05-06", "oura_night.json")["subjects"] == ["S-01"]
    assert summary["cells_missing"] > 0
    assert summary["missing_dates"] == 2  # 05-05 and 05-08


def test_timeline_gap_map_reports_gaps_per_stream():
    streams = _streams()
    aligned = align.align_streams(streams, mode="overnight_morning")
    gap = align.build_timeline_gap_map(streams, aligned.report)
    per_stream = gap["summary"]["per_stream"]
    cuff = per_stream["cuff_morning.csv"]
    assert cuff["role"] == "bp"
    assert cuff["dates_present"] == 3
    assert cuff["dates_missing"] == 2
    assert cuff["join_rate_pct"] == 100.0
    assert any(gap_entry["start"] == "2026-05-08" for gap_entry in cuff["gaps"])
    night = per_stream["oura_night.json"]
    assert night["join_rate_pct"] == 60.0  # 3 of 5 rows joined (05-08 has no morning cuff, 13:00 is after one)
    assert gap["summary"]["gaps"]


def test_timeline_gap_map_without_report_marks_presence_only():
    streams = [("cuff.csv", _cuff([["2026-05-06 07:10", "S-01", None, 126, 78]]))]
    gap = align.build_timeline_gap_map(streams, None)
    assert gap["alignment_known"] is False
    assert gap["cells"][0]["status"] == "present"
    assert gap["cells"][0]["matched_rows"] is None


def test_timeline_gap_map_is_json_safe_and_does_not_invent_values():
    import json

    streams = _streams()
    aligned = align.align_streams(streams, mode="overnight_morning")
    gap = align.build_timeline_gap_map(streams, aligned.report)
    json.dumps(gap, ensure_ascii=False, allow_nan=False)
    missing = [c for c in gap["cells"] if c["status"] == "missing"]
    assert missing and all(c["rows"] == 0 and c["matched_rows"] == 0 for c in missing)


def test_pipeline_bundle_carries_the_gap_map():
    streams = _streams()
    bundle = pipeline.analyze_streams(streams, mode="overnight_morning")
    assert bundle["meta"]["schema_version"] == "0.3.0"
    assert bundle["alignment"]["mode"] == "overnight_morning"
    gap = bundle["timeline_gap_map"]
    assert gap["summary"]["cells"] == 15
    assert bundle["meta"]["timeline_gap_map"]["cells"] == 15
    assert any("date(s) inside the study span" in warning for warning in bundle["warnings"])


def test_demo_overnight_joins_the_whole_synthetic_night():
    bundle = pipeline.demo_overnight()
    report = bundle["alignment"]
    assert report["mode"] == "overnight_morning"
    assert report["anchors_matched"] == report["anchors"]
    assert report["lag_minutes"]["n"] > 0
    assert bundle["timeline_gap_map"]["summary"]["cells_matched"] > 0


def test_missing_labels_never_become_text():
    import pandas as pd

    from heartmetric_core import schema

    assert schema.normalize_condition(pd.NA) is None
    assert schema.normalize_subject(pd.NA) is None
    assert schema.normalize_condition(float("nan")) is None
    assert schema.normalize_subject("  S-01 ") == "S-01"
    bundle = pipeline.demo_overnight()
    conditions = bundle["quality"]["conditions"]
    assert "<na>" not in conditions
    assert conditions.get("(unlabelled)", 0) > 0
