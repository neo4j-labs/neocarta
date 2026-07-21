"""Shared fixtures usable by both the unit and integration test suites.

Fixtures here are loaded for every ``tests/`` run (rootdir is the repo root), so
keep this file to genuinely cross-cutting fixtures — colocated per-package
fixtures remain the norm elsewhere.

This module also auto-applies the suite-group marker to every collected test (see
``pytest_collection_modifyitems`` below), which is what lets ``make test-*`` select
by marker rather than by directory path (S0-3 / GUIDE D4).
"""

import os
from pathlib import Path

import pytest

# Suite-group markers, keyed by where a test file lives under ``tests/``. Special
# subdirectories win over the parent ``unit``/``integration`` group (checked first),
# mirroring the legacy ``--ignore`` layout so the marker-selected set is identical
# to the old path-selected set.
_SUBDIR_MARKERS = (("_mcp", "mcp"), ("_cli", "cli"), ("agent", "agent"))
_ROOT_MARKERS = {"smoke": "smoke", "integration": "integration", "unit": "unit"}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--update-goldens`` for the characterization harness (S0-SPIKE-1)."""
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Regenerate characterization golden files instead of comparing against them.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Map ``--update-goldens`` onto the ``UPDATE_GOLDENS`` env flag the harness reads."""
    if config.getoption("--update-goldens"):
        os.environ["UPDATE_GOLDENS"] = "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-tag every collected test with its suite-group marker by location.

    Assigns exactly one registered group marker (``mcp``/``cli``/``agent``/``smoke``/
    ``integration``/``unit``) to each item based on where its file lives under
    ``tests/``, so ``make test-*`` can select by ``-m <marker>`` instead of by
    directory path (S0-3 / GUIDE D4). This keeps selection intent-based and stable
    across the file moves in later refactor tickets.

    Args:
        config: The pytest config, used to resolve the ``tests/`` root.
        items: The collected test items, mutated in place via ``add_marker``.
    """
    tests_root = Path(config.rootpath) / "tests"
    for item in items:
        try:
            parts = item.path.relative_to(tests_root).parts
        except ValueError:
            continue  # Defensive: item not under tests/ — leave it untagged.
        marker = next((m for seg, m in _SUBDIR_MARKERS if seg in parts), None)
        if marker is None and parts:
            marker = _ROOT_MARKERS.get(parts[0])
        if marker is not None:
            item.add_marker(marker)
