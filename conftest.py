"""Pytest bootstrap: make the repository root importable without installing."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

FIXTURES = Path(__file__).resolve().parent / "tests" / "fixtures"

import pytest  # noqa: E402


@pytest.fixture()
def demo_frame():
    """The synthetic 14-day series, anomalies included (the cleaner handles them)."""
    from heartmetric_core import synthetic

    return synthetic.generate()
