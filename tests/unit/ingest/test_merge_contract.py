"""Contract-level tests for the merge / idempotency & sparse-row policy (S1.3, #294).

Proves the Cypher the writer generates per :class:`MergePolicy`: that ``COALESCE`` wraps
every property in ``coalesce(row.p, n.p)`` so an incoming ``NULL`` cannot erase a stored
value (GUIDE D10), that the legacy ``overwrite_existing`` boolean still generates
byte-identical Cypher in both of its spellings (parity, GUIDE §2), and — the negative
control — that the other two policies do **not** coalesce, so these guards can fail.

The graph-level proof that sparse→full and full→sparse lose nothing and are
order-independent lives in ``tests/integration/ingest/test_merge_contract_IT.py``; here
we prove the generated statement only. See ``docs/refactor/merge-contract.md``.
"""

from __future__ import annotations

import numpy as np
import pytest

from neocarta.enums import NodeLabel, RelationshipType
from neocarta.errors import ConfigError
from neocarta.ingest import MergePolicy as ExportedMergePolicy
from neocarta.ingest.utils import (
    MergePolicy,
    _build_node_ingest_query,
    _build_relationship_ingest_query,
    _resolve_merge_policy,
)

# The full :Column property set — the sparse/full seam this contract exists for.
COLUMN_PROPERTIES = [
    "name",
    "description",
    "type",
    "nullable",
    "is_primary_key",
    "is_foreign_key",
]

ALL_POLICIES = [MergePolicy.CREATE_ONLY, MergePolicy.OVERWRITE, MergePolicy.COALESCE]


def _relationship_query(merge_policy: bool | MergePolicy, properties_list: list[str]) -> str:
    """Build a REFERENCES query — the one edge with a real (and often absent) property."""
    return _build_relationship_ingest_query(
        RelationshipType.REFERENCES,
        NodeLabel.COLUMN,
        NodeLabel.COLUMN,
        "source_column_id",
        "target_column_id",
        merge_policy,
        properties_list,
    )


class TestPolicyResolution:
    """The legacy boolean spelling maps onto the enum, and nothing else is accepted."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(False, MergePolicy.CREATE_ONLY, id="False-is-create-only"),
            pytest.param(True, MergePolicy.OVERWRITE, id="True-is-overwrite"),
        ],
    )
    def test_legacy_bool_resolves(self, value: bool, expected: MergePolicy) -> None:
        assert _resolve_merge_policy(value) is expected

    @pytest.mark.parametrize("policy", ALL_POLICIES)
    def test_policy_passes_through(self, policy: MergePolicy) -> None:
        assert _resolve_merge_policy(policy) is policy

    @pytest.mark.parametrize("policy", ALL_POLICIES)
    def test_string_value_resolves(self, policy: MergePolicy) -> None:
        # The enum is str-valued, so a config-supplied string is usable as-is.
        assert _resolve_merge_policy(policy.value) is policy

    @pytest.mark.parametrize("value", ["", "coalesce_all", "COALESCE", "on_create", "True"])
    def test_unknown_policy_string_is_rejected(self, value: str) -> None:
        # A string is unambiguously a policy name, so a typo must raise rather than be
        # reinterpreted as a truthy legacy flag — that would silently pick OVERWRITE,
        # which erases data, for a caller who meant COALESCE.
        with pytest.raises(ConfigError, match="Unknown merge policy"):
            _resolve_merge_policy(value)

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            pytest.param(None, MergePolicy.CREATE_ONLY, id="None"),
            pytest.param(0, MergePolicy.CREATE_ONLY, id="int-0"),
            pytest.param(1, MergePolicy.OVERWRITE, id="int-1"),
            pytest.param(np.bool_(False), MergePolicy.CREATE_ONLY, id="numpy-False"),
            pytest.param(np.bool_(True), MergePolicy.OVERWRITE, id="numpy-True"),
        ],
    )
    def test_legacy_non_bool_flags_keep_their_truthiness_meaning(
        self, value: object, expected: MergePolicy
    ) -> None:
        # ``overwrite_existing`` was annotated ``bool`` but accepted anything truthy, and
        # connectors read pandas frames (where a bool column yields ``numpy.bool_``).
        # Widening the argument must not narrow what it tolerates.
        assert _resolve_merge_policy(value) is expected

    def test_policy_is_exported_from_the_ingest_package(self) -> None:
        # Callers configure the policy; it is public surface, not a builder-private detail.
        assert ExportedMergePolicy is MergePolicy


class TestLegacyBoolParity:
    """GUIDE §2 parity: widening the argument changed no existing call site's Cypher."""

    @pytest.mark.parametrize(
        ("legacy", "policy"),
        [
            pytest.param(False, MergePolicy.CREATE_ONLY, id="create-only"),
            pytest.param(True, MergePolicy.OVERWRITE, id="overwrite"),
        ],
    )
    @pytest.mark.parametrize(
        "properties_list",
        [
            pytest.param([], id="no-properties"),
            pytest.param(["name"], id="one-property"),
            pytest.param(COLUMN_PROPERTIES, id="all-properties"),
        ],
    )
    def test_node_query_is_identical(
        self, legacy: bool, policy: MergePolicy, properties_list: list[str]
    ) -> None:
        assert _build_node_ingest_query(
            NodeLabel.COLUMN, legacy, properties_list
        ) == _build_node_ingest_query(NodeLabel.COLUMN, policy, properties_list)

    @pytest.mark.parametrize(
        ("legacy", "policy"),
        [
            pytest.param(False, MergePolicy.CREATE_ONLY, id="create-only"),
            pytest.param(True, MergePolicy.OVERWRITE, id="overwrite"),
        ],
    )
    def test_node_query_with_secondary_labels_is_identical(
        self, legacy: bool, policy: MergePolicy
    ) -> None:
        assert _build_node_ingest_query(
            NodeLabel.TABLE, legacy, ["name"], secondary_labels=[NodeLabel.OSI_TABLE]
        ) == _build_node_ingest_query(
            NodeLabel.TABLE, policy, ["name"], secondary_labels=[NodeLabel.OSI_TABLE]
        )

    @pytest.mark.parametrize(
        ("legacy", "policy"),
        [
            pytest.param(False, MergePolicy.CREATE_ONLY, id="create-only"),
            pytest.param(True, MergePolicy.OVERWRITE, id="overwrite"),
        ],
    )
    @pytest.mark.parametrize(
        "properties_list",
        [pytest.param([], id="no-properties"), pytest.param(["criteria"], id="criteria")],
    )
    def test_relationship_query_is_identical(
        self, legacy: bool, policy: MergePolicy, properties_list: list[str]
    ) -> None:
        assert _relationship_query(legacy, properties_list) == _relationship_query(
            policy, properties_list
        )


