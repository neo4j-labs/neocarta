"""Negative-control tests for the #290 coverage / test-count regression gate.

The gate (``scripts/check_regression_gate.py``) is the enforcing half of the GUIDE §4
"no coverage / test-count regression" invariant, so a version that silently *never fires*
would pass CI green while enforcing nothing — the exact failure the ticket's "demonstrated
red" acceptance criterion exists to prevent. These tests are that demonstration, wired as
an automated control rather than a one-off scratch-branch run: they prove ``main()`` (and
the pure checks it composes) goes **red** on a below-floor coverage drop and on a shrunken
collected count, and **green** on a healthy run. This mirrors the #291 characterization
harness, whose Layer-A goldens each ship a sibling test asserting an injected change is
caught ("a golden that can't fail guards nothing").

The gate reads its baseline with stdlib ``tomllib`` and ``sys.exit()``s at import on
Python < 3.11, so this module is skipped there (the gate only runs in the 3.12 CI job).
"""

import sys

import pytest

if sys.version_info < (3, 11):  # gate imports stdlib tomllib; skip where it is absent
    pytest.skip(
        "check_regression_gate requires Python 3.11+ (stdlib tomllib)",
        allow_module_level=True,
    )

import check_regression_gate as gate  # placed after the version guard above (gate exits pre-3.11)

# A minimal baseline mirroring the shape of docs/testing/coverage-baseline.toml: a total
# floor, a couple of enforceable per-package floors, and the gated collected-count floor.
_BASELINE = {
    "total": {"line_floor": 68, "branch_floor": 49},
    "packages": {
        "connectors": {"line_floor": 78, "branch_floor": 60},
        "root": {"line_floor": 95, "branch_floor": 86},
    },
    "test_count": {"all": 1205},
}

# Fresh coverage that clears every floor above (the "healthy run" the gate must pass).
_HEALTHY_COVERAGE = {
    "total": (68.53, 49.30),
    "connectors": (78.45, 60.41),
    "root": (95.50, 86.84),
}


def _collect_stub(node_count, returncode=0):
    """Build a ``collect_with_status`` replacement reporting ``node_count`` ids.

    Args:
        node_count: How many distinct collected node ids the stub reports.
        returncode: The pytest exit code to report (0 == healthy; non-0/5 == collection error).

    Returns:
        A callable with ``collect_with_status``'s ``(node_ids, returncode)`` shape that
        ignores the argument it is passed.
    """

    def _stub(_args):
        return ({f"tests/x.py::test_{i}" for i in range(node_count)}, returncode)

    return _stub


# --- _rates: raw-count -> percentage, with coverage.py's no-branches convention -------


def test_rates_computes_line_and_branch_percentages():
    """`_rates` turns raw covered/total counts into line and branch percentages."""
    line, branch = gate._rates(
        {
            "num_statements": 200,
            "covered_lines": 137,
            "num_branches": 100,
            "covered_branches": 49,
        }
    )
    assert line == pytest.approx(68.5)
    assert branch == pytest.approx(49.0)


def test_rates_treats_no_branches_as_full_branch_coverage():
    """A package with zero branches reads as 100% branch-covered (coverage.py convention)."""
    _, branch = gate._rates(
        {"num_statements": 10, "covered_lines": 10, "num_branches": 0, "covered_branches": 0}
    )
    assert branch == 100.0


# --- check_coverage: total + per-package floor comparison -----------------------------


def test_check_coverage_passes_when_all_scopes_clear_their_floor():
    """No failures when total and every package hold their line and branch floors."""
    assert gate.check_coverage(_BASELINE, _HEALTHY_COVERAGE) == []


def test_check_coverage_is_inclusive_at_the_floor():
    """A fresh value exactly equal to its floor passes (the comparison is `< floor`)."""
    at_floor = {"total": (68.0, 49.0), "connectors": (78.0, 60.0), "root": (95.0, 86.0)}
    assert gate.check_coverage(_BASELINE, at_floor) == []


def test_check_coverage_fails_on_a_line_drop_below_floor():
    """A total line rate a hair below the floor is reported as a coverage regression."""
    dropped = {**_HEALTHY_COVERAGE, "total": (67.99, 49.30)}
    failures = gate.check_coverage(_BASELINE, dropped)
    assert len(failures) == 1
    assert "total line" in failures[0]


def test_check_coverage_fails_on_a_branch_drop_below_floor():
    """A per-package branch rate below its floor is reported as a coverage regression."""
    dropped = {**_HEALTHY_COVERAGE, "connectors": (78.45, 59.9)}
    failures = gate.check_coverage(_BASELINE, dropped)
    assert len(failures) == 1
    assert "connectors branch" in failures[0]


def test_check_coverage_fails_when_a_baselined_package_is_missing():
    """A package present in the baseline but absent from the fresh report fails the gate."""
    missing = {"total": (68.53, 49.30), "connectors": (78.45, 60.41)}
    failures = gate.check_coverage(_BASELINE, missing)
    assert len(failures) == 1
    assert "`root`" in failures[0]


# --- check_test_count: full-suite collected-count floor -------------------------------


def test_check_test_count_passes_when_count_holds(monkeypatch):
    """A collected count at or above the baseline passes."""
    monkeypatch.setattr(gate, "collect_with_status", _collect_stub(1205))
    assert gate.check_test_count(_BASELINE) == []


def test_check_test_count_fails_when_a_test_is_dropped(monkeypatch):
    """A collected count below the baseline is reported as a dropped test."""
    monkeypatch.setattr(gate, "collect_with_status", _collect_stub(1204))
    failures = gate.check_test_count(_BASELINE)
    assert len(failures) == 1
    assert "dropped" in failures[0]


def test_check_test_count_reports_a_collection_error_as_such(monkeypatch):
    """A non-healthy pytest exit is surfaced as a collection error, not a dropped test."""
    monkeypatch.setattr(gate, "collect_with_status", _collect_stub(3, returncode=2))
    failures = gate.check_test_count(_BASELINE)
    assert len(failures) == 1
    assert "collection FAILED" in failures[0]
    assert "dropped" not in failures[0]


# --- main: the end-to-end red/green control the AC asks for ---------------------------


def test_main_returns_zero_on_a_healthy_run(monkeypatch):
    """`main` exits 0 when coverage and the collected count both hold the baseline."""
    monkeypatch.setattr(gate, "load_baseline", lambda: _BASELINE)
    monkeypatch.setattr(gate, "fresh_coverage", lambda: _HEALTHY_COVERAGE)
    monkeypatch.setattr(gate, "collect_with_status", _collect_stub(1205))
    assert gate.main() == 0


def test_main_returns_one_on_an_injected_coverage_drop(monkeypatch):
    """`main` exits 1 when fresh coverage falls below a floor (the AC's coverage-drop case)."""
    monkeypatch.setattr(gate, "load_baseline", lambda: _BASELINE)
    monkeypatch.setattr(
        gate, "fresh_coverage", lambda: {**_HEALTHY_COVERAGE, "total": (67.99, 49.30)}
    )
    monkeypatch.setattr(gate, "collect_with_status", _collect_stub(1205))
    assert gate.main() == 1


def test_main_returns_one_on_a_deleted_test(monkeypatch):
    """`main` exits 1 when the collected count shrinks (the AC's deleted-test case)."""
    monkeypatch.setattr(gate, "load_baseline", lambda: _BASELINE)
    monkeypatch.setattr(gate, "fresh_coverage", lambda: _HEALTHY_COVERAGE)
    monkeypatch.setattr(gate, "collect_with_status", _collect_stub(1204))
    assert gate.main() == 1
