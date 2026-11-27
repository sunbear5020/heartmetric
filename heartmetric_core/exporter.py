"""Export a HEARTMETRIC analysis to Excel, CSV, JSON or a Markdown report.

The Excel workbook is meant to be handed to a co-author: it opens on a README
sheet that states the license, the data source, the method and what each sheet
holds. The Markdown report is the same result in a form that survives a chat
message, a pull request or a preprint appendix.

License: MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University
"""

from __future__ import annotations

import io
import json
import math
from pathlib import Path
from typing import Any, Dict, Mapping

import pandas as pd

from .schema import STANDARD_COLUMNS

LICENSE_LINE = "MIT License · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University"
SCHEMA_VERSION_FALLBACK = "0.3.0"


def _frame_from_records(records: Any, columns: list[str] | None = None) -> pd.DataFrame:
    if records is None:
        return pd.DataFrame()
    if isinstance(records, pd.DataFrame):
        return records.copy()
    if isinstance(records, list) and records and isinstance(records[0], dict):
        frame = pd.DataFrame(records)
        if columns:
            for column in columns:
                if column not in frame.columns:
                    frame[column] = None
            frame = frame[[c for c in columns if c in frame.columns]]
        return frame
    return pd.DataFrame()


def methodology_frame(bundle: Mapping[str, Any]) -> pd.DataFrame:
    """The provenance block as a flat sheet (one indicator per row)."""
    block = bundle.get("methodology") or {}
    indicators = block.get("indicators") if isinstance(block, dict) else None
    if not indicators and isinstance(block, dict):
        indicators = {k: v for k, v in block.items() if isinstance(v, dict)}
    rows = []
    for key, record in (indicators or {}).items():
        rows.append(
            {
                "indicator": key,
                "label": record.get("label"),
                "unit": record.get("unit"),
                "kind": record.get("kind"),
                "device": record.get("device"),
                "formula": record.get("formula"),
                "reference": record.get("reference"),
                "boundary": record.get("boundary"),
            }
        )
    return pd.DataFrame(rows)


def gap_map_frame(bundle: Mapping[str, Any]) -> pd.DataFrame:
    """The date × stream gap grid as one row per cell."""
    block = bundle.get("timeline_gap_map") or {}
    if not isinstance(block, dict):
        return pd.DataFrame()
    rows = []
    for cell in block.get("cells", []):
        rows.append(
            {
                "date": cell.get("date"),
                "stream": cell.get("stream"),
                "role": cell.get("role"),
                "status": cell.get("status"),
                "rows": cell.get("rows"),
                "matched_rows": cell.get("matched_rows"),
                "unmatched_rows": cell.get("unmatched_rows"),
                "subjects": ", ".join(cell.get("subjects") or []),
            }
        )
    return pd.DataFrame(rows)


def alignment_frame(bundle: Mapping[str, Any]) -> pd.DataFrame:
    """Per-stream alignment counts, one row per input stream."""
    block = bundle.get("alignment") or (bundle.get("meta") or {}).get("alignment")
    if not block:
        return pd.DataFrame()
    rows = []
    for stream in block.get("streams", []):
        rows.append(
            {
                "stream": stream.get("name"),
                "role": stream.get("role"),
                "rows": stream.get("rows"),
                "matched_rows": stream.get("matched_rows"),
                "unmatched_rows": stream.get("unmatched_rows"),
                "match_rate_pct": stream.get("match_rate_pct"),
                "mode": block.get("mode"),
                "tolerance_minutes": block.get("tolerance_minutes"),
                "overnight_lookback_hours": block.get("overnight_lookback_hours"),
                "lag_median_minutes": (block.get("lag_minutes") or {}).get("median"),
            }
        )
    return pd.DataFrame(rows)


