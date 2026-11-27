# HEARTMETRIC Core (v0.3.0)

**Environmental Cardiovascular Response Platform**
Blood Pressure · Heart Rate · HRV · Environmental Exposure

경상국립대학교 **FEI · HEL Lab**이 만든 클린룸(Clean-room) MIT 오픈소스 연구 엔진입니다.
커프 혈압(Apple Health export) · 웨어러블 심박/HRV(Oura, Apple Watch) · 환경 노출
(기온 · PM2.5 · 녹지/산림)을 **하나의 표준 테이블**로 결합해, 도시 가로와 산림치유
조건의 심혈관 반응을 같은 방법으로 계산하고 비교합니다.

> 100% 합성 데모 데이터 · 외부 전송 없음(브라우저 워크벤치) · MIT
> Oura · Apple 비제휴 독립 프로젝트

```
pip install -e .
python -m heartmetric_core --demo -o report.xlsx
```

## v0.3.0에서 달라진 것

| 영역 | v0.2.0 | v0.3.0 |
| --- | --- | --- |
| 다중 비교 | 없음(지표마다 p를 따로 읽음) | **BH-FDR `q_value_bh` · Holm `p_holm`** — 비교표의 지표를 한 가족으로 보고 원 p 옆에 함께 보고, `significant_fdr_05` 플래그와 가족 크기 `m`을 번들에 기록 |
| 야간→아침 결합 | 넓은 허용 오차나 일별 집계로 우회 | **`mode="overnight_morning"`** — 아침 커프(05:00–12:00)를 앵커로 직전 14시간의 야간 행만 결합, 매치마다 `lag_minutes`·미결합 사유 기록 |
| 타임라인 | 스트림별 총계만 | **스트림 타임라인 갭 맵** — 일자×스트림 격자에 matched / partial / unmatched / missing, 스트림별 최장 연속 결측 |
| 내보내기 | schema `0.2.0`, 10시트, 6장 | **schema `0.3.0`**, `GapMap` 시트·갭 맵 절 포함, Markdown 7장, BH/Holm 열 |
| 워크벤치 | 허용 오차·일별 | **야간→아침 프리셋**, **갭 맵 패널**, **BH q-값 열** |
| 테스트 | 87 | **124** |

## v0.2.0에서 달라진 것

| 영역 | v0.1.0 | v0.2.0 |
| --- | --- | --- |
| 입력 | 파일 1개 | **여러 스트림을 시간 허용 오차로 결합** — `align_streams()`, `--merge`, 다중 `-i`, `--tolerance-minutes`, `--align-mode daily` |
| 표준 테이블 | 16열 | `subject_id` 추가(피험자 단위 대응 설계) |
| 비교 | Welch t · Row-wise paired t | **subject_id 대응표본** — 대응 t, **Cohen's d_z**, **sign-flip 순열 p**, **정확 부호검정**, 사후 Wilcoxon, 95% CI |
| 상관 | Pearson r(간단 표) | **Pearson r · Spearman ρ · 단순 선형회귀 기울기/절편/기울기 p/95% CI · R²**, 환경 전용 파생지수 `env_load` |
| 근거 | 문서 산문 | **`provenance.METHODOLOGY`** — 지표마다 수식·단위·참고문헌·경계, measured / derived / exploratory 구분 |
| 내보내기 | xlsx · csv · json | + **Markdown 리포트**, Excel `Methodology`·`Alignment` 시트, `schema_version: "0.2.0"` 번들 |
| 워크벤치 | 단일 파일 | **다중 파일 결합 업로드 + 허용 오차 선택**, 대응표본 전환, 환경 산점도(ρ·회귀선·기울기 p), 지표 정의 패널, JSON/ Markdown 내보내기 |
| 테스트 | 45 | **87** |

---

## 1. 왜 이런 구조인가 — 하드웨어/API 경계

| 스트림 | 출처 | 값 |
| --- | --- | --- |
| 혈압 SBP/DBP | **커프 혈압계** → Apple Health CSV/XML, 또는 아무 CSV | mmHg |
| 심박수 | Oura · Apple Watch export (CSV/JSON), Apple Health XML | bpm |
| HRV | Oura `average_hrv`(rMSSD), Apple Health `HRV SDNN` | ms |
| 환경 노출 | 기상청 · 에어코리아 · 산림청 또는 연구 자체 로거 | °C, %, µg/m³, 녹지 0–1 |

