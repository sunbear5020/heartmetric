"""Provenance: what each number is, how it is computed, and where it stops.

Every metric and statistic HEARTMETRIC reports carries a record here:
the formula, the unit, whether it is **measured**, **derived** or
**exploratory**, the reference it follows, and the boundary beyond which it must
not be read. The web workbench renders the same records in its "지표 정의" panel,
so a reader can audit a figure without opening the source.

Kinds
-----
``measured``
    Recorded by a device and passed through QC unchanged (cuff SBP/DBP, wearable
    HR/HRV, environmental sensor values).
``derived``
    A deterministic arithmetic combination of measured values (MAP, pulse
    pressure, dipping, recovery ratio) — reproducible, but not itself measured.
``exploratory``
    A laboratory summary with chosen weights or reference points (stress index,
    environmental load). It orders a series; it is not a clinical score.

License: MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University
"""

from __future__ import annotations

from typing import Any, Dict

from . import __version__

#: Reference anchors used by the indices, with their exact provenance.
REFERENCES: Dict[str, str] = {
    "pm25_35": "WHO (2005) Air Quality Guidelines, 24-hour PM2.5 interim target 1 = 35 µg/m³ "
    "(the 2021 guideline value is 15 µg/m³; HEARTMETRIC keeps 35 as an explicitly named interim target)",
    "rmssd_50": "RMSSD ≈ 50 ms as a typical healthy adult nightly average — a descriptive anchor, not a cut-off",
    "hr_55_95": "Resting heart rate span 55–95 bpm used only to place a mean on a 0–1 scale",
    "thermal_22": "22 °C as a thermal-comfort centre with a ±15 °C span — laboratory convention, not a standard",
    "dipping": "Ambulatory BP convention: normal 10–20 %, non-dipper 0–10 %, reverse < 0 %, extreme > 20 %",
    "welch": "Welch, B. L. (1947). The generalization of Student's problem. Biometrika 34:28–35",
    "paired_t": "Student (1908); paired t-test on within-subject differences, df = n − 1",
    "cohens_d": "Cohen, J. (1988). Statistical Power Analysis for the Behavioral Sciences, 2nd ed.",
    "cohens_dz": "Lakens, D. (2013). Calculating and reporting effect sizes. Frontiers in Psychology 4:863",
    "permutation": "Sign-flip randomization test: under H0 the two conditions are exchangeable within a subject",
    "sign_test": "Exact two-sided binomial sign test on the direction of paired differences",
    "wilcoxon": "Wilcoxon, F. (1945). Individual comparisons by ranking methods. Biometrics Bulletin 1:80–83",
    "pearson": "Pearson product-moment correlation; p from t = r·√((n−2)/(1−r²)) with df = n − 2",
    "spearman": "Spearman rank correlation with average ranks for ties; p uses the same t approximation",
    "ols": "Ordinary least squares y = b0 + b1·x; slope tested with t = b1/SE(b1), df = n − 2",
    "mann_whitney": "Mann–Whitney U with tie-corrected normal approximation (two-sided)",
    "benjamini_hochberg": "Benjamini, Y. & Hochberg, Y. (1995). Controlling the false discovery rate: "
    "a practical and powerful approach to multiple testing. Journal of the Royal Statistical Society B 57(1):289–300",
    "holm_bonferroni": "Holm, S. (1979). A simple sequentially rejective multiple test procedure. "
    "Scandinavian Journal of Statistics 6(2):65–70",
    "overnight_morning": "Alignment preset, not a statistic: the anchor is a morning cuff reading and only rows "
    "recorded before it (default 14 h look-back) may join — the shape of an Oura nightly aggregate "
    "(placed at 03:00 of its day) plus a post-waking cuff; Oura API v2 has no blood-pressure endpoint",
    "timeline_gap_map": "Coverage audit of the aligned table: rows written and rows joined per stream and "
    "calendar day, with missing days reported as missing (no interpolation, no shifting, no filling)",
}

