"""HEARTMETRIC standard table schema.

Every vendor export (Apple Health cuff BP, Oura sleep/HRV, generic CSV/JSON,
environmental exposure logs) is mapped onto one long-format table so that the
cleaner, metrics and statistics always see the same column names.

Design note — the hardware/API boundary
---------------------------------------
Oura Ring does not expose mmHg blood pressure: neither the ring display nor the
Oura API v2 provides a blood-pressure endpoint (only nighttime PPG trends and a
"nighttime BP" estimate inside the app). HEARTMETRIC therefore keeps two
streams separate and joins them by time:

  * ``sbp`` / ``dbp``  — cuff blood pressure, e.g. an Apple Health export
  * ``hr`` / ``rmssd`` / ``sdnn`` — wearable heart rate and HRV
  * ``temp_c`` / ``pm25`` / ``green_index`` / ``forest`` — environmental exposure

No value in any stream is inferred from another here; joining is by timestamp.
"""

from __future__ import annotations

import re
from typing import Dict, List

# --------------------------------------------------------------------- columns

TIMESTAMP = "timestamp"
SUBJECT = "subject_id"
SOURCE = "source"
CONDITION = "condition"
FLAGS = "flags"
NOTES = "notes"

#: Numeric measurement columns. ``activity`` is a text label ("walk", "night",
#: "휴식") and is kept out of the numeric table so it is never counted as a
#: missing measurement.
METRIC_COLUMNS: List[str] = [
    "sbp",
    "dbp",
    "hr",
    "rmssd",
    "sdnn",
    "temp_c",
    "humidity_pct",
    "pm25",
    "pm10",
    "green_index",
    "forest",
    "steps",
]

ACTIVITY = "activity"

STANDARD_COLUMNS: List[str] = [
    TIMESTAMP,
    SUBJECT,
    SOURCE,
    CONDITION,
    *METRIC_COLUMNS,
    ACTIVITY,
    FLAGS,
    NOTES,
]

#: Columns that must be numeric after loading.
NUMERIC_COLUMNS: List[str] = [*METRIC_COLUMNS]

#: Columns without which a row cannot be placed in time.
REQUIRED_COLUMNS: List[str] = [TIMESTAMP]

# ---------------------------------------------------------------------- aliases
# Keys are already in normalized form (lowercase, alphanumerics + Hangul only).
ALIASES: Dict[str, List[str]] = {
    TIMESTAMP: [
        "timestamp", "datetime", "date time", "date", "time", "start", "startdate",
        "start date", "starttime", "enddate", "recordedat", "recorded at", "measuredat",
        "measurement time", "day", "summarydate", "bedtime start", "bedtime_start",
        "측정일", "측정시각", "일시", "날짜", "시간", "측정일시",
    ],
    SUBJECT: [
        "subject id", "subject", "subjectid", "participant", "participant id", "participantid",
        "participant code", "person id", "person", "record id", "user id", "userid",
        "피험자", "피험자id", "피험자번호", "대상자", "대상자id", "참가자", "참가자id", "연구대상",
    ],
    SOURCE: ["source", "device", "app", "vendor", "출처", "기기"],
    CONDITION: [
        "condition", "group", "phase", "condition name", "segment", "protocol",
        "intervention", "activity type", "환경", "조건", "구간", "그룹",
    ],
    "sbp": [
        "sbp", "systolic", "systolic bp", "systolic blood pressure", "systolicpressure",
        "systolic mmhg", "bpx systole", "highest blood pressure",
        "수축기", "수축기혈압", "최고혈압", "수축기 압",
    ],
    "dbp": [
        "dbp", "diastolic", "diastolic bp", "diastolic blood pressure",
        "diastolicpressure", "diastolic mmhg", "bpx diastole", "lowest blood pressure",
        "이완기", "이완기혈압", "최저혈압", "이완기 압",
    ],
    "hr": [
        "hr", "heart rate", "heartrate", "pulse", "pulse rate", "bpm", "pulse bpm",
        "average heart rate", "averageheartrate", "mean heart rate", "resting heart rate",
        "restingheartrate", "lowest heart rate",
        "심박수", "맥박", "심박", "평균심박수",
    ],
    "rmssd": [
        "rmssd", "rmssd ms", "rmssdms", "hrv", "hrv ms", "hrvms", "average hrv",
        "averagehrv", "hrv rmssd", "hrv balance ms",
        "알엠에스에스디", "심박변이도", "에이치알브이",
    ],
    "sdnn": ["sdnn", "sdnn ms", "sdnnms", "hrv sdnn", "심박변이도sdnn"],
    "temp_c": [
        "temp", "temperature", "temp c", "tempc", "air temp", "airtemperature",
        "ambient temperature", "기온", "온도", "기온c",
    ],
    "humidity_pct": ["humidity", "rh", "relative humidity", "humidity pct", "습도"],
    "pm25": ["pm25", "pm2 5", "pm2.5", "pm 2.5", "pm25 ugm3", "fine dust", "초미세먼지", "pm25농도"],
    "pm10": ["pm10", "pm 10", "pm10 ugm3", "미세먼지"],
    "green_index": [
        "green index", "greenindex", "ndvi", "greenness", "green ratio", "녹지지수", "녹지율",
    ],
    "forest": [
        "forest", "forest flag", "is forest", "forestflag", "canopy", "canopy cover",
        "산림", "숲", "산림여부",
    ],
    "activity": ["activity", "activity type", "posture", "state", "활동", "활동유형", "자세"],
    "steps": ["steps", "step count", "stepcount", "걸음수", "걸음"],
    FLAGS: ["flags", "qc", "quality", "note", "notes", "메모", "비고"],
}