**Oura Ring은 mmHg 혈압을 제공하지 않습니다.** Oura API v2에는 혈압 엔드포인트가
없고, 앱의 야간 BP 추세는 PPG 기반 추정치로 제3자 소프트웨어에 수치를 넘기지
않습니다. 그래서 HEARTMETRIC은 **커프 측정만을 혈압의 근거로** 두고, 링/워치는
심박·HRV·수면 시점을 담당하게 합니다. Apple Health는 HRV를 **SDNN**으로 저장하고
Oura는 **RMSSD**를 보고하므로, 둘을 서로 변환하지 않고 어느 쪽이 있는지 표시합니다.

자세한 경계와 비제휴 고지는 [`NOTICE.md`](NOTICE.md)에 있습니다.

## 2. 설치

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[api,dev]"      # 엔진 + FastAPI + 테스트
```

의존성은 `numpy` · `pandas` · `openpyxl` 뿐입니다(통계 함수는 자체 구현, SciPy 불필요).

## 3. 빠른 시작

### CLI — 합성 데모 14일

```bash
python -m heartmetric_core --demo -o report.xlsx
```

```
rows: 70 / 71 · conditions: {'urban': 35, 'forest': 35}
mean SBP/DBP: 128.7 / 80.8 mmHg · MAP 96.8 · PP 47.9
HRV recovery index: 122.6 (enhanced recovery, baseline night)
nocturnal dipping: 11.3% (normal dipping)
environmental stress index: 38.0 (moderate)
    sbp: 126.97 vs 130.58 (Δ -3.61, d=-0.51, p=0.0410, by unpaired)
  rmssd: 46.49 vs 40.71 (Δ 5.78, d=1.12, p<0.0001, by unpaired)
```

### CLI — 스트림 결합 (v0.2)

```bash
# 혈압 · 웨어러블 · 환경 CSV를 30분 허용 오차로 결합해 분석
python -m heartmetric_core \
  -i examples/streams/cuff_bp.csv \
  -i examples/streams/wearable.csv \
  -i examples/streams/environment.csv \
  --merge --tolerance-minutes 30 -o report.md

# 일별 집계로 결합(야간 HRV 집계처럼 시각이 다른 스트림에 적합)
python -m heartmetric_core -i bp.csv -i oura.json --align-mode daily -o daily.md

# 대응표본(피험자 단위) + 순열·부호검정
python -m heartmetric_core -i cohort.csv --paired --paired-by subject -o cohort.xlsx
```

`--merge`는 `-i`를 두 번 이상 주면 자동으로 켜집니다. 결합 결과는 콘솔에 스트림별
결합/미결합 행 수와 매칭률로 출력되고, 번들의 `alignment` 블록과 Excel
`Alignment` 시트에 같은 값이 남습니다.

### CLI — 야간 웨어러블 + 아침 커프 (v0.3)

```bash
# 오우라 야간 집계(03:00)와 아침 커프(07:10)를 직전 14시간 창으로 결합
python -m heartmetric_core \
  -i examples/streams/morning_cuff.csv \
  -i examples/streams/night_wearable.csv \
  -i examples/streams/morning_environment.csv \
  --align-mode overnight_morning -o overnight.md

# 아침 창·되돌아보기 시간 바꾸기 (05–12시, 14시간이 기본)
python -m heartmetric_core -i cuff.csv -i oura.json \
  --align-mode overnight_morning --morning-window 6-10 --overnight-lookback-hours 12 -o night.md
```

### CLI — 내 파일 하나

```bash
python -m heartmetric_core -i my_export.csv --condition forest -o forest.xlsx
python -m heartmetric_core -i export.xml -o apple_health.xlsx     # Apple Health export.xml
python -m heartmetric_core -i oura_sleep.json -o oura.xlsx        # Oura API v2 응답
```

### Python — 결합 + 대응표본 + 상관

```python
from heartmetric_core import align_streams, analyze, exporter

aligned = align_streams([
    "cuff_bp.csv",        # SBP/DBP
    "wearable.json",      # HR, RMSSD/SDNN
    "environment.csv",    # PM2.5, 기온, 녹지
], tolerance_minutes=30)  # mode="daily" 로 일별 집계 결합

print(aligned.report.to_dict())      # 스트림별 matched / unmatched / 매칭률

bundle = analyze(aligned.frame, paired=True)   # subject_id가 있으면 자동 대응표본
print(bundle["comparison"][0])       # d_z · permutation_p · sign_test_p · 95% CI
print(bundle["correlations"][0])     # pearson_r · spearman_rho · slope · slope_p