def bundle_frames(bundle: Mapping[str, Any]) -> Dict[str, pd.DataFrame]:
    """Turn an analysis bundle into the sheet set used by both exporters."""
    summary = bundle.get("summary") or {}
    summary_rows = []
    for key, value in summary.items():
        if isinstance(value, (dict, list)):
            continue
        summary_rows.append({"metric": key, "value": value})
    quality = bundle.get("quality") or {}
    quality_rows = [
        {"check": key, "result": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}
        for key, value in quality.items()
    ]

    frames = {
        "Summary": pd.DataFrame(summary_rows),
        "Quality": pd.DataFrame(quality_rows),
        "Alignment": alignment_frame(bundle),
        "GapMap": gap_map_frame(bundle),
        "Conditions": _frame_from_records(bundle.get("conditions")),
        "Exposure": _frame_from_records(bundle.get("exposure")),
        "Comparison": _frame_from_records(bundle.get("comparison")),
        "Daily": _frame_from_records(bundle.get("daily")),
        "Correlations": _frame_from_records(bundle.get("correlations")),
        "Methodology": methodology_frame(bundle),
        "Readings": _frame_from_records(bundle.get("series")),
    }
    return {name: frame for name, frame in frames.items() if not frame.empty}


def _readme_frame(bundle: Mapping[str, Any]) -> pd.DataFrame:
    meta = bundle.get("meta") or {}
    comparison = meta.get("comparison") or {}
    alignment = bundle.get("alignment") or meta.get("alignment") or {}
    paired_by = comparison.get("paired_by") or "unpaired"
    rows = [
        ("Project", "HEARTMETRIC — Environmental Cardiovascular Response Platform"),
        ("Lab", "FEI · HEL Lab, Gyeongsang National University"),
        ("License", LICENSE_LINE),
        ("Generated", meta.get("generated_at", "")),
        ("Version", meta.get("heartmetric_version", "")),
        ("Bundle schema", meta.get("schema_version", SCHEMA_VERSION_FALLBACK)),
        ("Comparison", f"{comparison.get('b', '')} → {comparison.get('a', '')} ({paired_by})"),
        ("Subjects", comparison.get("n_subjects", "—")),
        ("Night window", meta.get("night_window", "")),
        ("Data", meta.get("input", {}).get("data", "user-supplied") if isinstance(meta.get("input"), dict) else "user-supplied"),
        ("", ""),
        (
            "Sheets",
            "Summary · Quality · Alignment · GapMap · Conditions · Exposure · Comparison · Daily · "
            "Correlations · Methodology · Readings",
        ),
        ("Indices", "MAP = DBP + (SBP−DBP)/3 · PP = SBP−DBP · Dipping = (day−night)/day × 100"),
        ("", "HRV recovery = night RMSSD / day RMSSD × 100 (baseline named in the Summary sheet)"),
        ("", "Stress index: 0.30 BP load + 0.25 HRV suppression + 0.20 PM2.5 + 0.15 thermal + 0.10 HR load"),
        ("", "Environmental load (row): mean of PM2.5/35 · |temp−22|/15 · (1−green), each clamped to 0–1"),
        (
            "Statistics",
            "Welch t (independent) · paired t with d_z, sign-flip permutation and exact sign test "
            "(subject-level when subject_id exists) · Pearson r + Spearman ρ + OLS slope",
        ),
        (
            "Multiple comparison",
            "The metrics of one comparison table are one family: raw p is reported beside "
            "Holm-adjusted p and Benjamini–Hochberg q (BH 1995; Holm 1979) — see Comparison",
        ),
        ("Correlation caveat", "Correlation is not causation; autocorrelated series shrink the effective sample size."),
    ]
    if alignment:
        rows.append(
            (
                "Alignment",
                f"{alignment.get('mode')} · tolerance {alignment.get('tolerance_minutes')} min · "
                f"matched {alignment.get('anchors_matched')}/{alignment.get('anchors')} "
                f"({alignment.get('match_rate_pct')}%)",
            )
        )
        if alignment.get("mode") == "overnight_morning":
            lag = alignment.get("lag_minutes") or {}
            rows.append(
                (
                    "Overnight preset",
                    f"morning cuff {alignment.get('morning_window')} · look-back "
                    f"{alignment.get('overnight_lookback_hours')} h · median lag "
                    f"{lag.get('median')} min (n={lag.get('n')})",
                )
            )
    gap_summary = bundle.get("timeline_gap_map", {}).get("summary") if isinstance(bundle.get("timeline_gap_map"), dict) else None
    if gap_summary:
        rows.append(
            (
                "Gap map",
                f"{gap_summary.get('dates')} days × {gap_summary.get('streams')} streams · "
                f"matched {gap_summary.get('cells_matched')} / partial {gap_summary.get('cells_partial')} / "
                f"unmatched {gap_summary.get('cells_unmatched')} / missing {gap_summary.get('cells_missing')}",
            )
        )
    rows += [
        ("", ""),
        (
            "Disclaimer",
            "These are research descriptors of the submitted time series, not a diagnosis. "
            "A cuff measurement and a clinician remain the reference. HEARTMETRIC is not "
            "affiliated with Oura Health Oy or Apple Inc.",
        ),
        ("Contact", "bkim5020@gnu.ac.kr"),
    ]
    return pd.DataFrame(rows, columns=["item", "detail"])


