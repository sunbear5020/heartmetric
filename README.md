# HEARTMETRIC Core (v0.1.0)

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
environmental stress index: 38.1 (moderate)
    sbp: 126.97 vs 130.58 (Δ -3.61, d=-0.51, p=0.0410)
  rmssd: 46.49 vs 40.71 (Δ 5.78, d=1.12, p<0.0001)
```

### CLI — 내 파일

```bash
python -m heartmetric_core -i my_export.csv --condition forest -o forest.xlsx
python -m heartmetric_core -i export.xml -o apple_health.xlsx     # Apple Health export.xml
python -m heartmetric_core -i oura_sleep.json -o oura.xlsx        # Oura API v2 응답
```

### Python

```python
from heartmetric_core import load_file, analyze, exporter

loaded = load_file("apple_health_export.xml")
bundle = analyze(loaded.frame, group_a="forest", group_b="urban")
print(bundle["summary"]["sbp"], bundle["summary"]["dipping"])
exporter.save(bundle, "report.xlsx")
```

### API

```bash
uvicorn api.server:app --reload
curl -s localhost:8000/api/sample | head -c 400
curl -X POST localhost:8000/api/analyze -H 'content-type: application/json' \
     -d '{"demo": true}' | python -m json.tool | head -40
curl -X POST "localhost:8000/api/export?fmt=xlsx" -F file=@my_export.csv -o report.xlsx
```

| Method | Path | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 상태·버전 |
| GET | `/api/sample?days=14&seed=5020` | 합성 데모 레코드 |
| POST | `/api/analyze` | JSON records / multipart 파일 → 분석 번들 |
| POST | `/api/export?fmt=xlsx\|csv\|json` | 같은 입력 → 파일 다운로드 |

## 4. 표준 테이블

로더가 모든 출처를 아래 열로 정리합니다(긴 형식, long format).

| 열 | 의미 | 단위 |
| --- | --- | --- |
| `timestamp` | 측정 시각(로컬 시간대로 통일) | ISO 8601 |
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
| `flags` | QC 플래그(`sbp_range`, `sbp_le_dbp`, `wide_pulse_pressure` …) | — |

`수축기`·`이완기`·`심박수`·`측정일시` 같은 한글 헤더, `systolic`/`pulse` 같은 영문
헤더, HealthKit의 긴 형식(`type,value,startDate`)과 Oura API v2 JSON을 모두
자동 매핑합니다. kPa·화씨·초 단위 HRV처럼 단위가 다른 값은 **경고를 남기고**
변환합니다(조용히 바꾸지 않습니다).

## 5. 지표 정의

| 지표 | 식 | 비고 |
| --- | --- | --- |
| 맥압 PP | `SBP − DBP` | 100 mmHg 초과는 플래그(삭제 아님) |
| 평균동맥압 MAP | `DBP + (SBP − DBP)/3` | |
| 야간 하강률 | `(주간평균 − 야간평균) / 주간평균 × 100` | 야간 22:00–06:00, 기본 2회 이상 |
| 하강 분류 | 정상 10–20 % · non-dipper 0–10 % · reverse < 0 % · extreme > 20 % | ABPM 관례 |
| HRV 회복 지수 | `야간 RMSSD / 주간 RMSSD × 100` | 야간 측정이 없으면 '그날 첫 측정'을 기저로 사용(응답에 명시) |
| BP 부하 | `SBP ≥ 130 또는 DBP ≥ 80` 비율 | 진단이 아닌 부하 지표 |
| 환경 스트레스 지수 | `0.30·BP부하 + 0.25·HRV억제 + 0.20·PM2.5 + 0.15·열부담 + 0.10·HR부하` | 0–100, 연구용 합성 지표 |
| 효과크기 | Cohen's d(합동 SD), Hedges' g(소표본 보정) | 0.2/0.5/0.8 = small/medium/large |

환경 스트레스 지수의 기준값은 모두 코드에 상수로 노출되어 있습니다
(`metrics.REFERENCE`: RMSSD 50 ms · PM2.5 35 µg/m³ · 22 °C …). 다른 기준을 쓰려면
`environmental_stress_index(frame, weights=...)`로 가중치를 바꿀 수 있습니다.

## 6. 통계

- **Welch t-test**(등분산 가정 없음) + 평균차 95 % 신뢰구간
- **Paired t-test**(같은 참가자의 두 조건, `--paired`)
- **Mann–Whitney U**(동점 보정 정규근사) — 분포 가정이 어려울 때
- **Cohen's d / Hedges' g**
- t 분포는 정규화 불완전 베타 함수로 직접 구현했고, SciPy가 설치되어 있으면
  테스트에서 값이 일치하는지 대조합니다(`tests/test_stats.py`).

## 7. 데이터 품질(QC)

`cleaner.clean()`은 다음을 보고합니다.

- 생리적 범위 밖 값(SBP 60–260, DBP 30–160, HR 25–220 …) → 제거 + 사유 기록
- `SBP ≤ DBP` 모순 쌍 → 제거
- 정확 중복·60초 이내 동일 재동기화 → 1건으로 축약
- 결측률, 조건별 행 수, 관측 기간, 12시간 이상 공백(gap — 야간 공백은 기본적으로 제외)
- 단위 불일치, RMSSD > SDNN 같은 경고

삭제는 언제나 **개수와 사유**로 남습니다. 조용히 사라지는 값은 없습니다.

## 8. 내보내기

- **Excel(.xlsx)** — `README` 시트 + 데이터 8개 시트(`Summary` · `Quality` · `Conditions` ·
  `Exposure` · `Comparison` · `Daily` · `Correlations` · `Readings`)
- **CSV** — 표준 테이블(UTF-8 BOM, Excel에서 한글 바로 열림) 또는 시트별 폴더
- **JSON** — 분석 번들 전체(재현 가능한 메타데이터 포함)

## 9. 웹 워크벤치

`https://sunbear5020.github.io/heartmetric/` — 설치 없이 브라우저에서 실행됩니다.
CSV/JSON 업로드, 합성 데모 원클릭, 요약 카드, 조건 비교표, SBP/DBP·HRV 시계열과
환경 상관 차트, CSV/JSON 다운로드. 파일은 페이지를 떠나지 않습니다.
엔진과 같은 정의를 JavaScript로 옮겨 두어 같은 파일에서 같은 수치가 나옵니다.

