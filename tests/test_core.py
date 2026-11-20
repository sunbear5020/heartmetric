from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from heartmetric_core import cleaner, loader, metrics, synthetic


@pytest.fixture()
def demo() -> pd.DataFrame:
    return synthetic.generate(include_anomalies=False)


def test_generate_is_deterministic_and_standard(demo):
    again = synthetic.generate(include_anomalies=False)
    pd.testing.assert_frame_equal(demo, again)
    assert len(demo) == 14 * 5
    assert demo["condition"].value_counts().to_dict() == {"urban": 35, "forest": 35}


def test_generate_covers_night_and_day(demo):
    hours = pd.to_datetime(demo["timestamp"]).dt.hour
    assert (hours < 6).sum() == 14
    assert demo["rmssd"].notna().all()


def test_loader_maps_korean_headers():
    text = (
        "측정일시,수축기,이완기,심박수,조건\n"
        "2026-05-06 07:10:00,132,84,70,도시\n"
        "2026-05-06 10:00:00,138,86,92,숲\n"
    )
    result = loader.load_csv(text, timezone="Asia/Seoul")
    assert len(result.frame) == 2
    assert result.frame["condition"].tolist() == ["urban", "forest"]
    assert result.frame["sbp"].tolist() == [132.0, 138.0]
    assert result.mapping["sbp"] == "수축기"


def test_loader_pivots_long_healthkit_export():
    text = (
        "type,value,startDate\n"
        "HKQuantityTypeIdentifierBloodPressureSystolic,131,2026-05-06 07:10:00 +0900\n"
        "HKQuantityTypeIdentifierBloodPressureDiastolic,83,2026-05-06 07:10:00 +0900\n"
        "HKQuantityTypeIdentifierHeartRate,69,2026-05-06 07:10:00 +0900\n"
    )
    result = loader.load_csv(text)
    assert len(result.frame) == 1
    row = result.frame.iloc[0]
    assert (row["sbp"], row["dbp"], row["hr"]) == (131.0, 83.0, 69.0)


def test_loader_reads_oura_json():
    payload = (
        '[{"day":"2026-05-06","average_hrv":44,"average_heart_rate":54,"lowest_heart_rate":47},'
        ' {"day":"2026-05-07","average_hrv":39,"average_heart_rate":56,"lowest_heart_rate":49}]'
    )
    result = loader.load_json(payload)
    assert result.source == "oura"
    assert result.frame["rmssd"].tolist() == [44.0, 39.0]
    assert pd.to_datetime(result.frame["timestamp"]).dt.hour.tolist() == [3, 3]
    assert any("nightly aggregates" in w for w in result.warnings)


def test_loader_converts_kpa_and_fahrenheit():
    text = "date,systolic,diastolic,temperature\n2026-05-06 07:10,17.6,11.2,80\n"
    result = loader.load_csv(text)
    row = result.frame.iloc[0]
    assert 130 < row["sbp"] < 135
    assert abs(row["temp_c"] - 26.67) < 0.1
    assert any("kPa" in w for w in result.warnings)


def test_loader_detects_units_of_hrv_in_seconds():
    text = "date,hrv\n2026-05-06 03:00,0.042\n2026-05-07 03:00,0.044\n"
    result = loader.load_csv(text)
    assert result.frame["rmssd"].iloc[0] == pytest.approx(42.0)


def test_loader_reads_apple_health_xml(tmp_path):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="ko_KR">
 <Record type="HKQuantityTypeIdentifierBloodPressureSystolic" unit="mmHg" value="134"
         startDate="2026-05-06 07:10:00 +0900" endDate="2026-05-06 07:10:00 +0900"/>
 <Record type="HKQuantityTypeIdentifierBloodPressureDiastolic" unit="mmHg" value="85"
         startDate="2026-05-06 07:10:00 +0900" endDate="2026-05-06 07:10:00 +0900"/>
 <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" unit="ms" value="62"
         startDate="2026-05-06 03:00:00 +0900" endDate="2026-05-06 03:05:00 +0900"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" value="900"
         startDate="2026-05-06 09:00:00 +0900" endDate="2026-05-06 10:00:00 +0900"/>
