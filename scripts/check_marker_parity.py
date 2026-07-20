"""Prove pytest-marker selection matches the legacy path-based selection.

S0-3 moved ``make test-*`` selection from directory paths to pytest markers. This
script is the parity proof the ticket requires (and that the S0-4 CI gate will
reuse): for every target it collects the test set two ways — the legacy path/
``--ignore`` expression and the new marker (``-m``) expression — and asserts the two
sets are identical. It also asserts the markers *partition* the suite (every
collected test carries exactly one group marker), which is what makes the switch
safe against tests silently dropping out of a target.

Run it in a full environment (``uv sync --all-groups`` plus all extras) so that every
module — including the ``agent`` and ``mcp`` suites — imports during collection::

    make check-markers

Exits non-zero (printing the offending node ids) if any target's sets differ or the
partition invariant is violated.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Every group marker registered in pyproject.toml.
MARKERS = ("unit", "integration", "mcp", "cli", "agent", "smoke")

# Per-target: the legacy path/--ignore selection vs the new marker selection. The two
# must collect an identical set. Paths mirror the Makefile test-* recipes exactly.
TARGETS: dict[str, dict[str, list[str]]] = {
    "unit": {
        "path": [
            "tests/unit",
            "--ignore=tests/unit/_mcp",
            "--ignore=tests/unit/_cli",
            "--ignore=tests/unit/agent",
        ],
        "marker": [
            "tests/unit",
            "-m",
            "unit",
            "--ignore=tests/unit/_mcp",
            "--ignore=tests/unit/_cli",
            "--ignore=tests/unit/agent",
        ],
    },
    "integration": {
        "path": [
            "tests/integration",
            "--ignore=tests/integration/_mcp",
            "--ignore=tests/integration/_cli",
        ],
        "marker": [
            "tests/integration",
            "-m",
            "integration",
            "--ignore=tests/integration/_mcp",
            "--ignore=tests/integration/_cli",
        ],
    },
    "mcp": {
        "path": ["tests/integration/_mcp", "tests/unit/_mcp"],
        "marker": ["tests/integration/_mcp", "tests/unit/_mcp", "-m", "mcp"],
    },
    "cli": {
        "path": ["tests/unit/_cli"],
        "marker": ["tests/unit/_cli", "-m", "cli"],
    },
    "agent": {
        "path": ["tests/unit/agent"],
        "marker": ["tests/unit/agent", "-m", "agent"],
    },
    "smoke": {
        "path": ["tests/smoke"],
        "marker": ["tests/smoke", "-m", "smoke"],
    },
}


def collect(args: list[str]) -> set[str]:
    """Return the set of test node ids pytest collects for ``args``.

    Args:
        args: Extra arguments appended to ``pytest --collect-only -q`` (paths,
            ``-m`` expressions, ``--ignore`` flags).

    Returns:
        The collected node ids (lines containing ``::``).

    Raises:
        SystemExit: If pytest reports a collection error.
    """
    # Trusted call: the argv is this repo's own interpreter plus the hardcoded target
    # definitions above — no external/untrusted input reaches the command.
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    node_ids = {line for line in proc.stdout.splitlines() if "::" in line}
    if proc.returncode not in (0, 5) and not node_ids:  # 5 == no tests collected
        sys.exit(f"pytest collection failed for {args}:\n{proc.stdout}\n{proc.stderr}")
    return node_ids


def check_target_parity() -> bool:
    """Assert marker selection equals path selection for every target.

    Returns:
        True if all targets match, False otherwise (with a diff printed).
    """
    ok = True
    for name, expr in TARGETS.items():
        by_path = collect(expr["path"])
        by_marker = collect(expr["marker"])
        if by_path == by_marker:
            print(f"  OK   {name:<12} {len(by_path)} tests (path == marker)")
            continue
        ok = False
        print(f"  FAIL {name:<12} path={len(by_path)} marker={len(by_marker)}")
        for node in sorted(by_path - by_marker):
            print(f"         only in path selection:   {node}")
        for node in sorted(by_marker - by_path):
            print(f"         only in marker selection: {node}")
    return ok


def check_partition() -> bool:
    """Assert the markers partition the full suite (exactly one marker per test).

    Returns:
        True if the per-marker sets are pairwise disjoint and cover the full tree.
    """
    ok = True
    full = collect(["tests"])
    by_marker = {m: collect(["tests", "-m", m]) for m in MARKERS}

    union: set[str] = set()
    for marker, nodes in by_marker.items():
        overlap = union & nodes
        if overlap:
            ok = False
            print(f"  FAIL {marker} overlaps a prior marker on {len(overlap)} tests:")
            for node in sorted(overlap):
                print(f"         double-tagged: {node}")
        union |= nodes

    untagged = full - union
    if untagged:
        ok = False
        print(f"  FAIL {len(untagged)} collected tests carry no group marker:")
        for node in sorted(untagged):
            print(f"         untagged: {node}")
    extra = union - full
    if extra:
        ok = False
        print(f"  FAIL {len(extra)} marker-selected tests are not in the full tree:")
        for node in sorted(extra):
            print(f"         unexpected: {node}")
    if ok:
        print(f"  OK   partition: {len(full)} tests, exactly one group marker each")
    return ok


def main() -> int:
    """Run both checks and return a process exit code.

    Returns:
        0 if selection parity and the partition invariant both hold, else 1.
    """
    print("Marker parity (legacy path selection == -m marker selection):")
    parity_ok = check_target_parity()
    print("\nMarker partition (every test tagged with exactly one group marker):")
    partition_ok = check_partition()
    if parity_ok and partition_ok:
        print("\nAll marker checks passed.")
        return 0
    print("\nMarker checks FAILED.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