exporter.save(bundle, "report.xlsx")
exporter.to_markdown(bundle, "report.md")
```

### Python — 통계 함수 직접 호출

```python
from heartmetric_core import stats

a, b, subjects = stats.subject_pairs(frame, "sbp", subject_column="subject_id")
stats.paired_subject_compare(frame, "rmssd")      # 대응 t + d_z + 순열 p + 부호검정
stats.correlation_profile(frame, "pm25", "sbp")   # r, ρ, 기울기, p, R²
stats.linear_regression(x, y)                     # 기울기 95% CI 포함
```

### API

```bash
uvicorn api.server:app --reload
curl -s localhost:8000/api/sample | head -c 400
curl -X POST localhost:8000/api/analyze -H 'content-type: application/json' \
     -d '{"demo": true}' | python -m json.tool | head -40
curl -X POST "localhost:8000/api/export?fmt=md" -F file=@my_export.csv -o report.md
```

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 상태·버전 |
| GET | `/api/sample?days=14&seed=5020` | 합성 데모 레코드 |
| GET | `/api/methodology` | 지표별 수식·단위·근거·경계(v0.3) |
| POST | `/api/analyze` | JSON records / multipart 파일 → 분석 번들 |
| POST | `/api/export?fmt=xlsx\|csv\|json\|md` | 같은 입력 → 파일 다운로드 |

## 4. 표준 테이블

로더가 모든 출처를 아래 열로 정리합니다(긴 형식, long format).

| 열 | 의미 | 단위 |
| --- | --- | --- |
| `timestamp` | 측정 시각(로컬 시간대로 통일) | ISO 8601 |
| `subject_id` | 피험자 식별자(v0.2) — `피험자`·`participant`·`subject` 헤더 인식 | — |
| `source` | `apple_health` · `oura` · `synthetic` · 사용자 지정 | — |
| `condition` | `urban` · `forest` · `rest` 등(한글 라벨 자동 변환) | — |
| `sbp`, `dbp` | 수축기/이완기 혈압 | mmHg |
| `hr` | 심박수 | bpm |
| `rmssd`, `sdnn` | HRV | ms |
| `temp_c`, `humidity_pct` | 기온·습도 | °C, % |
| `pm25`, `pm10` | 미세먼지 | µg/m³ |
| `green_index` | 녹지지수(0–1, 0–100 스케일은 자동 변환) | — |
| `forest` | 산림 여부(0/1) | — |
| `activity`, `steps` | 활동 라벨(텍스트)·걸음 수 | — |
| `flags` | QC 플래그 + 정렬 플래그(`align:bp+wearable`, `align_unmatched` …) | — |

`수축기`·`이완기`·`심박수`·`측정일시`·`피험자` 같은 한글 헤더, `systolic`/`pulse`
같은 영문 헤더, HealthKit의 긴 형식(`type,value,startDate`)과 Oura API v2 JSON을
모두 자동 매핑합니다. kPa·화씨·초 단위 HRV처럼 단위가 다른 값은 **경고를 남기고**
변환합니다(조용히 바꾸지 않습니다).

## 5. 다중 스트림 시간 정렬 (`heartmetric_core/align.py`)

세 파일은 서로 다른 기기·시계에서 기록되므로 같은 초에 만나는 일이 거의 없습니다.
`align_streams()`는 **시간 근접성**으로 결합합니다.

```python
align_streams(streams, tolerance_minutes=30, mode="tolerance", anchor=None,
              subject_column="subject_id",
              overnight_lookback_hours=14, morning_window=(5, 12))
