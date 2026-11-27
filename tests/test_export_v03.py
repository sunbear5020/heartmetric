"""v0.3 — the exported bundle carries the gap map and the adjusted p-values."""

from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from heartmetric_core import SCHEMA_VERSION, exporter, pipeline


@pytest.fixture(scope="module")
def bundle():
    return pipeline.demo_streams(tolerance_minutes=30)


@pytest.fixture(scope="module")
def overnight_bundle():
    return pipeline.demo_overnight()


def test_schema_version_is_030(bundle):
    assert SCHEMA_VERSION == "0.3.0"
    assert bundle["meta"]["schema_version"] == "0.3.0"


def test_json_bundle_carries_gap_map_and_multiple_comparison(bundle, tmp_path):
    path = exporter.to_json(bundle, tmp_path / "bundle.json")
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["meta"]["schema_version"] == "0.3.0"
    gap = payload["timeline_gap_map"]
    assert gap["summary"]["cells"] == len(gap["cells"])
    assert gap["summary"]["streams"] == 3
    assert payload["meta"]["timeline_gap_map"]["dates"] == gap["summary"]["dates"]
    block = payload["meta"]["multiple_comparison"]
    assert block["family_size"] == len(payload["comparison"])
    for row in payload["comparison"]:
        assert "q_value_bh" in row and "p_holm" in row
        assert isinstance(row["significant_fdr_05"], bool)


def test_gap_map_frame_is_a_sheet(bundle):
    frames = exporter.bundle_frames(bundle)
    assert "GapMap" in frames
    frame = frames["GapMap"]
    assert {"date", "stream", "role", "status", "rows", "matched_rows"} <= set(frame.columns)
    assert set(frame["status"]) <= {"matched", "partial", "unmatched", "missing", "present"}


def test_markdown_report_has_the_gap_section_and_adjusted_columns(bundle):
    text = exporter.to_markdown(bundle)
    assert "## 5. 스트림 타임라인 갭 맵" in text
    assert "## 6. 조건별 평균" in text
    assert "## 7. 지표 정의와 경계" in text
    assert "q_value_bh" in text and "p_holm" in text
    assert "다중 비교: 가족 크기 m = " in text
    assert "Benjamini & Hochberg 1995" in text
    assert "관측이 없는 칸은 **결측**" in text


def test_overnight_bundle_reports_the_preset(bundle, overnight_bundle):
    text = exporter.to_markdown(overnight_bundle)
    assert "야간→아침 프리셋" in text
    assert "overnight_morning" in text
    assert "lag 중앙값" in text
    readme = exporter._readme_frame(overnight_bundle)
    details = " ".join(str(v) for v in readme.to_numpy().ravel() if v is not None)
    assert "Overnight preset" in details
    assert "Gap map" in details


def test_excel_has_gapmap_sheet_with_rows(bundle):
    payload = exporter.to_excel(bundle)
    book = pd.ExcelFile(io.BytesIO(payload))
    assert "GapMap" in book.sheet_names
    frame = pd.read_excel(io.BytesIO(payload), sheet_name="GapMap")
    assert len(frame) == bundle["timeline_gap_map"]["summary"]["cells"]
    readme = pd.read_excel(io.BytesIO(payload), sheet_name="README")
    text = " ".join(str(v) for v in readme.to_numpy().ravel() if v is not None)
    assert "Multiple comparison" in text
    assert "GapMap" in text


def test_comparison_excel_sheet_has_adjusted_columns(overnight_bundle):
    cohort = pipeline.demo_bundle(paired=True)
    frame = exporter.bundle_frames(cohort)["Comparison"]
    assert {"p_value", "p_holm", "q_value_bh", "significant_fdr_05"} <= set(frame.columns)


def test_cli_demo_overnight_runs(capsys):
    from heartmetric_core.__main__ import main

    code = main(["--demo-overnight", "-o", "/tmp/heartmetric_overnight.json"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "overnight preset" in printed
    assert "gap map:" in printed


def test_cli_align_mode_overnight(tmp_path):
    from heartmetric_core.__main__ import main

    cuff = tmp_path / "cuff.csv"
    cuff.write_text(
        "timestamp,subject_id,sbp,dbp\n"
        "2026-05-06 07:10,S-01,126,78\n"
        "2026-05-07 07:05,S-01,134,84\n",
        encoding="utf-8",
    )
    night = tmp_path / "night.json"
    night.write_text(
        json.dumps(
            [
                {"day": "2026-05-06", "average_hrv": 54, "average_heart_rate": 53},
                {"day": "2026-05-07", "average_hrv": 49, "average_heart_rate": 57},
            ]
        ),
        encoding="utf-8",
    )
    out = tmp_path / "overnight.md"
    code = main(["-i", str(cuff), "-i", str(night), "--align-mode", "overnight_morning", "-o", str(out)])
    assert code == 0
    text = out.read_text(encoding="utf-8")
    assert "overnight_morning" in text
    assert "스트림 타임라인 갭 맵" in text