#: HealthKit / long-format exports carry the metric name in a column of its own.
METRIC_NAME_ALIASES: List[str] = [
    "type", "metric", "metric name", "quantity type", "quantitytype", "hk type",
    "hktype", "variable", "field", "item", "측정항목", "항목", "지표",
]
VALUE_ALIASES: List[str] = ["value", "val", "measurement", "reading", "값", "측정값", "수치"]

#: Values inside a metric-name column that identify a standard column.
METRIC_NAME_MAP: Dict[str, str] = {
    "systolic": "sbp",
    "systolicbloodpressure": "sbp",
    "sbp": "sbp",
    "hkquantitytypeidentifierbloodpressuresystolic": "sbp",
    "diastolic": "dbp",
    "diastolicbloodpressure": "dbp",
    "dbp": "dbp",
    "hkquantitytypeidentifierbloodpressurediastolic": "dbp",
    "heartrate": "hr",
    "hr": "hr",
    "pulse": "hr",
    "hkquantitytypeidentifierheartrate": "hr",
    "restingheartrate": "hr",
    "hkquantitytypeidentifierrestingheartrate": "hr",
    "heartratevariabilityrmssd": "rmssd",
    "rmssd": "rmssd",
    "hkquantitytypeidentifierheartratevariabilityrmssd": "rmssd",
    "heartratevariabilitysdnn": "sdnn",
    "sdnn": "sdnn",
    "hkquantitytypeidentifierheartratevariabilitysdnn": "sdnn",
    "stepcount": "steps",
    "steps": "steps",
    "hkquantitytypeidentifierstepcount": "steps",
}

#: Condition labels in Korean/other spellings that map onto canonical codes.
CONDITION_VALUES: Dict[str, str] = {
    "urban": "urban",
    "city": "urban",
    "street": "urban",
    "도시": "urban",
    "도심": "urban",
    "가로": "urban",
    "시가지": "urban",
    "forest": "forest",
    "forest healing": "forest",
    "healing forest": "forest",
    "숲": "forest",
    "산림": "forest",
    "산림치유": "forest",
    "치유의숲": "forest",
    "숲길": "forest",
    "rest": "rest",
    "resting": "rest",
    "baseline": "rest",
    "휴식": "rest",
    "안정": "rest",
    "기저": "rest",
    "indoor": "indoor",
    "실내": "indoor",
    "outdoor": "outdoor",
    "야외": "outdoor",
}


def normalize_key(name: object) -> str:
    """Normalize a column/vocabulary name for alias matching."""
    if name is None:
        return ""
    text = str(name).strip().lower()
    text = text.replace("°c", "c").replace("℃", "c")
    text = re.sub(r"[^0-9a-z가-힣]+", "", text)
    return text


#: normalized alias → canonical column, built once at import time.
_LOOKUP: Dict[str, str] = {}
for _canonical, _aliases in ALIASES.items():
    _LOOKUP.setdefault(normalize_key(_canonical), _canonical)
    for _alias in _aliases:
        _LOOKUP.setdefault(normalize_key(_alias), _canonical)


#: normalized condition label → canonical code.
_CONDITION_LOOKUP: Dict[str, str] = {
    normalize_key(alias): code for alias, code in CONDITION_VALUES.items()
}


def canonical_column(name: object) -> str | None:
    """Return the standard column an input header maps to, or ``None``."""
    key = normalize_key(name)
    return _LOOKUP.get(key) if key else None


def canonical_metric_name(value: object) -> str | None:
    key = normalize_key(value)
    return METRIC_NAME_MAP.get(key) if key else None


def _is_missing_value(value: object) -> bool:
    """Missing for a label column: None, NaN, pandas NA/NaT, and their text forms.

    pandas 3 stores object columns in a string dtype whose missing value is
    ``pd.NA``; ``str(pd.NA)`` is ``"<NA>"``, which must never become a subject id
    or a condition label.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "nan", "none", "null", "-", "<na>", "nat"}
    if isinstance(value, float):
        return value != value
    try:
        import pandas as pd

        result = pd.isna(value)
    except (ImportError, TypeError, ValueError):
        return False
    return bool(result) if isinstance(result, bool) else False


def normalize_subject(value: object) -> str | None:
    """Keep a subject identifier as a trimmed string (never a number)."""
    if _is_missing_value(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    return text


def normalize_condition(value: object) -> str | None:
    """Map a condition label onto a canonical code, keeping unknown labels."""
    if _is_missing_value(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    key = normalize_key(text)
    if key in _CONDITION_LOOKUP:
        return _CONDITION_LOOKUP[key]
    return text.lower().replace(" ", "_")


def empty_frame():
    """An empty standard table (used when an input has no usable rows)."""
    import pandas as pd

    frame = pd.DataFrame({c: pd.Series(dtype="object") for c in STANDARD_COLUMNS})
    return frame