class TestCoalesceNodeQuery:
    """The non-clobber node statement, pinned verbatim."""

    def test_full_property_set(self) -> None:
        assert (
            _build_node_ingest_query(NodeLabel.COLUMN, MergePolicy.COALESCE, COLUMN_PROPERTIES)
            == """
UNWIND $rows as row
MERGE (n:Column {id: row.id})
SET n.name = coalesce(row.name, n.name),
    n.description = coalesce(row.description, n.description),
    n.type = coalesce(row.type, n.type),
    n.nullable = coalesce(row.nullable, n.nullable),
    n.is_primary_key = coalesce(row.is_primary_key, n.is_primary_key),
    n.is_foreign_key = coalesce(row.is_foreign_key, n.is_foreign_key)"""
        )

    def test_one_property(self) -> None:
        assert (
            _build_node_ingest_query(NodeLabel.SCHEMA, MergePolicy.COALESCE, ["name"])
            == """
UNWIND $rows as row
MERGE (n:Schema {id: row.id})
SET n.name = coalesce(row.name, n.name)"""
        )

    def test_secondary_labels_apply_on_every_merge(self) -> None:
        # Adding a label cannot lose information, so it is unconditional — no ON MATCH
        # clause is needed the way CREATE_ONLY needs one.
        assert (
            _build_node_ingest_query(
                NodeLabel.TABLE,
                MergePolicy.COALESCE,
                ["name", "description"],
                secondary_labels=[NodeLabel.OSI_TABLE],
            )
            == """
UNWIND $rows as row
MERGE (n:Table {id: row.id})
SET n:OsiTable,
    n.name = coalesce(row.name, n.name),
    n.description = coalesce(row.description, n.description)"""
        )

    def test_no_properties_and_no_labels_is_a_bare_merge(self) -> None:
        assert (
            _build_node_ingest_query(NodeLabel.COLUMN, MergePolicy.COALESCE, [])
            == """
UNWIND $rows as row
MERGE (n:Column {id: row.id})"""
        )


