from __future__ import annotations

import pandas as pd
import pytest

from heartmetric_core import align, loader, pipeline, synthetic


def _streams():
    """Three small streams recorded on three different clocks."""
    bp = pd.DataFrame(
        {
            "timestamp": ["2026-05-06 07:10", "2026-05-06 10:00", "2026-05-07 07:10"],
            "subject_id": ["S-01", "S-01", "S-01"],
            "condition": ["forest", "forest", "forest"],
            "sbp": [126, 141, 124],
            "dbp": [78, 86, 77],
        }
    )
    wearable = pd.DataFrame(
        {
            "timestamp": ["2026-05-06 07:12", "2026-05-06 10:06", "2026-05-07 07:08"],
            "subject_id": ["S-01", "S-01", "S-01"],
            "hr": [68, 96, 70],
            "rmssd": [44.0, 32.0, 41.0],
        }
    )
    environment = pd.DataFrame(
        {
            "timestamp": ["2026-05-06 07:05", "2026-05-06 10:05", "2026-05-07 07:06"],
            "subject_id": ["S-01", "S-01", "S-01"],
            "pm25": [8.0, 9.5, 8.6],
            "temp_c": [23.0, 24.0, 22.6],
            "green_index": [0.8, 0.82, 0.79],
        }
    )
    return [("cuff_bp.csv", bp), ("wearable.json", wearable), ("environment.csv", environment)]


def test_align_streams_joins_by_tolerance_and_reports_matches():
    aligned = align.align_streams(_streams(), tolerance_minutes=15)
    frame, report = aligned.frame, aligned.report
    assert report.anchors == 3
    assert report.anchors_matched == 3
    assert report.match_rate_pct == 100.0
    first = frame.iloc[0]
    assert first["sbp"] == 126
    assert first["rmssd"] == 44.0
    assert first["pm25"] == 8.0
    assert "align_unmatched" not in str(first["flags"])
    assert {s["role"] for s in report.streams} == {"bp", "wearable", "environment"}
    assert all(s["matched_rows"] == s["rows"] for s in report.streams)


def test_zero_tolerance_only_joins_identical_timestamps():
    aligned = align.align_streams(_streams(), tolerance_minutes=0)
    report = aligned.report
    assert report.anchors_matched == 0
    assert report.match_rate_pct == 0.0
    # every row is kept: nothing is dropped when a partner cannot be found
    assert len(aligned.frame) == 9
    flags = " ".join(str(v) for v in aligned.frame["flags"].dropna())
    assert flags.count("align_unmatched") == 9


def test_alignment_never_joins_two_subjects():
    bp = pd.DataFrame(
        {"timestamp": ["2026-05-06 07:10"], "subject_id": ["S-01"], "sbp": [126], "dbp": [78]}
    )
    wearable = pd.DataFrame(
        {"timestamp": ["2026-05-06 07:11"], "subject_id": ["S-02"], "rmssd": [44.0]}
    )
    aligned = align.align_streams([("bp", bp), ("wearable", wearable)], tolerance_minutes=60)
    assert len(aligned.frame) == 2
    assert aligned.report.anchors_matched == 0
    bp_row = aligned.frame[aligned.frame["sbp"].notna()].iloc[0]
    assert pd.isna(bp_row["rmssd"])
    other = aligned.frame[aligned.frame["sbp"].isna()].iloc[0]
    assert other["rmssd"] == 44.0 and other["subject_id"] == "S-02"


def test_wider_tolerance_matches_more_rows():
    bp = _streams()[0][1]
    wearable = pd.DataFrame(
        {
            "timestamp": ["2026-05-06 07:40", "2026-05-06 10:35"],
            "subject_id": ["S-01", "S-01"],
            "rmssd": [40.0, 30.0],
        }
    )
    tight = align.align_streams([("bp", bp), ("wearable", wearable)], tolerance_minutes=15)
    loose = align.align_streams([("bp", bp), ("wearable", wearable)], tolerance_minutes=45)
    assert tight.report.anchors_matched == 0
    assert loose.report.anchors_matched == 2


def test_daily_mode_aggregates_before_joining():
    aligned = align.align_streams(_streams(), mode="daily")
    assert aligned.report.mode == "daily"
    assert len(aligned.frame) == 2  # two calendar days
    day_one = aligned.frame.iloc[0]
    assert day_one["sbp"] == pytest.approx(133.5)  # mean of 126 and 141
    assert day_one["rmssd"] == pytest.approx(38.0)
    assert aligned.report.rows_with_multiple_streams == 2


def test_align_streams_accepts_loaded_files(tmp_path):
    bp = tmp_path / "bp.csv"
    bp.write_text("측정일시,수축기,이완기,피험자\n2026-05-06 07:10,128,80,S-01\n", encoding="utf-8")
    wearable = tmp_path / "oura.json"
    wearable.write_text(
        '[{"day":"2026-05-06","average_hrv":42,"average_heart_rate":55}]', encoding="utf-8"
    )
    # Oura places a nightly aggregate at 03:00 of its day, four hours before the
    # 07:10 cuff reading, so the tolerance has to span the night to join them.
    aligned = align.align_files([bp, wearable], tolerance_minutes=300)
    assert len(aligned.frame) == 1
    row = aligned.frame.iloc[0]
    assert row["sbp"] == 128
    assert row["rmssd"] == 42.0
    assert row["subject_id"] == "S-01"
    # the Oura export carries no subject id, so the join is recorded in the warnings
    assert any("no subject_id" in w for w in aligned.report.warnings)


def test_analyze_streams_returns_alignment_block(tmp_path):
    bp = tmp_path / "bp.csv"
    bp.write_text(
        "timestamp,subject_id,condition,sbp,dbp\n"
        "2026-05-06 07:10,S-01,forest,126,78\n"
        "2026-05-07 07:10,S-01,urban,134,84\n",
        encoding="utf-8",
    )
    env = tmp_path / "env.csv"
    env.write_text("timestamp,subject_id,pm25,green_index\n2026-05-06 07:08,S-01,8,0.8\n2026-05-07 07:12,S-01,27,0.1\n", encoding="utf-8")
    bundle = pipeline.analyze_streams([str(bp), str(env)], tolerance_minutes=10)
    assert bundle["alignment"]["mode"] == "tolerance"
    assert bundle["meta"]["alignment"]["anchors_matched"] == 2
    assert bundle["meta"]["schema_version"] == "0.2.0"
    assert bundle["quality"]["rows_out"] == 2


def test_demo_streams_rejoins_the_synthetic_study():
    bundle = pipeline.demo_streams(tolerance_minutes=30)
    assert bundle["alignment"]["anchors_matched"] == bundle["alignment"]["anchors"]
    assert bundle["summary"]["sbp"] is not None
    assert {s["role"] for s in bundle["alignment"]["streams"]} == {"bp", "wearable", "environment"}


def test_stream_role_detection():
    frame = synthetic.generate(days=2, include_anomalies=False)
    assert align.stream_role(frame) == "bp"
    assert align.stream_role(frame[["timestamp", "rmssd"]].dropna()) == "wearable"
    assert align.stream_role(frame[["timestamp", "pm25", "green_index"]]) == "environment"
