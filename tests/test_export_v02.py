from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from heartmetric_core import __version__, exporter, pipeline, provenance, synthetic


@pytest.fixture(scope="module")
def bundle():
    return pipeline.demo_streams(tolerance_minutes=30)


def test_version_is_030():
    assert __version__ == "0.3.0"


def test_methodology_covers_every_indicator():
    indicators = provenance.METHODOLOGY
    for key in ("sbp", "dbp", "hr", "rmssd", "sdnn", "pm25", "map", "pp", "dipping",
                "hrv_recovery", "env_load", "stress_index", "welch_t", "paired_t",
                "cohens_dz", "permutation_p", "pearson_r", "spearman_rho", "ols_slope"):
        assert key in indicators
        record = indicators[key]
        assert record["kind"] in {"measured", "derived", "exploratory"}
        assert record["boundary"]
        if record["kind"] != "measured":
            assert record["formula"]


def test_bundle_carries_schema_version_and_methodology(bundle):
    assert bundle["meta"]["schema_version"] == "0.3.0"
    assert bundle["methodology"]["references"]["welch"]
    assert bundle["methodology"]["indicators"]["env_load"]["kind"] == "exploratory"
    json.dumps(bundle, ensure_ascii=False, allow_nan=False)


def test_markdown_report_contains_the_sections(bundle):
    text = exporter.to_markdown(bundle)
    assert text.startswith("# HEARTMETRIC 분석 리포트")
    for heading in ("## 1. 데이터와 품질", "## 2. 요약 지표", "## 3. 조건별 비교",
                    "## 4. 환경 노출 × 심혈관 상관", "## 5. 스트림 타임라인 갭 맵",
                    "## 6. 조건별 평균", "## 7. 지표 정의와 경계"):
        assert heading in text
    assert "bundle schema 0.3.0" in text
    assert "Oura Health Oy" in text
    assert "| sbp |" in text
    assert "환경 스트림" not in text  # no placeholder left behind


def test_markdown_file_write(tmp_path, bundle):
    path = exporter.to_markdown(bundle, tmp_path / "report.md")
    assert path.endswith("report.md")
    assert "HEARTMETRIC 분석 리포트" in open(path, encoding="utf-8").read()
    saved = exporter.save(bundle, tmp_path / "report_md.md")
    assert saved.endswith(".md")


def test_excel_has_methodology_and_alignment_sheets(bundle):
    payload = exporter.to_excel(bundle)
    book = pd.ExcelFile(io.BytesIO(payload))
    assert book.sheet_names[0] == "README"
    assert "Methodology" in book.sheet_names
    assert "Alignment" in book.sheet_names
    assert "GapMap" in book.sheet_names
    assert "Correlations" in book.sheet_names
    method = pd.read_excel(io.BytesIO(payload), sheet_name="Methodology")
    assert {"indicator", "kind", "formula", "boundary"} <= set(method.columns)
    alignment = pd.read_excel(io.BytesIO(payload), sheet_name="Alignment")
    assert set(alignment["role"]) == {"bp", "wearable", "environment"}
    readme = pd.read_excel(io.BytesIO(payload), sheet_name="README")
    text = " ".join(str(v) for v in readme.iloc[:, 1].dropna())
    assert "0.3.0" in text and "tolerance" in text
    assert "GapMap" in " ".join(str(v) for v in readme.iloc[:, 1].dropna())


def test_comparison_sheet_reports_paired_columns():
    cohort = synthetic.generate_cohort(subjects=6, days=6)
    bundle = pipeline.analyze(cohort, paired=True)
    frame = exporter.bundle_frames(bundle)["Comparison"]
    assert {"cohens_dz", "permutation_p", "sign_test_p", "paired_by"} <= set(frame.columns)
    assert set(frame["paired_by"]) == {"subject"}


def test_json_bundle_keeps_alignment_and_schema(bundle, tmp_path):
    path = exporter.to_json(bundle, tmp_path / "bundle.json")
    payload = json.loads(open(path, encoding="utf-8").read())
    assert payload["meta"]["schema_version"] == "0.3.0"
    assert payload["alignment"]["anchors"] > 0
    assert payload["correlations"][0]["pearson_r"] is not None


def test_cli_merges_multiple_inputs(tmp_path, capsys):
    from heartmetric_core.__main__ import main

    bp = tmp_path / "bp.csv"
    bp.write_text(
        "timestamp,subject_id,condition,sbp,dbp\n"
        "2026-05-06 07:10,S-01,forest,126,78\n"
        "2026-05-07 07:10,S-01,urban,134,84\n"
        "2026-05-08 07:10,S-01,forest,125,77\n",
        encoding="utf-8",
    )
    env = tmp_path / "env.csv"
    env.write_text(
        "timestamp,subject_id,pm25,green_index,temp_c\n"
        "2026-05-06 07:05,S-01,8,0.8,23\n"
        "2026-05-07 07:05,S-01,27,0.1,26\n"
        "2026-05-08 07:05,S-01,9,0.79,23\n",
        encoding="utf-8",
    )
    out = tmp_path / "report.md"
    code = main(["-i", str(bp), "-i", str(env), "--merge", "--tolerance-minutes", "10", "-o", str(out)])
    assert code == 0
    printed = capsys.readouterr().out
    assert "aligned: tolerance" in printed
    assert out.exists()
    assert "HEARTMETRIC 분석 리포트" in out.read_text(encoding="utf-8")


def test_cli_demo_streams_runs(capsys):
    from heartmetric_core.__main__ import main

    code = main(["--demo-streams", "-o", "/tmp/heartmetric_demo_report.json"])
    assert code == 0
    printed = capsys.readouterr().out
    assert "aligned: tolerance" in printed