class TestCoalesceRelationshipQuery:
    """The non-clobber relationship statement, pinned verbatim."""

    def test_one_property(self) -> None:
        assert (
            _relationship_query(MergePolicy.COALESCE, ["criteria"])
            == """
UNWIND $rows as row
MATCH (n1:Column {id: row.source_column_id})
MATCH (n2:Column {id: row.target_column_id})
MERGE (n1)-[r:REFERENCES]->(n2)
SET r.criteria = coalesce(row.criteria, r.criteria)"""
        )

    def test_multiple_properties(self) -> None:
        assert (
            _relationship_query(MergePolicy.COALESCE, ["criteria", "name"])
            == """
UNWIND $rows as row
MATCH (n1:Column {id: row.source_column_id})
MATCH (n2:Column {id: row.target_column_id})
MERGE (n1)-[r:REFERENCES]->(n2)
SET r.criteria = coalesce(row.criteria, r.criteria),
    r.name = coalesce(row.name, r.name)"""
        )

    def test_no_properties_is_a_bare_merge(self) -> None:
        assert (
            _relationship_query(MergePolicy.COALESCE, [])
            == """
UNWIND $rows as row
MATCH (n1:Column {id: row.source_column_id})
MATCH (n2:Column {id: row.target_column_id})
MERGE (n1)-[r:REFERENCES]->(n2)"""
        )


class TestOnlyCoalesceCoalesces:
    """Negative control: a guard that can't fail guards nothing."""

    @pytest.mark.parametrize(
        "policy", [MergePolicy.CREATE_ONLY, MergePolicy.OVERWRITE, False, True]
    )
    def test_other_policies_assign_the_raw_row_value(self, policy: bool | MergePolicy) -> None:
        node = _build_node_ingest_query(NodeLabel.COLUMN, policy, COLUMN_PROPERTIES)
        assert "coalesce(" not in node
        assert "n.description = row.description" in node
        edge = _relationship_query(policy, ["criteria"])
        assert "coalesce(" not in edge
        assert "r.criteria = row.criteria" in edge

    @pytest.mark.parametrize("prop", COLUMN_PROPERTIES)
    def test_coalesce_wraps_every_property(self, prop: str) -> None:
        query = _build_node_ingest_query(NodeLabel.COLUMN, MergePolicy.COALESCE, COLUMN_PROPERTIES)
        assert f"n.{prop} = coalesce(row.{prop}, n.{prop})" in query
        # No property escapes the wrapper.
        assert f"n.{prop} = row.{prop}" not in query

    def test_coalesce_writes_on_every_merge_not_only_on_create(self) -> None:
        # An ON CREATE clause would reintroduce first-writer-wins, which is precisely
        # the order-dependence the contract removes.
        query = _build_node_ingest_query(NodeLabel.COLUMN, MergePolicy.COALESCE, COLUMN_PROPERTIES)
        assert "ON CREATE" not in query
        assert "ON MATCH" not in query

    def test_create_only_still_gates_properties_on_create(self) -> None:
        query = _build_node_ingest_query(
            NodeLabel.COLUMN, MergePolicy.CREATE_ONLY, COLUMN_PROPERTIES
        )
        assert "ON CREATE" in query


class TestIdempotencyIsStructural:
    """Every policy addresses the entity by ``id``, so a re-emitted row cannot duplicate it."""

    @pytest.mark.parametrize("policy", ALL_POLICIES)
    def test_node_merges_on_id_exactly_once(self, policy: MergePolicy) -> None:
        query = _build_node_ingest_query(NodeLabel.COLUMN, policy, COLUMN_PROPERTIES)
        assert query.count("MERGE (n:Column {id: row.id})") == 1
        assert "CREATE (" not in query

    @pytest.mark.parametrize("policy", ALL_POLICIES)
    def test_relationship_merges_on_the_endpoint_pair(self, policy: MergePolicy) -> None:
        query = _relationship_query(policy, ["criteria"])
        assert query.count("MERGE (n1)-[r:REFERENCES]->(n2)") == 1
        assert "CREATE (" not in query

    @pytest.mark.parametrize("policy", ALL_POLICIES)
    def test_each_property_is_assigned_once(self, policy: MergePolicy) -> None:
        query = _build_node_ingest_query(NodeLabel.COLUMN, policy, COLUMN_PROPERTIES)
        for prop in COLUMN_PROPERTIES:
            assert query.count(f"n.{prop} = ") == 1
