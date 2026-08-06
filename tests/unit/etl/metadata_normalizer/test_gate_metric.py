"""The S1.6 (#297) go/no-go gate: declarations stay small and the hatch list stays closed.

The ticket armed a **⚠ negative-outcome trigger** — *if the chosen mapping is as complex as or
more complex than today's per-connector shape, principle 2 has failed → escalate, don't silently
proceed.* GUIDE §9 wants that objectively checkable rather than an impression.

The **measurement** (52 declaration lines against 1 467 lines of ``transform.py``, for the three
proof-set connectors) was taken at spike time and is recorded in
``docs/refactor/mapping-mechanism.md``. It is not re-asserted here: pinning production files' line
counts would fail this suite on any unrelated edit to them, which is a tax on other people's
changes for a one-time finding.

What *is* an ongoing invariant, and is asserted: a declaration stays small in absolute terms, and
no fifth escape hatch appears. Those are the two ways the mechanism could quietly grow back into
the thing it replaced. #298 widened the sweep from three declarations to five.
"""

import ast
import inspect
from importlib import import_module

from neocarta.etl.metadata_normalizer import hatch_usage
from tests.support.connectors.registry import BY_CONNECTOR, DECLARATIONS

#: A declaration this size stopped being a declaration. The five real ones measure 11-28 lines
#: (query_log is the largest), so the ceiling leaves room to add a table or two without becoming a
#: tripwire.
MAX_DECLARATION_LINES = 40

#: The closed set of named hatches. A fifth appearing is a trigger condition, not a feature.
NAMED_HATCHES = frozenset({"pre_fold", "row_filter", "drop_self_references", "property_scope"})

#: The hatch usage each connector's declaration is expected to have. Pinned rather than merely
#: bounded, so a connector quietly acquiring a second ``pre_fold``, or losing one, shows up as a
#: decision to review — the hatch count is half the gate metric.
EXPECTED_HATCHES = {
    "bigquery/schema": {"pre_fold": 1, "row_filter": 1, "drop_self_references": 1},
    "jdbc/schema": {"drop_self_references": 1, "property_scope": 1},
    "csv": {"property_scope": 1},
    "databricks/tags": {"property_scope": 1},
    "query_log": {"pre_fold": 4, "property_scope": 1},
}


def declaration_lines(declared):
    """Count the source lines of one declaration's assignment statement.

    Measured from the module AST so the number in the design doc is reproducible, and scoped to
    the assignment so the module docstring, imports and hatch helpers are **not** counted as
    declaration cost. Deliberately not ``len(getsource(module).splitlines())``, which would
    silently redefine the gate.

    An annotated ``NAME: T = ...`` is an ``ast.AnnAssign`` with no ``.targets`` and would raise
    below rather than be measured — which is the right failure, since it says plainly that the
    measurement needs updating.
    """
    tree = ast.parse(inspect.getsource(import_module(declared.module)))
    for node in tree.body:
        targets = getattr(node, "targets", [])
        if any(getattr(target, "id", None) == declared.constant for target in targets):
            return node.end_lineno - node.lineno + 1
    message = f"{declared.constant} not found in {declared.module}"
    raise AssertionError(message)


class TestDeclarationsStaySmall:
    """A declaration is a declaration, not a transform in disguise."""

    def test_declaration_stays_under_the_ceiling(self, connector):
        declared = BY_CONNECTOR[connector]
        lines = declaration_lines(declared)
        assert lines <= MAX_DECLARATION_LINES, (
            f"⚠ TRIGGER: {connector}'s declaration is {lines} lines. Re-measure it against the "
            "transform it replaces and escalate per the ticket's go/no-go clause if the margin "
            "is gone, rather than raising this ceiling."
        )


class TestHatchUsageIsNamedAndUnchanged:
    """Only the four named hatches are used, in the amounts the design record reports."""

    def test_hatch_usage_matches(self, connector):
        used = hatch_usage(BY_CONNECTOR[connector].mapping)
        assert set(used) <= NAMED_HATCHES, (
            f"⚠ TRIGGER: {connector} uses an unnamed hatch {sorted(set(used) - NAMED_HATCHES)}; "
            "the gate metric requires the hatch list stay closed-ended."
        )
        assert used == EXPECTED_HATCHES[connector]

    def test_every_connector_is_pinned(self):
        assert set(EXPECTED_HATCHES) == {declared.connector for declared in DECLARATIONS}


def test_bigquery_needs_no_property_scope():
    """BigQuery relies on the loader's property defaults, and says so by omission.

    Worth pinning because it is the only declared connector that does *not* own property scope, so
    it is the control for the **D10** obligation being genuinely per-source.
    """
    assert BY_CONNECTOR["bigquery/schema"].mapping.property_scope is None