</HealthData>
"""
    path = tmp_path / "export.xml"
    path.write_text(xml, encoding="utf-8")
    result = loader.load_apple_health_xml(path)
    assert len(result.frame) == 2
    bp_row = result.frame[result.frame["sbp"].notna()].iloc[0]
    assert bp_row["sbp"] == 134 and bp_row["dbp"] == 85
    assert result.frame["sdnn"].dropna().iloc[0] == 62
    assert any("SDNN" in w for w in result.warnings)


def test_cleaner_removes_impossible_values():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-05-06 07:00", periods=4, freq="1D"),
            "sbp": [130, 0, 90, 128],
            "dbp": [84, 0, 96, 82],
        }
    )
    report = cleaner.clean(frame)
    assert report.rows_out == 4
    assert report.removed_out_of_range["sbp"] == 1  # the zero reading
    # the 90/96 pair is removed as internally contradictory
    assert report.removed_inconsistent == 1
    valid = report.frame["sbp"].dropna().tolist()
    assert 0 not in valid and 90 not in valid


def test_cleaner_counts_duplicates():
    frame = synthetic.generate(include_anomalies=False).head(4)
    duplicated = pd.concat([frame, frame.iloc[[1]]], ignore_index=True)
    report = cleaner.clean(duplicated)
    assert report.duplicates_removed == 1


def test_cleaner_keeps_two_subjects_with_identical_readings():
    base = synthetic.generate(days=2, include_anomalies=False)
    base = base.drop(columns=["subject_id"])
    first = base.assign(subject_id="S-01")
    second = base.assign(subject_id="S-02")
    report = cleaner.clean(pd.concat([first, second], ignore_index=True))
    assert report.duplicates_removed == 0
    assert report.rows_out == len(first) + len(second)


def test_cleaner_reports_gaps():
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-05-06 07:00", "2026-05-06 08:00", "2026-05-09 07:00"]),
            "sbp": [130, 132, 128],
        }
    )
    report = cleaner.clean(frame, gap_hours=6)
    assert report.max_gap_hours == pytest.approx(71.0)
    assert len(report.gaps) == 1
    assert report.gaps[0]["hours"] == pytest.approx(71.0)


def test_map_and_pulse_pressure():
    sbp = pd.Series([130.0, 120.0])
    dbp = pd.Series([85.0, 80.0])
    assert metrics.pulse_pressure(sbp, dbp).tolist() == [45.0, 40.0]
    expected = [85 + 45 / 3, 80 + 40 / 3]
    assert metrics.mean_arterial_pressure(sbp, dbp).round(2).tolist() == [round(v, 2) for v in expected]


def test_nocturnal_dipping_category(demo):
    dipping = metrics.nocturnal_dipping(demo, "sbp")
    assert dipping["available"] is True
    assert 5 < dipping["dipping_pct"] < 25
    assert dipping["night_mean"] < dipping["day_mean"]


def test_hrv_recovery_uses_night_baseline(demo):
    recovery = metrics.hrv_recovery(demo)
    assert recovery["available"] is True
    assert recovery["baseline"] == "night"
    assert recovery["index"] > 100
    assert recovery["band"] in {"enhanced recovery", "maintained"}


@pytest.mark.parametrize("column", ["sbp", "dbp"])
def test_dipping_needs_enough_night_readings(demo, column):
    day_only = demo[pd.to_datetime(demo["timestamp"]).dt.hour >= 6]
    assert metrics.nocturnal_dipping(day_only, column)["available"] is False


def test_stress_index_bounds(demo):
    index = metrics.environmental_stress_index(demo)
    assert index["available"] is True
    assert 0 <= index["index"] <= 100
    assert set(index["components"]) >= {"bp_load", "pm25", "thermal"}


def test_condition_summary_and_comparison(demo):
    table = metrics.condition_summary(demo)
    assert set(table["condition"]) == {"urban", "forest"}
    forest = table.set_index("condition").loc["forest", "sbp"]
    urban = table.set_index("condition").loc["urban", "sbp"]
    assert forest < urban