```

| 규칙 | 동작 |
| --- | --- |
| 결합 기준 | `|Δt| ≤ tolerance_minutes` 이고 `subject_id`가 같은 행. 허용 오차 0이면 동일 시각만 |
| 앵커 | `bp` 스트림 행이 출력 행이 됨(없으면 첫 스트림). 다른 스트림은 가장 가까운 앵커에 1:1로만 붙음 |
| 값 충돌 | 앵커에 이미 값이 있으면 덮어쓰지 않고 **버림** + `align_conflict` 플래그 |
| 미결합 | 버리지 않고 별도 행으로 유지 + `align_unmatched` 플래그 |
| 피험자 | 양쪽에 `subject_id`가 있으면 반드시 일치. 한쪽에만 없으면 표 전체가 단일 피험자일 때만 결합(경고 기록), 여러 피험자면 결합 거부 |
| 일별 모드 | `mode="daily"` — 피험자·날짜별 평균으로 집계한 뒤 날짜로 결합 |
| 야간 모드 | `mode="overnight_morning"` — 05:00–12:00 커프를 앵커로, **직전** 14시간(`overnight_lookback_hours`) 안의 행만 역할별 1개씩 결합. 커프 뒤에 찍힌 값은 붙이지 않으며, 매치마다 `lag_minutes`, 못 붙였으면 사유(`outside_lookback_window` · `only_after_anchor` · `no_row_for_this_subject` · `already_matched_to_another_anchor`)를 남김 |
| 보고 | 스트림별 `rows` / `matched_rows` / `unmatched_rows` / `match_rate_pct` / `by_date`, 앵커 매칭률, (야간 모드) `lag_minutes`·`matches`·`unmatched_reasons` |

**값은 절대 이동·보간·복사되지 않습니다.** 정렬은 열들을 시간축에서 나란히 놓을
뿐이고, 결측은 결측으로 남습니다.

### 스트림 타임라인 갭 맵 (v0.3)

```python
gap = align_streams(streams, mode="overnight_morning")
gap_map = build_timeline_gap_map(streams, gap.report)
gap_map["summary"]["per_stream"]["oura_night.json"]["longest_gap_days"]
```

전체 관측의 첫날부터 마지막 날까지 **일자×스트림 격자**를 만들고 각 칸을
`matched`(모든 행 결합) · `partial`(일부 결합) · `unmatched`(행은 있으나 미결합) ·
`missing`(그날 관측 없음)으로 표시합니다. 스트림별 결측일·최장 연속 결측·결합률,
관측 커버리지가 함께 나오고 JSON 번들의 `timeline_gap_map`·Excel `GapMap` 시트·
워크벤치 패널이 같은 값을 씁니다. **구멍은 구멍으로 보고하고 메우지 않습니다.**

## 6. 지표 정의

| 지표 | 식 | 구분 | 비고 |
| --- | --- | --- | --- |
| 맥압 PP | `SBP − DBP` | derived | 100 mmHg 초과는 플래그(삭제 아님) |
| 평균동맥압 MAP | `DBP + (SBP − DBP)/3` | derived | |
| 야간 하강률 | `(주간평균 − 야간평균) / 주간평균 × 100` | derived | 야간 22:00–06:00, 기본 2회 이상 |
| 하강 분류 | 정상 10–20 % · non-dipper 0–10 % · reverse < 0 % · extreme > 20 % | derived | ABPM 관례 |
| HRV 회복 지수 | `야간 RMSSD / 주간 RMSSD × 100` | derived | 야간 측정 없으면 '그날 첫 측정' 기저(응답에 명시) |
| BP 부하 | `SBP ≥ 130 또는 DBP ≥ 80` 비율 | derived | 진단이 아닌 부하 지표 |
| 환경 부하 `env_load` | `mean( clamp(PM2.5/35) · clamp(|기온−22|/15) · (1−녹지) )` | exploratory | **혈압·HRV 미포함** — 상관분석의 순환논리 회피 |
| 환경 스트레스 지수 | `0.30·BP부하 + 0.25·HRV억제 + 0.20·PM2.5 + 0.15·열부담 + 0.10·HR부하` | exploratory | 0–100, 연구용 합성 지표 |

지표마다 **수식·단위·참고문헌·경계**가 `provenance.METHODOLOGY`에 구조화되어 있고,
번들의 `methodology` 블록 · Excel `Methodology` 시트 · Markdown 리포트 6장 ·
워크벤치 "지표 정의" 패널에 같은 내용이 나옵니다. 기준값은
`metrics.REFERENCE`(RMSSD 50 ms · PM2.5 35 µg/m³(WHO 2005 24h interim target 1) ·
22 °C …)에 상수로 노출되어 있습니다.

## 7. 통계

### 독립표본
- **Welch t-test**(등분산 가정 없음) + 평균차 95 % 신뢰구간
- **Mann–Whitney U**(동점 보정 정규근사)
- **Cohen's d / Hedges' g**

### 대응표본 (v0.2)
- **`subject_id` 대응**: 피험자마다 조건별 평균을 하나씩 만들어(반복 측정을 한 값으로
  요약) 대응 검정. 양쪽 조건에 모두 있는 피험자만 사용하며 인원수를 보고합니다.
- **Paired t-test** + 평균차 95 % CI, **Cohen's d_z** = mean(d)/SD(d) (Lakens 2013)
- **Sign-flip 순열 p** (5,000회, seed 5020) — 분포 가정 없음
- **정확 부호검정 p** (이항분포)
- **Wilcoxon signed-rank** (정규근사, 동점 보정)
- `subject_id`가 없으면 `--paired`는 **시간 순서 짝짓기**로 대체하고, 번들
  `meta.comparison.paired_by = "row"` 및 note로 그 사실을 알립니다(조용히 넘어가지 않음).

### 환경 노출 × 심혈관 상관 (v0.2)
- **Pearson r** + p, **Spearman ρ** + p, **단순 선형회귀** 기울기·절편·기울기 p·기울기 95 % CI·R²
- 기본 쌍: PM2.5×SBP/DBP/MAP/RMSSD/SDNN, 녹지×SBP/RMSSD, 기온×HR/SBP, 습도×HR, `env_load`×SBP/RMSSD
- 경고: 상관은 인과가 아니며, 자기상관이 있는 시계열은 실효 표본이 줄어 p가 실제보다 작아집니다.

### 다중 비교 보정 (v0.3)
- 비교표에 오르는 지표(SBP·DBP·MAP·PP·HR·RMSSD·SDNN·`env_load`)는 **한 가족**으로 취급합니다.
- `benjamini_hochberg(p)` — BH-FDR q-값(`q_value_bh`), 오름차순 p에 `q_(i) = min_{j≥i} m·p_(j)/j`, 단조·0–1 절단
- `holm_bonferroni(p)` — Holm 보정 p(`p_holm`), `p_holm_(i) = max_{j≤i} min(1, (m−j+1)·p_(j))`
- 원 p 옆에 둘을 함께 보고하고 `significant_fdr_05` 플래그와 가족 크기 `m`을 번들·Markdown·Excel에 남깁니다. 입력 순서를 보존하고, 계산할 수 없는 지표(NaN)는 가족 크기에서 제외합니다.
- 두 방법이 다른 결론을 내면 **둘 다** 보고합니다(유리한 쪽만 고르지 않음).

t 분포와 정규화 불완전 베타 함수는 직접 구현했고, SciPy가 있으면 테스트에서
`ttest_ind` · `ttest_rel` · `mannwhitneyu` · `wilcoxon` · `pearsonr` · `spearmanr` ·
`linregress` · `false_discovery_control`과, statsmodels가 있으면 `multipletests(holm)`과
값이 일치하는지 대조합니다.

## 8. 데이터 품질(QC)

`cleaner.clean()`은 다음을 보고합니다.

- 생리적 범위 밖 값(SBP 60–260, DBP 30–160, HR 25–220 …) → 제거 + 사유 기록
- `SBP ≤ DBP` 모순 쌍 → 제거
- 정확 중복·60초 이내 동일 재동기화 → 1건으로 축약(피험자 단위로 구분)
- 결측률, 조건별 행 수, 관측 기간, 12시간 이상 공백(gap — 야간 공백은 기본적으로 제외)
- 단위 불일치, RMSSD > SDNN 같은 경고

삭제는 언제나 **개수와 사유**로 남습니다. 조용히 사라지는 값은 없습니다.

## 9. 내보내기

- **Excel(.xlsx)** — `README` 시트 + 데이터 11개 시트(`Summary` · `Quality` ·
  `Alignment` · `GapMap` · `Conditions` · `Exposure` · `Comparison` · `Daily` ·
  `Correlations` · `Methodology` · `Readings`)
- **Markdown(.md)** — 7장 리포트: 데이터·품질 / 요약 지표 / 조건별 비교(BH·Holm 열) /
  환경 상관 / **스트림 타임라인 갭 맵** / 조건별 평균 / 지표 정의와 경계. 표와 근거
  구분(measured·derived·exploratory)을 그대로 담습니다.
- **CSV** — 표준 테이블(UTF-8 BOM, Excel에서 한글 바로 열림) 또는 시트별 폴더
- **JSON** — `schema_version: "0.3.0"` 번들: 파라미터, 표본 수, 경고, 정렬 보고,
  **`timeline_gap_map`**, **다중 비교(BH q · Holm p · 가족 크기)**, 통계 결과, 지표 정의
  전체. 재현에 필요한 것이 모두 들어 있습니다.

## 10. 웹 워크벤치

`https://sunbear5020.github.io/heartmetric/` — 설치 없이 브라우저에서 실행됩니다.

