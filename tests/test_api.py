from __future__ import annotations

import io
import json

import pandas as pd
import pytest

from fastapi.testclient import TestClient

from api.server import app
from heartmetric_core import synthetic

client = TestClient(app)


def test_root_and_health():
    assert client.get("/api/health").json()["status"] == "ok"
    root = client.get("/").json()
    assert root["name"] == "HEARTMETRIC"
    assert "not affiliated" in root["affiliation"]


def test_sample_returns_records():
    payload = client.get("/api/sample?days=4").json()
    assert payload["meta"]["seed"] == 5020
    assert len(payload["records"]) == 20
    assert {"timestamp", "sbp", "rmssd", "condition"} <= set(payload["records"][0])


def test_analyze_demo_flag():
    response = client.post("/api/analyze", json={"demo": True})
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["summary"]["available"] is True
    assert bundle["quality"]["rows_out"] > 60


def test_analyze_records_payload():
    frame = synthetic.generate(include_anomalies=False).head(20)
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    response = client.post("/api/analyze", json={"records": records, "group_a": "forest", "group_b": "urban"})
    assert response.status_code == 200
    bundle = response.json()
    assert bundle["quality"]["rows_in"] == 20


def test_analyze_uploaded_csv():
    frame = synthetic.generate(include_anomalies=False).head(20)
    csv_bytes = frame.to_csv(index=False).encode("utf-8-sig")
    response = client.post(
        "/api/analyze",
        files={"file": ("heartmetric.csv", io.BytesIO(csv_bytes), "text/csv")},
    )
    assert response.status_code == 200
    assert response.json()["summary"]["available"] is True


def test_export_workbook():
    frame = synthetic.generate(include_anomalies=False).head(20)
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    response = client.post("/api/export?fmt=xlsx", json={"records": records})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    book = pd.ExcelFile(io.BytesIO(response.content))
    assert "Summary" in book.sheet_names


def test_export_json_and_csv():
    frame = synthetic.generate(include_anomalies=False).head(12)
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    exported = client.post("/api/export?fmt=json", json={"records": records})
    assert exported.json()["summary"]["rows"] == 12
    csv_response = client.post("/api/export?fmt=csv", json={"records": records})
    assert csv_response.status_code == 200
    assert "timestamp" in csv_response.text.splitlines()[0]


def test_bad_body_is_422():
    response = client.post("/api/analyze", json={"nothing": 1})
    assert response.status_code == 422


def test_methodology_endpoint():
    payload = client.get("/api/methodology").json()
    assert payload["version"] == "0.3.0"
    assert payload["indicators"]["sbp"]["kind"] == "measured"
    assert payload["indicators"]["env_load"]["kind"] == "exploratory"


def test_export_markdown():
    frame = synthetic.generate(include_anomalies=False).head(20)
    records = json.loads(frame.to_json(orient="records", date_format="iso"))
    response = client.post("/api/export?fmt=md", json={"records": records})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "HEARTMETRIC" in response.text


def test_analyze_reports_paired_by():
    cohort = synthetic.generate_cohort(subjects=4, days=4)
    records = json.loads(cohort.to_json(orient="records", date_format="iso"))
    response = client.post("/api/analyze", json={"records": records, "paired": True})
    bundle = response.json()
    assert bundle["meta"]["comparison"]["paired_by"] == "subject"
    assert bundle["meta"]["schema_version"] == "0.3.0"