def to_excel(
    bundle: Mapping[str, Any] | pd.DataFrame,
    path: str | Path | None = None,
    *,
    sheet_order: list[str] | None = None,
) -> bytes | str:
    """Write a multi-sheet workbook; returns bytes when no path is given."""
    if isinstance(bundle, pd.DataFrame):
        bundle = {"series": bundle.to_dict(orient="records"), "meta": {}}
    frames = bundle_frames(bundle)
    order = sheet_order or [
        "Summary", "Quality", "Alignment", "GapMap", "Conditions", "Exposure", "Comparison",
        "Daily", "Correlations", "Methodology", "Readings",
    ]
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _readme_frame(bundle).to_excel(writer, sheet_name="README", index=False)
        for name in order:
            frame = frames.get(name)
            if frame is None or frame.empty:
                continue
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            worksheet = writer.sheets[name[:31]]
            for index, column in enumerate(frame.columns, start=1):
                width = max(10, min(42, int(max([len(str(column))] + [len(str(v)) for v in frame[column].head(200)]) + 2)))
                worksheet.column_dimensions[worksheet.cell(row=1, column=index).column_letter].width = width
            worksheet.freeze_panes = "A2"
    payload = buffer.getvalue()
    if path is None:
        return payload
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_bytes(payload)
    return str(path)


def to_csv(frame: pd.DataFrame, path: str | Path | None = None, *, encoding: str = "utf-8-sig") -> bytes | str:
    """Write one table as CSV (UTF-8 with BOM so Excel opens Korean text)."""
    working = frame.copy()
    for column in STANDARD_COLUMNS:
        if column not in working.columns and column == "timestamp":
            working[column] = None
    payload = working.to_csv(index=False, encoding=encoding)
    if path is None:
        return payload.encode(encoding)
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_text(payload, encoding=encoding)
    return str(path)


def to_csv_dir(bundle: Mapping[str, Any], directory: str | Path) -> list[str]:
    """Write each table of a bundle as its own CSV; returns the file paths."""
    target = Path(str(directory))
    target.mkdir(parents=True, exist_ok=True)
    written = []
    for name, frame in bundle_frames(bundle).items():
        path = target / f"heartmetric_{name.lower()}.csv"
        frame.to_csv(path, index=False, encoding="utf-8-sig")
        written.append(str(path))
    return written


def to_json(bundle: Mapping[str, Any], path: str | Path | None = None, *, indent: int = 2) -> bytes | str:
    payload = json.dumps(bundle, ensure_ascii=False, indent=indent, allow_nan=False)
    if path is None:
        return payload.encode("utf-8")
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_text(payload, encoding="utf-8")
    return str(path)


# --------------------------------------------------------------- markdown


def _fmt(value: Any, digits: int = 1) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        if value != value:  # NaN
            return "—"
        return f"{value:.{digits}f}"
    return str(value)


#: Columns whose value is a p-value or an adjusted p-value: 0.0000 is not a
#: report of certainty, so these are printed with scientific notation when tiny.
P_VALUE_COLUMNS = frozenset(
    {"p_value", "p_holm", "q_value_bh", "permutation_p", "sign_test_p",
     "pearson_p", "spearman_p", "slope_p", "mann_whitney_p"}
)


def _fmt_p(value: Any) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return "—"
    if number == 0:
        return "<1e-300"
    if number < 0.0001:
        return f"{number:.2e}"
    return f"{number:.4f}"


