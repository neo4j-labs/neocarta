"""Filesystem paths used by the characterization harness."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    """Return the repository root (the directory containing ``datasets/`` and ``neocarta/``)."""
    # This file lives at <root>/tests/support/characterization/paths.py.
    return Path(__file__).resolve().parents[3]


DATASETS_CSV: Path = repo_root() / "datasets" / "csv"
"""The committed CSV sample dataset — the deterministic offline input for the CSV connector."""
