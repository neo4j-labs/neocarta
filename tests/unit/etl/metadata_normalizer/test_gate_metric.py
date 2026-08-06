"""The S1.6 (#297) go/no-go gate: the declarations stay small and the hatch list stays closed.

The ticket arms a **⚠ negative-outcome trigger** — *if the chosen mapping is as complex as or
more complex than today's per-connector shape, principle 2 has failed → escalate, don't
silently proceed.* GUIDE §9 wants that objectively checkable rather than an impression.

The **measurement** (52 declaration lines against 1 467 lines of `transform.py`, per connector)
was taken at spike time and is recorded in `docs/refactor/mapping-mechanism.md`. It is not
re-asserted here: pinning three production files' line counts would fail this suite on any
unrelated edit to them, which is a tax on other people's changes for a one-time finding.

What *is* an ongoing invariant, and is asserted: a declaration stays small in absolute terms,
and no fifth escape hatch appears. Those are the two ways the mechanism could quietly grow back
into the thing it replaced.
"""

from __future__ import annotations

import ast
import inspect

import pytest

from tests.support.mapping_spike import BIGQUERY_SCHEMA, CSV, JDBC_SCHEMA, connectors, hatch_usage

#: A declaration this size stopped being a declaration. The three real ones are 11-23 lines, so
#: the ceiling leaves room to add a table or two without becoming a tripwire.
MAX_DECLARATION_LINES = 40

#: The closed set of named hatches. A fifth appearing is a trigger condition, not a feature.
NAMED_HATCHES = frozenset({"pre_fold", "row_filter", "drop_self_references", "property_scope"})

#: Connector → its declaration constant, and the hatch usage the design doc reports.
DECLARATIONS = {
    "bigquery/schema": (
        "BIGQUERY_SCHEMA",
        BIGQUERY_SCHEMA,
        {"pre_fold": 1, "row_filter": 1, "drop_self_references": 1},
    ),
    "jdbc/schema": ("JDBC_SCHEMA", JDBC_SCHEMA, {"drop_self_references": 1, "property_scope": 1}),
    "csv": ("CSV", CSV, {"property_scope": 1}),
}


def _declaration_lines(constant_name: str) -> int:
    """Count the source lines of one declaration's assignment statement.

    Measured from the module AST so the number in the design doc is reproducible, and scoped to
    the assignment so the shared hatch helpers are not counted as declaration cost.
    """
    tree = ast.parse(inspect.getsource(connectors))
    for node in tree.body:
        if any(getattr(t, "id", None) == constant_name for t in getattr(node, "targets", [])):
            return node.end_lineno - node.lineno + 1
    message = f"{constant_name} not found in the declarations module"
    raise AssertionError(message)


@pytest.mark.parametrize("connector", sorted(DECLARATIONS))
def test_declaration_stays_small(connector: str) -> None:
    """A declaration is a declaration, not a transform in disguise."""
    constant, _, _ = DECLARATIONS[connector]
    lines = _declaration_lines(constant)
    assert lines <= MAX_DECLARATION_LINES, (
        f"⚠ TRIGGER: {connector}'s declaration is {lines} lines. Re-measure it against the "
        "transform it replaces and escalate per the ticket's go/no-go clause if the margin is "
        "gone, rather than raising this ceiling."
    )


@pytest.mark.parametrize("connector", sorted(DECLARATIONS))
def test_hatch_usage_is_named_and_unchanged(connector: str) -> None:
    """Only the four named hatches are used, in the amounts the design doc reports.

    Pinning the exact usage rather than only the names means a connector quietly acquiring a
    second `pre_fold`, or losing one, shows up as a decision to review — the hatch count is half
    the gate metric.
    """
    _, mapping, expected = DECLARATIONS[connector]
    used = hatch_usage(mapping)
    assert set(used) <= NAMED_HATCHES, (
        f"⚠ TRIGGER: {connector} uses an unnamed hatch {sorted(set(used) - NAMED_HATCHES)}; "
        "the gate metric requires the hatch list stay closed-ended."
    )
    assert used == expected


def test_bigquery_needs_no_property_scope() -> None:
    """BigQuery relies on the loader's property defaults, and says so by omission.

    Worth pinning because it is the one connector in the proof set that does *not* own property
    scope, so it is the control for the D10 obligation being genuinely per-source.
    """
    assert BIGQUERY_SCHEMA.property_scope is None
