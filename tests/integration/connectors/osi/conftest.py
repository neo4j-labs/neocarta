"""Pytest fixtures for OSI connector integration tests."""

from pathlib import Path

import pytest

# Re-use the TPC-DS sample copied into the unit-test fixtures dir.
_UNIT_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "unit"
    / "connectors"
    / "osi"
    / "fixtures"
    / "tpcds_osi.yaml"
)


@pytest.fixture
def tpcds_yaml_path() -> Path:
    """Filesystem path to the TPC-DS OSI sample (shared with unit tests)."""
    return _UNIT_FIXTURE