워크벤치 원본은 **이 저장소의 `web/` 폴더**에 함께 들어 있습니다
(`web/index.html` · `web/styles.css` · `web/app.js` — 라이브 사이트와 같은 파일).

- **라이브**: <https://sunbear5020.github.io/heartmetric/>
- **로컬 실행** (설치 없이 내 컴퓨터에서 띄우기): 아래 두 줄

```bash
cd web
python3 -m http.server 8000
# 브라우저에서 http://localhost:8000 접속 (파일은 서버로 전송되지 않습니다)
```

이 저장소의 `web/`을 GitHub Pages로 공개하려면 Settings → Pages → Source를
`Deploy from a branch`, 브랜치 `main`, 폴더 `/web`으로 지정하면 됩니다.

## 10. 한계와 윤리

- 커프 혈압은 간헐 측정입니다. 야간 하강률은 ABPM 수준의 연속 측정이 아니면
  잡음이 큽니다. 표본 수(`n_day`, `n_night`)를 항상 함께 보고하십시오.
- Oura 야간 집계는 03:00으로 배치됩니다 — 실제 수면 구간의 평균이라는 점을
  기억해야 합니다.
- 환경 변수는 개인 노출이 아니라 측정 지점의 대표값입니다. 실내·실외 이동을
  구분하지 않습니다.
- 이 소프트웨어는 의료기기가 아니며 진단·치료를 대체하지 않습니다.
- 건강 데이터는 민감정보입니다. 연구 이용 시 IRB 승인과 가명처리 계획이 먼저입니다.

## 11. 라이선스 · 인용

MIT License · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University

```
FEI · HEL Lab, Gyeongsang National University. (2026).
HEARTMETRIC: Environmental Cardiovascular Response Platform (v0.1.0) [Software].
https://github.com/sunbear5020/heartmetric
```

문의: 김건우 교수 · bkim5020@gnu.ac.kr · 경상국립대학교 농대2호관 452동 237호

## 12. CI (GitHub Actions)

세 파이썬 버전(3.10·3.11·3.12)에서 pytest와 CLI 스모크 테스트를 돌리는 워크플로를
`.github/ci-workflow.yml.template`로 두었습니다. 이 환경의 GitHub 연결 권한이
`.github/workflows/` 경로 쓰기를 허용하지 않아 템플릿으로 보관합니다.
GitHub 웹에서 이 파일을 `.github/workflows/ci.yml`로 옮기면(내용 그대로)
Actions가 다음 푸시부터 자동으로 돕니다. 로컬에서는 `python -m pytest`가 같은
검사입니다.
