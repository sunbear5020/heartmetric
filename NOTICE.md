# NOTICE

HEARTMETRIC — Environmental Cardiovascular Response Platform
Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University

This project is released under the MIT License (see `LICENSE`). This NOTICE
records what the software does and does not claim, so that a reader — or a
reviewer — can check the boundary before using a number it produces.

## 1. Hardware and API boundary

HEARTMETRIC does **not** obtain blood pressure from a ring or a watch.

| Stream | Source in HEARTMETRIC | What it contains |
| --- | --- | --- |
| Blood pressure (SBP/DBP) | Cuff reading exported from Apple Health (CSV/XML), or any CSV/JSON with a cuff column | mmHg, intermittent |
| Heart rate | Oura / Apple Watch export (CSV/JSON), Apple Health XML | bpm, per record or nightly aggregate |
| HRV | Oura `average_hrv` (rMSSD, ms), Apple Health `HeartRateVariabilitySDNN` | ms |
| Environmental exposure | 기상청 / AirKorea / 산림청 or a study's own logger, joined by time | °C, %, µg/m³, 0–1 greenness, forest flag |

- **Oura API v2 publishes no blood-pressure endpoint.** The Oura app can show a
  nighttime BP trend derived from PPG, but it does not expose mmHg readings to
  third-party software. HEARTMETRIC therefore treats a cuff measurement as the
  only source of SBP/DBP, and uses the ring for HR/HRV/sleep timing.
- Apple Health writes HRV as **SDNN** (`HeartRateVariabilitySDNN`). RMSSD is
  what Oura reports. The two are not interchangeable; HEARTMETRIC labels which
  one is present instead of converting between them.
- Nightly Oura aggregates are placed at 03:00 local time of their `day`. No
  per-beat data is reconstructed.

## 2. No affiliation

HEARTMETRIC is an independent research project. It is **not affiliated with,
endorsed by, or sponsored by Oura Health Oy, Apple Inc., or any cuff
manufacturer**. Product names are used only to describe file formats.

## 3. Synthetic demonstration data

`heartmetric_core.synthetic` generates every demonstration value with
`numpy.random.default_rng(seed)`. No vendor sample file, no real participant,
no scraped measurement is used anywhere in this repository. The generator
embeds assumed effect sizes (a forest walk lowers SBP by a few mmHg in the
simulation); those assumptions are illustrative and are **not** findings.

## 4. Not a medical device

HEARTMETRIC is a research and self-tracking tool. It does not diagnose,
treat, cure or prevent any disease, and no index it computes (nocturnal
dipping category, HRV recovery index, environmental stress index) is a clinical
threshold. A validated cuff measurement and a clinician remain the reference.

## 5. Privacy

The in-browser workbench parses and analyses files locally: nothing is
uploaded, there is no analytics script, and no file leaves the page. The
optional FastAPI server processes data in the memory of the machine you run it
on and stores nothing. Health data is special-category personal data under
GDPR Art. 9 and Korean 개인정보 보호법; a study that collects it needs IRB
approval and a de-identification plan before HEARTMETRIC is pointed at it.

## 6. Citation

    FEI · HEL Lab, Gyeongsang National University. (2026).
    HEARTMETRIC: Environmental Cardiovascular Response Platform (v0.1.0) [Software].
    https://github.com/sunbear5020/heartmetric

Contact: bkim5020@gnu.ac.kr