def _markdown_table(frame: pd.DataFrame, columns: list[str] | None = None, digits: int = 2) -> str:
    if frame is None or frame.empty:
        return "_no rows_"
    columns = [c for c in (columns or list(frame.columns)) if c in frame.columns]
    if not columns:
        return "_no rows_"
    header = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, rule]
    for _, row in frame.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            if column in P_VALUE_COLUMNS:
                cells.append(_fmt_p(value))
            elif isinstance(value, float):
                cells.append(_fmt(value, digits))
            else:
                cells.append("—" if value is None or value == "" else str(value))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def to_markdown(bundle: Mapping[str, Any], path: str | Path | None = None) -> str:
    """Render the bundle as a Markdown report (Korean headings, same numbers)."""
    meta = bundle.get("meta") or {}
    summary = bundle.get("summary") or {}
    quality = bundle.get("quality") or {}
    comparison = _frame_from_records(bundle.get("comparison"))
    correlations = _frame_from_records(bundle.get("correlations"))
    conditions = _frame_from_records(bundle.get("conditions"))
    alignment = bundle.get("alignment") or meta.get("alignment") or {}
    gap_map = bundle.get("timeline_gap_map") if isinstance(bundle.get("timeline_gap_map"), dict) else {}
    multiple_comparison = bundle.get("multiple_comparison") or meta.get("multiple_comparison") or {}
    methodology = methodology_frame(bundle)
    comparison_meta = meta.get("comparison") or {}

    lines: list[str] = []
    lines.append("# HEARTMETRIC 분석 리포트")
    lines.append("")
    lines.append(
        f"**FEI · HEL Lab, 경상국립대학교** · v{meta.get('heartmetric_version', '0.3.0')} "
        f"(bundle schema {meta.get('schema_version', SCHEMA_VERSION_FALLBACK)})  "
    )
    lines.append(f"생성: {meta.get('generated_at', '—')} · 100% 로컬 실행 · MIT License")
    lines.append("")
    lines.append(
        "> 연구 요약입니다. 진단이 아니며, 커프 혈압 측정과 의료진의 판단이 언제나 기준입니다. "
        "Oura Health Oy · Apple Inc.와 제휴하지 않은 독립 프로젝트입니다."
    )
    lines.append("")

    rows_out = quality.get("rows_out", summary.get("rows"))
    lines.append("## 1. 데이터와 품질")
    lines.append("")
    lines.append(f"- 유효 행: **{rows_out}** / 입력 {quality.get('rows_in', '—')}")
    if quality.get("span"):
        span = quality["span"]
        lines.append(f"- 관측 기간: {span.get('start', '—')} → {span.get('end', '—')} ({span.get('days', '—')}일)")
    conditions_text = ", ".join(f"{k} {v}" for k, v in (quality.get("conditions") or {}).items())
    if conditions_text:
        lines.append(f"- 조건: {conditions_text}")
    lines.append(
        f"- 제거: 범위 밖 {sum((quality.get('removed_out_of_range') or {}).values())}건 · "
        f"모순 쌍 {quality.get('removed_inconsistent', 0)}건 · 중복 {quality.get('duplicates_removed', 0)}건"
    )
    lines.append(f"- 최대 공백: {quality.get('max_gap_hours', '—')}시간 (보정하지 않음)")
    if alignment:
        tolerance_label = "되돌아보기" if alignment.get("mode") == "overnight_morning" else "허용 오차"
        lines.append(
            f"- 스트림 결합: {alignment.get('mode')} · {tolerance_label} {alignment.get('tolerance_minutes')}분 · "
            f"앵커 매칭 {alignment.get('anchors_matched')}/{alignment.get('anchors')}"
            f"({alignment.get('match_rate_pct')}%)"
        )
        if alignment.get("mode") == "overnight_morning":
            lag = alignment.get("lag_minutes") or {}
            window = alignment.get("morning_window") or []
            window_text = f"{window[0]:02d}:00–{window[1]:02d}:00" if len(window) == 2 else "—"
            lines.append(
                f"  - 야간→아침 프리셋: 아침 창 {window_text} · 되돌아보기 "
                f"{alignment.get('overnight_lookback_hours')}시간 · lag 중앙값 {lag.get('median')}분 (n={lag.get('n')})"
            )
            reasons = alignment.get("unmatched_reasons") or {}
            if reasons:
                lines.append(
                    "  - 미결합 사유: " + ", ".join(f"{k} {v}건" for k, v in reasons.items())
                )
        for stream in alignment.get("streams", []):
            lines.append(
                f"  - {stream.get('name')} ({stream.get('role')}): {stream.get('matched_rows')}/{stream.get('rows')}행 결합"
            )
    lines.append("")

    lines.append("## 2. 요약 지표")
    lines.append("")
    lines.append("| 지표 | 값 | 단위 | 근거 구분 |")
    lines.append("| --- | --- | --- | --- |")
    lines.append(f"| 평균 혈압 (SBP/DBP) | {_fmt(summary.get('sbp'), 1)} / {_fmt(summary.get('dbp'), 1)} | mmHg | measured |")
    lines.append(f"| MAP · 맥압 | {_fmt(summary.get('map'), 1)} / {_fmt(summary.get('pp'), 1)} | mmHg | derived |")
    dipping = summary.get("dipping") or {}
    if dipping.get("available"):
        lines.append(
            f"| 야간 하강률 | {_fmt(dipping.get('dipping_pct'), 1)}% ({dipping.get('category')}) | % | derived |"
        )
    recovery = summary.get("hrv_recovery") or {}
    if recovery.get("available"):
        lines.append(
            f"| HRV 회복 지수 | {_fmt(recovery.get('index'), 1)} ({recovery.get('band')}, baseline {recovery.get('baseline')}) | index | derived |"
        )
    stress = summary.get("stress_index") or {}
    if stress.get("available"):
        lines.append(f"| 환경 스트레스 지수 | {_fmt(stress.get('index'), 1)} ({stress.get('band')}) | 0–100 | exploratory |")
    lines.append(f"| 평균 PM2.5 | {_fmt(summary.get('pm25'), 1)} | µg/m³ | measured |")
    lines.append(f"| 평균 기온 | {_fmt(summary.get('temp_c'), 1)} | °C | measured |")
    lines.append("")

    lines.append("## 3. 조건별 비교")
    lines.append("")
    a = comparison_meta.get("a", "A")
    b = comparison_meta.get("b", "B")
    paired_by = comparison_meta.get("paired_by", "unpaired")
    lines.append(f"A = **{a}**, B = **{b}** · 방식: `{paired_by}` · Δ는 A − B")
    lines.append("")
    if not comparison.empty:
        lines.append(
            _markdown_table(
                comparison,
                ["metric", "n_a", "mean_a", "n_b", "mean_b", "diff", "cohens_d", "cohens_dz",
                 "effect", "p_value", "p_holm", "q_value_bh", "significant_fdr_05",
                 "permutation_p", "ci_low", "ci_high"],
            )
        )
        lines.append("")
        lines.append(
            "효과크기: |d| < 0.2 무시 · 0.2–0.5 작음 · 0.5–0.8 중간 · ≥ 0.8 큼. "
            "p는 보정 전 값이고, 같은 표의 지표들을 한 가족으로 본 **Holm 보정 p**와 "
            "**BH-FDR q**를 나란히 표시합니다(`significant_fdr_05`는 q ≤ 0.05). "
            "대응표본에서는 `cohens_dz`를 읽으세요."
        )
        if multiple_comparison:
            lines.append("")
            lines.append(
                f"다중 비교: 가족 크기 m = {multiple_comparison.get('family_size')} · alpha "
                f"{multiple_comparison.get('alpha')} · BH-FDR 유의 {multiple_comparison.get('rejected_bh_fdr')}건 · "
                f"Holm 유의 {multiple_comparison.get('rejected_holm_fw')}건 "
                "(Benjamini & Hochberg 1995; Holm 1979)"
            )
    else:
        lines.append("_조건 두 개 이상의 데이터가 있어야 비교표가 만들어집니다._")
    lines.append("")

    lines.append("## 4. 환경 노출 × 심혈관 상관")
    lines.append("")
    if not correlations.empty:
        lines.append(
            _markdown_table(
                correlations,
                ["x", "y", "n", "pearson_r", "pearson_p", "spearman_rho", "spearman_p",
                 "slope", "slope_p", "r_squared"],
            )
        )
        lines.append("")
        lines.append(
            "r은 선형, ρ는 단조 관계입니다. 기울기는 y = 절편 + 기울기·x 의 OLS 추정치이며 "
            "관측 범위 밖으로 외삽하지 않습니다. 상관은 인과가 아닙니다."
        )
    else:
        lines.append("_환경 지표와 심혈관 지표가 함께 있는 행이 부족합니다._")
    lines.append("")

    lines.append("## 5. 스트림 타임라인 갭 맵")
    lines.append("")
    gap_summary = (gap_map or {}).get("summary") or {}
    if gap_summary and gap_summary.get("cells"):
        lines.append(
            f"{gap_summary.get('dates')}일 × {gap_summary.get('streams')}개 스트림 · "
            f"매칭 {gap_summary.get('cells_matched')} · 부분 {gap_summary.get('cells_partial')} · "
            f"미결합 {gap_summary.get('cells_unmatched')} · 결측 {gap_summary.get('cells_missing')} "
            f"(커버리지 {gap_summary.get('coverage_pct')}%)"
        )
        lines.append("")
        lines.append("| 스트림 | 역할 | 관측일 | 결측일 | 결합 | 미결합 | 결측 | 최장 연속 결측 | 결합률 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for name, entry in (gap_summary.get("per_stream") or {}).items():
            lines.append(
                f"| {name} | {entry.get('role')} | {entry.get('dates_present')} | {entry.get('dates_missing')} | "
                f"{entry.get('cells_matched')} | {entry.get('cells_unmatched')} | {entry.get('cells_missing')} | "
                f"{entry.get('longest_gap_days')}일 | {entry.get('join_rate_pct')}% |"
            )
        lines.append("")
        lines.append(
            "관측이 없는 칸은 **결측**이며 보간·대체하지 않습니다. 스트림마다 관측 기간이 달라 "
            "앞뒤 날짜가 결측으로 보이는 것은 그 날 그 스트림이 없었다는 뜻입니다."
        )
    else:
        lines.append("_스트림을 2개 이상 결합하면 일자×스트림 갭 맵이 만들어집니다._")
    lines.append("")

    lines.append("## 6. 조건별 평균")
    lines.append("")
    lines.append(_markdown_table(conditions))
    lines.append("")

    lines.append("## 7. 지표 정의와 경계")
    lines.append("")
    lines.append("| 지표 | 구분 | 수식 | 경계 |")
    lines.append("| --- | --- | --- | --- |")
    for _, row in methodology.iterrows():
        lines.append(
            f"| {row.get('label')} | {row.get('kind')} | {row.get('formula') or '—'} | {row.get('boundary') or '—'} |"
        )
    lines.append("")
    lines.append(f"인용: FEI · HEL Lab, Gyeongsang National University. (2026). HEARTMETRIC (v{meta.get('heartmetric_version', '0.3.0')}). MIT License.")
    lines.append("")

    text = "\n".join(lines)
    if path is None:
        return text
    Path(str(path)).parent.mkdir(parents=True, exist_ok=True)
    Path(str(path)).write_text(text, encoding="utf-8")
    return str(path)


def save(
    bundle: Mapping[str, Any],
    path: str | Path,
    *,
    fmt: str | None = None,
) -> str:
    """Save by extension (``.xlsx`` / ``.csv`` / ``.json`` / ``.md``)."""
    suffix = (fmt or Path(str(path)).suffix.lstrip(".")).lower()
    if suffix in ("xlsx", "xls", "excel"):
        return str(to_excel(bundle, path))
    if suffix == "csv":
        return str(to_csv(bundle_frames(bundle).get("Readings", pd.DataFrame()), path))
    if suffix == "json":
        return str(to_json(bundle, path))
    if suffix in ("md", "markdown"):
        return str(to_markdown(bundle, path))
    raise ValueError(f"unsupported export format: {suffix}")
