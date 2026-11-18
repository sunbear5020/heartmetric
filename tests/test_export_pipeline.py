from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from heartmetric_core import exporter, loader, pipeline, synthetic


@pytest.fixture()
def bundle():
    return pipeline.analyze(synthetic.generate())


def test_bundle_is_json_serialisable(bundle):
    text = json.dumps(bundle, ensure_ascii=False, allow_nan=False)
    assert len(text) > 1000
    assert bundle["meta"]["license"].startswith("MIT")
    assert set(["quality", "summary", "comparison", "daily", "series"]) <= set(bundle)


def test_summary_has_indices(bundle):
    summary = bundle["summary"]
    assert summary["available"] is True
    assert summary["rows"] > 60
    assert summary["map"] is not None
    assert summary["hrv_recovery"]["available"] is True
    assert summary["stress_index"]["available"] is True


def test_comparison_reports_forest_lower_bp(bundle):
    row = {r["metric"]: r for r in bundle["comparison"]}["sbp"]
    assert row["mean_a"] < row["mean_b"]
    assert row["cohens_d"] < 0
    assert 0 <= row["p_value"] <= 1


def test_quality_reports_the_inserted_faults(bundle):
    quality = bundle["quality"]
    assert quality["rows_in"] > quality["rows_out"]
    assert quality["duplicates_removed"] >= 1
    assert quality["removed_inconsistent"] >= 1


def test_excel_export_has_expected_sheets(bundle):
    payload = exporter.to_excel(bundle)
    assert isinstance(payload, bytes) and len(payload) > 5000
    book = pd.ExcelFile(io.BytesIO(payload))
    assert book.sheet_names[0] == "README"
    for name in ("Summary", "Quality", "Comparison", "Readings"):
        assert name in book.sheet_names
    comparison = pd.read_excel(io.BytesIO(payload), sheet_name="Comparison")
    assert "cohens_d" in comparison.columns
    readme = pd.read_excel(io.BytesIO(payload), sheet_name="README")
    assert "MIT" in " ".join(str(v) for v in readme.iloc[:, 1].dropna())


def test_csv_and_json_export_roundtrip(tmp_path, bundle):
    frame = synthetic.generate()
    csv_path = exporter.to_csv(frame, tmp_path / "readings.csv")
    reloaded = loader.load_csv(csv_path)
    assert len(reloaded.frame) == len(frame)

    json_path = exporter.to_json(bundle, tmp_path / "report.json")
    payload = json.loads(open(json_path, encoding="utf-8").read())
    assert payload["summary"]["rows"] == bundle["summary"]["rows"]

    xlsx_path = exporter.save(bundle, tmp_path / "report.xlsx")
    assert xlsx_path.endswith(".xlsx")


def test_csv_dir_writes_each_table(tmp_path, bundle):
    written = exporter.to_csv_dir(bundle, tmp_path / "csv")
    names = {p.rsplit("/", 1)[-1] for p in written}
    assert "heartmetric_comparison.csv" in names
    assert "heartmetric_readings.csv" in names


def test_demo_bundle_is_flagged(bundle):
    demo = pipeline.demo_bundle()
    assert demo["meta"]["demo"] is True
    assert demo["meta"]["input"]["data"] == "synthetic"
