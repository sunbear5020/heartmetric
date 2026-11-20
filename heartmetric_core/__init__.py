"""HEARTMETRIC Core — clean-room cardiovascular × environment analytics.

HEARTMETRIC joins three streams that are usually kept apart — cuff blood
pressure, wearable heart rate / HRV, and environmental exposure — onto one
standard table so that the same analysis can be reproduced from a notebook, an
API call or the in-browser workbench.

v0.2.0 adds what a real study needs before a number can be trusted:

* ``align.align_streams`` — join separate files by time proximity (or by day)
  with a tolerance the researcher chooses, keeping a per-stream match report;
* ``stats.paired_subject_compare`` — subject-level paired comparison with a
  paired t-test, Cohen's d_z, a sign-flip permutation p and an exact sign test;
* ``stats.correlation_profile`` — Pearson r, Spearman ρ and an OLS slope with
  its confidence interval for environment × cardiovascular pairs;
* ``provenance.METHODOLOGY`` — formula, unit, reference and boundary for every
  indicator (measured / derived / exploratory);
* ``exporter.to_markdown`` — a reproducible Markdown report beside the Excel
  workbook and the ``schema_version``-tagged JSON bundle.

Hardware boundary: Oura Ring does not provide mmHg blood pressure through its
API (Oura API v2 has no blood-pressure endpoint), so HEARTMETRIC never pretends
to read BP from a ring. Cuff BP comes from an Apple Health export or any CSV;
the ring/watch contributes HR and HRV. Apple Health reports HRV as SDNN, Oura as
RMSSD: the two are never converted into one another. HEARTMETRIC is an
independent project and is not affiliated with Oura Health Oy or Apple Inc.

License: MIT · Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University
"""

from __future__ import annotations

__version__ = "0.2.0"

from . import (  # noqa: E402
    align,
    cleaner,
    exporter,
    loader,
    metrics,
    pipeline,
    provenance,
    stats,
    synthetic,
)
from .align import AlignedStreams, AlignmentReport, align_files, align_streams  # noqa: E402
from .cleaner import CleanReport, clean  # noqa: E402
from .exporter import (  # noqa: E402
    methodology_frame,
    save,
    to_csv,
    to_csv_dir,
    to_excel,
    to_json,
    to_markdown,
)
from .loader import load_any, load_csv, load_file, load_json, merge  # noqa: E402
from .metrics import (  # noqa: E402
    environmental_load,
    environmental_stress_index,
    hrv_recovery,
    mean_arterial_pressure,
    nocturnal_dipping,
    pulse_pressure,
)
from .pipeline import (  # noqa: E402
    SCHEMA_VERSION,
    analyze,
    analyze_file,
    analyze_loaded,
    analyze_streams,
    demo_bundle,
    demo_streams,
)
from .provenance import METHODOLOGY, REFERENCES, methodology  # noqa: E402
from .schema import STANDARD_COLUMNS  # noqa: E402
from .stats import (  # noqa: E402
    cohens_d,
    cohens_dz,
    compare,
    compare_table,
    correlation_profile,
    correlation_table,
    linear_regression,
    mann_whitney_u,
    paired_subject_compare,
    paired_ttest,
    pearson,
    sign_flip_permutation,
    sign_test,
    spearman,
    subject_pairs,
    welch_ttest,
    wilcoxon_signed_rank,
)
from .synthetic import generate  # noqa: E402

__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "STANDARD_COLUMNS",
    "METHODOLOGY",
    "REFERENCES",
    "methodology",
    "analyze",
    "analyze_file",
    "analyze_loaded",
    "analyze_streams",
    "demo_bundle",
    "demo_streams",
    "clean",
    "CleanReport",
    "load_any",
    "load_csv",
    "load_file",
    "load_json",
    "merge",
    "align",
    "align_streams",
    "align_files",
    "AlignedStreams",
    "AlignmentReport",
    "pulse_pressure",
    "mean_arterial_pressure",
    "nocturnal_dipping",
    "hrv_recovery",
    "environmental_stress_index",
    "environmental_load",
    "welch_ttest",
    "paired_ttest",
    "mann_whitney_u",
    "cohens_d",
    "cohens_dz",
    "sign_flip_permutation",
    "sign_test",
    "wilcoxon_signed_rank",
    "subject_pairs",
    "paired_subject_compare",
    "compare",
    "compare_table",
    "pearson",
    "spearman",
    "linear_regression",
    "correlation_profile",
    "correlation_table",
    "to_csv",
    "to_csv_dir",
    "to_excel",
    "to_json",
    "to_markdown",
    "save",
    "methodology_frame",
    "generate",
    "loader",
    "cleaner",
    "metrics",
    "stats",
    "exporter",
    "pipeline",
    "synthetic",
    "provenance",
]


def about() -> dict:
    """Short provenance block used by the API and the workbench footer."""
    return {
        "name": "HEARTMETRIC",
        "tagline": "Environmental Cardiovascular Response Platform",
        "version": __version__,
        "schema_version": SCHEMA_VERSION,
        "license": "MIT",
        "copyright": "Copyright (c) 2026 FEI · HEL Lab, Gyeongsang National University",
        "affiliation": "Independent open-source project; not affiliated with Oura Health Oy or Apple Inc.",
        "blood_pressure_source": "cuff reading exported from Apple Health (or any CSV/JSON); "
        "Oura API v2 exposes no blood-pressure endpoint",
    }
