"""HEARTMETRIC Core — clean-room cardiovascular × environment analytics.

HEARTMETRIC joins three streams that are usually kept apart — cuff blood
pressure, wearable heart rate / HRV, and environmental exposure — onto one
standard table so that the same analysis can be reproduced from a notebook, an
API call or the in-browser workbench.

Hardware boundary: Oura Ring does not provide mmHg blood pressure through its
API (Oura API v2 has no blood-pressure endpoint), so HEARTMETRIC never pretends
to read BP from a ring. Cuff BP comes from an Apple Health export or any CSV;
the ring/watch contributes HR and HRV. HEARTMETRIC is an independent project
and is not affiliated with Oura Health Oy or Apple Inc.

License: MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University
"""

from __future__ import annotations

__version__ = "0.1.0"

from . import cleaner, exporter, loader, metrics, pipeline, stats, synthetic  # noqa: E402
from .cleaner import CleanReport, clean  # noqa: E402
from .exporter import save, to_csv, to_excel, to_json  # noqa: E402
from .loader import load_any, load_csv, load_file, load_json, merge  # noqa: E402
from .metrics import (  # noqa: E402
    environmental_stress_index,
    hrv_recovery,
    mean_arterial_pressure,
    nocturnal_dipping,
    pulse_pressure,
)
from .pipeline import analyze, analyze_file, analyze_loaded, demo_bundle  # noqa: E402
from .schema import STANDARD_COLUMNS  # noqa: E402
from .stats import cohens_d, compare, mann_whitney_u, welch_ttest  # noqa: E402
from .synthetic import generate  # noqa: E402

__all__ = [
    "__version__",
    "STANDARD_COLUMNS",
    "analyze",
    "analyze_file",
    "analyze_loaded",
    "demo_bundle",
    "clean",
    "CleanReport",
    "load_any",
    "load_csv",
    "load_file",
    "load_json",
    "merge",
    "pulse_pressure",
    "mean_arterial_pressure",
    "nocturnal_dipping",
    "hrv_recovery",
    "environmental_stress_index",
    "welch_ttest",
    "mann_whitney_u",
    "cohens_d",
    "compare",
    "to_csv",
    "to_excel",
    "to_json",
    "save",
    "generate",
    "loader",
    "cleaner",
    "metrics",
    "stats",
    "exporter",
    "pipeline",
    "synthetic",
]


def about() -> dict:
    """Short provenance block used by the API and the workbench footer."""
    return {
        "name": "HEARTMETRIC",
        "tagline": "Environmental Cardiovascular Response Platform",
        "version": __version__,
        "license": "MIT",
        "copyright": "Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University",
        "affiliation": "Independent open-source project; not affiliated with Oura Health Oy or Apple Inc.",
        "blood_pressure_source": "cuff reading exported from Apple Health (or any CSV/JSON); "
        "Oura API v2 exposes no blood-pressure endpoint",
    }
