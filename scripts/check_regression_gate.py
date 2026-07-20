"""Fail CI on a coverage or test-count regression against the committed baseline.

This is the enforcing half of the GUIDE §4 invariant — *"No coverage / test-count
regression. Never drop a test or lower coverage."* #287 added the measurement
(``make test-cov``) and #288 committed the machine-readable reference point
(``docs/testing/coverage-baseline.toml``); this script (S0-4 / #290) gives that
baseline teeth. It compares a fresh run against the committed floors and exits
non-zero — naming the offending metric — when either invariant is violated:

* **Coverage** — the fresh ``make test-cov`` coverage (regenerated here as JSON from
  the ``.coverage`` data file) must not fall below the ``[total]`` line/branch floors
  or any of the six ``[packages.*]`` per-package floors. The ``[informational.*]``
  tables (``_mcp`` / ``_cli``) are **not** gated here — those suites run in the
  separate ``test-mcp`` / ``test-cli`` jobs, and under the ``make test-cov`` scope they
  read as scope artifacts (see coverage-baseline.md → Scope caveat).
* **Test count** — the full ``tests/`` collected set must not shrink below the
  ``[test_count].all`` baseline. GUIDE §4 requires preserving the *collected test set*,
  so this spans every suite (unit + integration + smoke + ``_mcp`` / ``_cli`` / agent),
  not just the ``make test-cov`` scope. The collection is delegated to
  ``check_marker_parity.collect_with_status`` (the parity proof this gate was built to
  reuse); a non-healthy pytest exit is reported as a collection error rather than being
  misattributed to a dropped test.

Floors are compared inclusively (a fresh value equal to its floor passes); the floors
already carry ≈1pp headroom (truncated down to a whole percent) so branch-count jitter
can't flake the gate. This gate never *lowers* a floor — raising floors after a genuine,
sustained gain is a manual, ratchet-up edit to the TOML (coverage-baseline.md → Update
policy).

Run it after ``make test-cov`` (so ``.coverage`` exists) in a full environment
(``uv sync --all-groups --all-extras``, so every test module imports during collection)::

    make check-regression

Exits 0 when both invariants hold, else 1 (printing every offending metric).
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ``coverage-baseline.toml`` is read with the stdlib TOML parser (Python 3.11+; the CI
# coverage job runs 3.12), so the gate needs no dependency beyond coverage + pytest. The
# project floor is 3.10, which has no tomllib — turn that into a clear message.
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - only on the 3.10 project floor
    sys.exit(
        "check_regression_gate requires Python 3.11+ (stdlib tomllib); the CI coverage job runs 3.12."
    )

# Reuse the single collection implementation. ``scripts/`` is this script's own directory
# (sys.path[0]), so the sibling module imports directly. Its docstring already notes the
# S0-4 gate reuses it.
from check_marker_parity import collect_with_status

_REPO_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_PATH = _REPO_ROOT / "docs" / "testing" / "coverage-baseline.toml"
_COVERAGE_DATA = _REPO_ROOT / ".coverage"

# TOML key "root" == the loose ``neocarta/*.py`` modules (Cobertura package ".").
_ROOT_PACKAGE = "root"


def load_baseline() -> dict:
    """Load the committed coverage/test-count baseline.

    Returns:
        The parsed ``coverage-baseline.toml`` tables.

    Raises:
        SystemExit: If the baseline file is missing.
    """
    if not _BASELINE_PATH.exists():
        sys.exit(f"baseline not found: {_BASELINE_PATH.relative_to(_REPO_ROOT)}")
    with _BASELINE_PATH.open("rb") as handle:
        return tomllib.load(handle)


def _rates(summary: dict) -> tuple[float, float]:
    """Return ``(line %, branch %)`` from a coverage.py summary block.

    Computed from raw counts (``covered_lines`` / ``num_statements`` and
    ``covered_branches`` / ``num_branches``) so the numbers match the Cobertura
    ``line-rate`` / ``branch-rate`` the baseline was recorded from — not the combined
    ``percent_covered``. A package with no branches is treated as 100% branch-covered
    (coverage.py's own convention).

    Args:
        summary: A coverage.py ``summary`` dict (per-file or ``totals``).

    Returns:
        The line and branch coverage percentages (0.0 to 100.0).
    """
    statements = summary["num_statements"]
    branches = summary["num_branches"]
    line_pct = 100.0 * summary["covered_lines"] / statements if statements else 100.0
    branch_pct = 100.0 * summary["covered_branches"] / branches if branches else 100.0
    return line_pct, branch_pct


def fresh_coverage() -> dict[str, tuple[float, float]]:
    """Regenerate coverage from ``.coverage`` and aggregate by top-level package.

    Runs ``coverage json`` against the ``.coverage`` data file ``make test-cov`` left
    behind (honoring the ``[tool.coverage.*]`` config, so exclusions match the committed
    ``coverage.xml``), then rolls the per-file summaries up by the first path component
    under ``neocarta/`` — files directly under ``neocarta/`` fall in the ``root`` bucket.

    Returns:
        A mapping of ``"total"`` and each top-level package name to its
        ``(line %, branch %)``.

    Raises:
        SystemExit: If ``.coverage`` is missing or ``coverage json`` fails.
    """
    if not _COVERAGE_DATA.exists():
        sys.exit(
            f"no coverage data at {_COVERAGE_DATA.relative_to(_REPO_ROOT)} — "
            "run `make test-cov` first"
        )
    with tempfile.NamedTemporaryFile(suffix=".json") as report_file:
        # Trusted call: fixed argv, no external input; cwd is the repo so coverage finds
        # `.coverage` and the pyproject config.
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-m", "coverage", "json", "-o", report_file.name],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            sys.exit(f"`coverage json` failed:\n{proc.stdout}\n{proc.stderr}")
        report = json.loads(Path(report_file.name).read_text())

    # Sum raw counts per top-level package, then convert to rates once.
    buckets: dict[str, dict[str, int]] = {}
    for path, info in report["files"].items():
        parts = path.split("/")
        if parts and parts[0] == "neocarta":
            parts = parts[1:]
        package = _ROOT_PACKAGE if len(parts) <= 1 else parts[0]
        bucket = buckets.setdefault(
            package,
            {"num_statements": 0, "covered_lines": 0, "num_branches": 0, "covered_branches": 0},
        )
        summary = info["summary"]
        for key in bucket:
            bucket[key] += summary[key]

    coverage = {package: _rates(counts) for package, counts in buckets.items()}
    coverage["total"] = _rates(report["totals"])
    return coverage


def check_coverage(baseline: dict, coverage: dict[str, tuple[float, float]]) -> list[str]:
    """Compare fresh coverage against the total and per-package floors.

    Args:
        baseline: The parsed baseline tables.
        coverage: Fresh ``(line %, branch %)`` per package plus ``"total"``.

    Returns:
        One failure message per breached floor (empty if all pass). Prints an
        OK/FAIL line per checked scope as a side effect.
    """
    failures: list[str] = []
    # (label, floors-table, fresh-key): total first, then each enforceable package.
    scopes: list[tuple[str, dict, str]] = [("total", baseline["total"], "total")]
    scopes += [(name, floors, name) for name, floors in sorted(baseline["packages"].items())]

    print("Coverage floors (fresh vs committed baseline):")
    for label, floors, key in scopes:
        line_floor, branch_floor = floors["line_floor"], floors["branch_floor"]
        if key not in coverage:
            failures.append(f"coverage: package `{label}` not present in the fresh report")
            print(
                f"  FAIL {label:<14} not measured (expected line>={line_floor} branch>={branch_floor})"
            )
            continue
        line_pct, branch_pct = coverage[key]
        line_bad = line_pct < line_floor
        branch_bad = branch_pct < branch_floor
        status = "FAIL" if (line_bad or branch_bad) else "OK  "
        line_cmp = "<" if line_bad else ">="
        branch_cmp = "<" if branch_bad else ">="
        print(
            f"  {status} {label:<14} "
            f"line {line_pct:6.2f} {line_cmp} {line_floor:<3} "
            f"branch {branch_pct:6.2f} {branch_cmp} {branch_floor}"
        )
        if line_bad:
            failures.append(f"coverage: {label} line {line_pct:.2f}% < floor {line_floor}%")
        if branch_bad:
            failures.append(f"coverage: {label} branch {branch_pct:.2f}% < floor {branch_floor}%")
    return failures


def check_test_count(baseline: dict) -> list[str]:
    """Compare the full ``tests/`` collected count against the baseline.

    Args:
        baseline: The parsed baseline tables.

    Returns:
        A single-element failure list if collection errored or the count dropped, else
        empty. Prints an OK/FAIL line as a side effect.
    """
    floor = baseline["test_count"]["all"]
    node_ids, returncode = collect_with_status(["tests"])
    collected = len(node_ids)
    print("\nTest count (full tests/ collected set):")
    # A non-healthy pytest exit (anything but 0/5) means a module failed to import or
    # collect, so the count is incomplete for a reason other than a deletion. Report the
    # real cause instead of misattributing it to a dropped test.
    if returncode not in (0, 5):
        print(f"  FAIL collection error (pytest exit {returncode}); only {collected} collected")
        return [
            f"test collection FAILED (pytest exit {returncode}): a test module could not be "
            "collected (import/syntax error), so the suite is incomplete — fix the collection "
            "error and re-run. Run `uv run pytest --collect-only tests` to see the offending module."
        ]
    if collected < floor:
        print(f"  FAIL {collected} < {floor}")
        return [f"test count: {collected} collected < baseline {floor} (a test was dropped)"]
    print(f"  OK   {collected} >= {floor}")
    return []


def main() -> int:
    """Run both regression checks and return a process exit code.

    Returns:
        0 if coverage and the collected test count both hold the baseline, else 1
        (after printing every offending metric).
    """
    baseline = load_baseline()
    failures = check_coverage(baseline, fresh_coverage())
    failures += check_test_count(baseline)

    if failures:
        print("\nRegression gate FAILED — the following dropped below the #288 baseline:")
        for message in failures:
            print(f"  - {message}")
        print(
            "\nGUIDE §4 forbids lowering coverage or dropping a test. If this is an "
            "intentional, justified ratchet, update docs/testing/coverage-baseline.toml "
            "(raise floors / counts only) in the same PR — never hand-lower a floor to pass."
        )
        return 1
    print("\nRegression gate PASSED — coverage and test count hold the #288 baseline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