- **다중 파일 결합 업로드**: 혈압 CSV + Oura JSON + 환경 CSV를 한 번에 올리고
  허용 오차(0 / 15 / 30 / 60 / 120분), 일별 집계, 또는 **야간(Oura) → 아침 커프**
  프리셋을 고른 뒤 결합. 스트림별 결합/미결합 행 수와 매칭률, 프리셋의 lag 중앙값·
  미결합 사유를 화면에 표시합니다.
- **스트림 타임라인 갭 맵**: 일자×스트림 격자에 매칭/부분/미결합/결측을 색으로 구분하고
  칸마다 툴팁(행 수·결합 행·과목·상태)을 붙입니다.
- **비교 모드 전환**: 독립표본(Welch) ↔ `subject_id` 대응표본(대응 t + d_z + 순열 p),
  비교표에 **BH-FDR q 열**과 Holm 보정 p를 함께 표시
- **환경 산점도**: PM2.5·녹지·기온·습도·환경부하 × SBP/DBP/HR/RMSSD/SDNN, 회귀선과
  r · ρ · 기울기 p 표시
- **지표 정의 패널**: 실측 / 파생 / 탐색 구분과 수식·경계
- **내보내기**: 정리된 CSV · JSON 번들(schema 0.3.0) · Markdown 리포트
- 100% 브라우저 로컬 실행. 파일은 페이지를 떠나지 않습니다.
- 엔진과 같은 정의를 JavaScript로 옮겨 두어 같은 파일·같은 허용 오차에서 같은 수치가 나옵니다.