METHODOLOGY: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------ measured
    "sbp": {
        "label": "수축기 혈압 (SBP)",
        "unit": "mmHg",
        "kind": "measured",
        "device": "cuff blood-pressure monitor (Apple Health export or CSV)",
        "formula": None,
        "reference": None,
        "boundary": "커프 측정만이 혈압의 근거입니다. Oura Ring과 Oura API v2는 mmHg 혈압을 제공하지 않으므로 링에서 혈압을 읽지 않습니다.",
    },
    "dbp": {
        "label": "이완기 혈압 (DBP)",
        "unit": "mmHg",
        "kind": "measured",
        "device": "cuff blood-pressure monitor",
        "formula": None,
        "reference": None,
        "boundary": "동일 세션의 SBP와 짝을 이룹니다. SBP ≤ DBP인 모순 쌍은 분석에서 제외하고 QC에 기록합니다.",
    },
    "hr": {
        "label": "심박수 (HR)",
        "unit": "bpm",
        "kind": "measured",
        "device": "wearable (Oura · Apple Watch) or CSV",
        "formula": None,
        "reference": None,
        "boundary": "기기별 평균 구간이 다릅니다(야간 평균·안정 심박·순간 심박). 어떤 평균인지 파일의 열 이름으로만 판단합니다.",
    },
    "rmssd": {
        "label": "HRV — RMSSD",
        "unit": "ms",
        "kind": "measured",
        "device": "Oura (average_hrv) or CSV",
        "formula": None,
        "reference": "RMSSD = √(mean of squared successive R-R differences)",
        "boundary": "Oura는 RMSSD를, Apple Health는 SDNN을 보고합니다. 두 값을 서로 변환하지 않습니다.",
    },
    "sdnn": {
        "label": "HRV — SDNN",
        "unit": "ms",
        "kind": "measured",
        "device": "Apple Health (HKQuantityTypeIdentifierHeartRateVariabilitySDNN)",
        "formula": None,
        "reference": "SDNN = standard deviation of N-N intervals",
        "boundary": "SDNN과 RMSSD는 서로 다른 양이고 기록 구간도 다릅니다. 한쪽이 없으면 그 사실을 표시하고 다른 쪽으로 대체하지 않습니다.",
    },
    "temp_c": {
        "label": "기온",
        "unit": "°C",
        "kind": "measured",
        "device": "weather station · portable sensor · CSV",
        "formula": None,
        "reference": None,
        "boundary": "측정 지점의 대표값이며 개인의 실제 노출(체감·옷차림·그늘)과 다를 수 있습니다.",
    },
    "humidity_pct": {
        "label": "상대습도",
        "unit": "%",
        "kind": "measured",
        "device": "weather station · portable sensor",
        "formula": None,
        "reference": None,
        "boundary": "상대습도는 기온에 따라 같은 수분량도 다른 값을 줍니다.",
    },
    "pm25": {
        "label": "초미세먼지 (PM2.5)",
        "unit": "µg/m³",
        "kind": "measured",
        "device": "air-quality station · sensor · CSV",
        "formula": None,
        "reference": REFERENCES["pm25_35"],
        "boundary": "측정소 값은 개인 흡입량이 아닙니다. 24시간 기준값과 순간 측정을 같은 것으로 읽지 않습니다.",
    },
    "pm10": {
        "label": "미세먼지 (PM10)",
        "unit": "µg/m³",
        "kind": "measured",
        "device": "air-quality station · sensor",
        "formula": None,
        "reference": None,
        "boundary": "PM10과 PM2.5는 다른 입자 크기 구간입니다.",
    },
    "green_index": {
        "label": "녹지지수",
        "unit": "0–1",
        "kind": "measured",
        "device": "NDVI-like greenery index from a map/sensor source",
        "formula": None,
        "reference": None,
        "boundary": "0–1로 정규화된 지수이며 0–100 스케일 파일은 자동으로 1/100 합니다. 측정 반경이 파일마다 다를 수 있습니다.",
    },
    "forest": {
        "label": "산림 여부",
        "unit": "0 / 1",
        "kind": "measured",
        "device": "protocol label",
        "formula": None,
        "reference": None,
        "boundary": "프로토콜 라벨이며 실제 수관 피복률이 아닙니다.",
    },
    "steps": {
        "label": "걸음 수",
        "unit": "count",
        "kind": "measured",
        "device": "wearable / phone",
        "formula": None,
        "reference": None,
        "boundary": "활동량 보정 변수로만 쓰이며 심혈관 지표가 아닙니다.",
    },
    # ------------------------------------------------------------- derived
    "map": {
        "label": "평균동맥압 (MAP)",
        "unit": "mmHg",
        "kind": "derived",
        "device": None,
        "formula": "MAP = DBP + (SBP − DBP) / 3",
        "reference": "Standard approximation of mean arterial pressure over the cardiac cycle",
        "boundary": "근사식입니다. 실제 MAP는 동맥압 파형의 적분이며, 이 값은 SBP/DBP 두 점에서 계산한 추정치입니다.",
    },
    "pp": {
        "label": "맥압 (Pulse pressure)",
        "unit": "mmHg",
        "kind": "derived",
        "device": None,
        "formula": "PP = SBP − DBP",
        "reference": None,
        "boundary": "큰 맥압은 동맥 경직 신호일 수 있으나 이 도구는 진단하지 않습니다. 100 mmHg 초과는 플래그만 남깁니다.",
    },
    "dipping": {
        "label": "야간 하강률",
        "unit": "%",
        "kind": "derived",
        "device": None,
        "formula": "dipping = (day mean − night mean) / day mean × 100",
        "reference": REFERENCES["dipping"],
        "boundary": "야간 창은 기본 22:00–06:00이며 주·야 각 2회 이상이 필요합니다. 수면 시간이 아니라 시계 시간으로 나눕니다.",
    },
    "hrv_recovery": {
        "label": "HRV 회복 지수",
        "unit": "index (100 = no night rise)",
        "kind": "derived",
        "device": None,
        "formula": "index = night RMSSD / day RMSSD × 100",
        "reference": "Night-to-day HRV ratio as a recovery descriptor",
        "boundary": "임상 기준값이 없습니다. 야간 측정이 없으면 그날 첫 측정을 기저로 쓰며 그 사실을 'baseline'에 표기합니다.",
    },
    "bp_load": {
        "label": "혈압 부하 (BP load)",
        "unit": "%",
        "kind": "derived",
        "device": None,
        "formula": "share of readings with SBP ≥ 130 or DBP ≥ 80",
        "reference": "Ambulatory BP load convention (thresholds adjustable in the code)",
        "boundary": "역치 130/80은 코드에서 바꿀 수 있는 관례값이며, 비율은 진단이 아닙니다.",
    },
    "env_load": {
        "label": "환경 부하 (행별)",
        "unit": "0–1",
        "kind": "exploratory",
        "device": None,
        "formula": "mean of available: PM2.5/35 (clamped) · |temp − 22|/15 (clamped) · (1 − green_index)",
        "reference": f"{REFERENCES['pm25_35']} · {REFERENCES['thermal_22']}",
        "boundary": "가중치를 같게 둔 탐색 지표입니다. 혈압·HRV를 포함하지 않아 상관분석에서 순환논리를 피했습니다.",
    },
    "stress_index": {
        "label": "환경 스트레스 지수",
        "unit": "0–100",
        "kind": "exploratory",
        "device": None,
        "formula": "0.30·BP load + 0.25·HRV suppression + 0.20·PM2.5 + 0.15·thermal + 0.10·HR load (missing components dropped, weights renormalized)",
        "reference": f"{REFERENCES['pm25_35']} · {REFERENCES['rmssd_50']} · {REFERENCES['thermal_22']}",
        "boundary": "연구실 요약 지수이며 임상 위험 점수가 아닙니다. 가중치는 선택값이므로 다른 가중치에서는 순위가 달라질 수 있습니다.",
    },
    # ------------------------------------------------------------ statistics
    "welch_t": {
        "label": "Welch t-test (독립표본)",
        "unit": "t, df, p",
        "kind": "derived",
        "device": None,
        "formula": "t = (x̄a − x̄b) / √(s²a/na + s²b/nb), Welch–Satterthwaite df",
        "reference": REFERENCES["welch"],
        "boundary": "두 조건이 서로 다른 관측일 때 씁니다. 같은 사람의 반복 측정에는 대응표본을 쓰세요.",
    },
    "paired_t": {
        "label": "대응표본 t-test",
        "unit": "t, df = n−1, p",
        "kind": "derived",
        "device": None,
        "formula": "t = mean(d) / (SD(d)/√n), d = a − b per subject",
        "reference": REFERENCES["paired_t"],
        "boundary": "subject_id가 양쪽 조건에 모두 있어야 합니다. 없으면 시간 순서 짝짓기로 대체하며 그 사실을 표시합니다.",
    },
    "cohens_d": {
        "label": "Cohen's d",
        "unit": "SD units",
        "kind": "derived",
        "device": None,
        "formula": "d = (x̄a − x̄b) / pooled SD",
        "reference": REFERENCES["cohens_d"],
        "boundary": "0.2/0.5/0.8은 관례적 크기 구간이며 분야·설계에 따라 달라집니다.",
    },
    "cohens_dz": {
        "label": "Cohen's d_z (대응)",
        "unit": "SD units",
        "kind": "derived",
        "device": None,
        "formula": "d_z = mean(a − b) / SD(a − b)",
        "reference": REFERENCES["cohens_dz"],
        "boundary": "대응 설계의 효과크기입니다. 독립표본 d와 같은 숫자 축으로 직접 비교하지 않습니다.",
    },
    "permutation_p": {
        "label": "순열(sign-flip) p",
        "unit": "p",
        "kind": "derived",
        "device": None,
        "formula": "share of 5,000 sign-flipped mean differences ≥ observed |mean difference| (seed 5020)",
        "reference": REFERENCES["permutation"],
        "boundary": "분포 가정이 없는 대안입니다. 몬테카를로 근사이므로 아주 작은 p는 해상도 한계(≈2×10⁻⁴)가 있습니다.",
    },
    "sign_test_p": {
        "label": "부호 검정 p",
        "unit": "p",
        "kind": "derived",
        "device": None,
        "formula": "two-sided binomial test on the number of positive differences",
        "reference": REFERENCES["sign_test"],
        "boundary": "차이의 크기를 무시하고 방향만 봅니다. 차이가 0인 쌍은 제외합니다.",
    },
    "mann_whitney_u": {
        "label": "Mann–Whitney U",
        "unit": "U, p",
        "kind": "derived",
        "device": None,
        "formula": "rank-sum U with tie-corrected normal approximation",
        "reference": REFERENCES["mann_whitney"],
        "boundary": "순위 기반이라 정규성을 가정하지 않지만, 분포 모양이 다르면 '중앙값 차이'로만 읽어야 합니다.",
    },
    "pearson_r": {
        "label": "Pearson r",
        "unit": "−1…1",
        "kind": "derived",
        "device": None,
        "formula": "r = Σ(x−x̄)(y−ȳ) / √(Σ(x−x̄)²·Σ(y−ȳ)²)",
        "reference": REFERENCES["pearson"],
        "boundary": "선형 관계만 봅니다. 시계열 자기상관이 있으면 p값이 실제보다 작아집니다(유효표본 감소).",
    },
    "spearman_rho": {
        "label": "Spearman ρ",
        "unit": "−1…1",
        "kind": "derived",
        "device": None,
        "formula": "Pearson correlation of average ranks",
        "reference": REFERENCES["spearman"],
        "boundary": "단조 관계를 봅니다. 동점이 많으면 ρ가 압축됩니다.",
    },
    "ols_slope": {
        "label": "단순 선형회귀 기울기",
        "unit": "y unit per x unit",
        "kind": "derived",
        "device": None,
        "formula": "b1 = Σ(x−x̄)(y−ȳ)/Σ(x−x̄)², b0 = ȳ − b1·x̄",
        "reference": REFERENCES["ols"],
        "boundary": "관측 범위 밖으로 외삽하지 않습니다. 다중 공변량(활동량·수면·계절)은 보정하지 않습니다.",
    },
    # ------------------------------------------------- v0.3 multiple comparison
    "benjamini_hochberg": {
        "label": "BH-FDR 보정 q-값",
        "unit": "q (adjusted p, 0–1)",
        "kind": "derived",
        "device": None,
        "formula": "오름차순 p_(i)에 대해 q_(i) = min_{j≥i} ( m · p_(j) / j ), 0–1로 절단; q ≤ 0.05면 FDR 5%에서 유의",
        "reference": REFERENCES["benjamini_hochberg"],
        "boundary": "같은 표에서 동시에 검정한 지표 수 m이 기준입니다. 지표를 추가·제거하면 q가 바뀌므로, 표에 없는 지표를 \"검정하지 않은 것\"으로 읽지 마세요. FDR은 거짓 발견의 기대 비율을 통제하며 가족 단위 오류율(FWER)보다 덜 보수적입니다.",
    },
    "holm_bonferroni": {
        "label": "Holm–Bonferroni 보정 p",
        "unit": "p_holm (0–1)",
        "kind": "derived",
        "device": None,
        "formula": "오름차순 p_(i)에 대해 p_holm_(i) = max_{j≤i} min(1, (m − j + 1) · p_(j)); p_holm ≤ 0.05면 FWER 5%에서 유의",
        "reference": REFERENCES["holm_bonferroni"],
        "boundary": "Bonferroni보다 검정력이 높지만 BH-FDR보다 보수적입니다. 두 보정이 다른 결론을 내면 \"보정 방법에 따라 달라진다\"고 보고해야 하며, 유리한 쪽만 골라 쓰지 않습니다.",
    },
    "overnight_morning": {
        "label": "야간 → 아침 커프 결합 (overnight_morning)",
        "unit": "align (n rows, lag minutes)",
        "kind": "derived",
        "device": None,
        "formula": "anchor = 05:00–12:00의 커프 행; 동일 subject_id의 다른 스트림 행 중 0 ≤ (anchor − 관측) ≤ 14시간인 행을 가장 가까운 것부터 역할별 1개씩 결합",
        "reference": REFERENCES["overnight_morning"],
        "boundary": "결합은 열을 나란히 놓는 일이며 값을 옮기거나 보간하지 않습니다. 야간 집계는 실제 수면 구간의 평균이고 03:00에 배치된 값이므로 lag_minutes를 항상 함께 읽으세요. 14시간 밖의 관측은 결합하지 않고 미결합 사유로 남깁니다.",
    },
    "timeline_gap_map": {
        "label": "스트림 타임라인 갭 맵",
        "unit": "date × stream cell",
        "kind": "derived",
        "device": None,
        "formula": "cell.status = matched(모든 행 결합) · partial(일부 결합) · unmatched(행은 있으나 미결합) · missing(그날 관측 없음); span은 전체 관측의 첫날–마지막날",
        "reference": REFERENCES["timeline_gap_map"],
        "boundary": "관측이 없는 칸은 결측이며 보간·대체하지 않습니다. 스트림마다 관측 기간이 다르면 앞뒤 칸이 missing으로 보이는 것은 정상이며, 그 자체가 \"그 날 그 스트림이 없었다\"는 정보입니다.",
    },
}


def methodology() -> Dict[str, Any]:
    """The provenance block embedded in every exported bundle."""
    return {
        "version": __version__,
        "note": "measured = recorded by a device; derived = arithmetic on measured values; "
        "exploratory = laboratory summary with chosen weights. None of these is a diagnosis.",
        "references": dict(REFERENCES),
        "indicators": {key: dict(value) for key, value in METHODOLOGY.items()},
    }


def indicator(key: str) -> Dict[str, Any]:
    """One indicator's record (empty dict when the key is unknown)."""
    return dict(METHODOLOGY.get(key, {}))