워크벤치 원본은 **이 저장소의 `web/` 폴더**에 함께 들어 있습니다
(`web/index.html` · `web/styles.css` · `web/app.js` — 라이브 사이트와 같은 파일).

- **라이브**: <https://sunbear5020.github.io/heartmetric/>
- **로컬 실행** (설치 없이 내 컴퓨터에서 띄우기):

```bash
cd web
python3 -m http.server 8000
# 브라우저에서 http://localhost:8000 접속 (파일은 서버로 전송되지 않습니다)
```

이 저장소의 `web/`을 GitHub Pages로 공개하려면 Settings → Pages → Source를
`Deploy from a branch`, 브랜치 `main`, 폴더 `/web`으로 지정하면 됩니다.

## 11. 한계와 윤리

- 커프 혈압은 간헐 측정입니다. 야간 하강률은 ABPM 수준의 연속 측정이 아니면
  잡음이 큽니다. 표본 수(`n_day`, `n_night`)를 항상 함께 보고하십시오.
- Oura 야간 집계는 03:00으로 배치됩니다 — 실제 수면 구간의 평균이라는 점을
  기억해야 합니다. 그래서 야간 집계와 아침 커프 값을 결합할 때는 `overnight_morning`
  프리셋(아침 앵커 + 직전 14시간)이 맞고, 결합된 값의 `lag_minutes`를 함께 읽으십시오.
- 환경 변수는 개인 노출이 아니라 측정 지점의 대표값입니다. 실내·실외 이동을
  구분하지 않습니다.
- 상관분석은 공변량(활동량·수면·계절·개인차)을 보정하지 않습니다. 비교표의 p는
  BH-FDR·Holm 보정치를 함께 보고하지만, 상관표와 다른 분석 가족의 p는 보정하지
  않습니다. 지표를 더 넣으면 가족 크기가 바뀌므로 q도 바뀝니다.
- 이 소프트웨어는 의료기기가 아니며 진단·치료를 대체하지 않습니다.
- 건강 데이터는 민감정보입니다. 연구 이용 시 IRB 승인과 가명처리 계획이 먼저입니다.

## 12. 라이선스 · 인용

MIT License · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University

```
FEI · HEL Lab, Gyeongsang National University. (2026).
HEARTMETRIC: Environmental Cardiovascular Response Platform (v0.3.0) [Software].
https://github.com/sunbear5020/heartmetric
```

문의: 김건우 교수 · bkim5020@gnu.ac.kr · 경상국립대학교 농대2호관 452동 237호

## 13. CI (GitHub Actions)

세 파이썬 버전(3.10·3.11·3.12)에서 pytest와 CLI 스모크 테스트를 돌리는 워크플로를
`.github/ci-workflow.yml.template`로 두었습니다. 이 환경의 GitHub 연결 권한이
`.github/workflows/` 경로 쓰기를 허용하지 않아 템플릿으로 보관합니다.
GitHub 웹에서 이 파일을 `.github/workflows/ci.yml`로 옮기면(내용 그대로)
Actions가 다음 푸시부터 자동으로 돕니다. 로컬에서는 `python -m pytest`가 같은
검사입니다(124 tests).
