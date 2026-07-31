"""Graph-level tests for the merge / idempotency & sparse-row contract (S1.3, #294).

Feeds the real sparse/full seam — a ``query_log``-shaped ``:Column`` (id + name only)
and a ``bigquery/schema``-shaped one (type, description, key flags) addressing the *same*
``id`` — through the writer against a Neo4j testcontainer, in both orders, and asserts
the GUIDE D10 contract: **non-clobber**, **idempotent**, **order-independent**.

Order-independence is asserted as whole-graph equality via ``dump_graph`` from the #291
characterization harness rather than per-property reads, so a stray extra node or edge
fails too. The negative controls matter as much as the positive ones: ``OVERWRITE`` on
the same feed is shown to erase, and today's shipped ``CREATE_ONLY`` default is
characterized as order-*dependent* — that divergence is the whole delta this contract
closes. See ``docs/refactor/merge-contract.md``.
"""

from __future__ import annotations

from typing import Any

import pytest
from neo4j import Driver, RoutingControl

from neocarta.data_model.schema.rdbms import Column, References
from neocarta.enums import NodeLabel, RelationshipType
from neocarta.ingest import MergePolicy
from neocarta.ingest.rdbms import Neo4jRDBMSLoader
from neocarta.ingest.utils import _build_node_ingest_query, _build_relationship_ingest_query
from tests.support.characterization import dump_graph

_DATABASE = "neo4j"

_SOURCE_ID = "test-project.sales.orders.customer_id"
_TARGET_ID = "test-project.sales.customers.customer_id"
_CRITERIA = "orders.customer_id = customers.customer_id"

# The property set both producers write. ``nullable`` is deliberately out of scope: it is
# a bare bool whose True default is indistinguishable from an asserted True, so only the
# property-scope layer can keep a sparse row from clobbering it (see the tests below).
SHARED_SCOPE = ["name", "description", "type", "is_primary_key", "is_foreign_key"]


def _full(column_id: str, name: str, description: str) -> Column:
    """A schema-connector-shaped row: everything the source knows."""
    return Column(
        id=column_id,
        name=name,
        description=description,
        type="INT64",
        nullable=False,
        is_primary_key=False,
        is_foreign_key=True,
    )


def _sparse(column_id: str, name: str) -> Column:
    """A sparse row that is honest about what it does not know: key flags are ``None``.

    This is the *normalized-contract* sparse shape — `ColumnRecord` defaults the key
    flags to ``None`` = "the source said nothing" — which is what connectors emit from
    S4 onward. Today's `connectors/query_log` predates that and leaves them at the
    graph model's ``False`` default; `_sparse_as_query_log_emits_today` below is that
    shape, and it is protected by the property-scope layer instead.
    """
    return Column(id=column_id, name=name, is_primary_key=None, is_foreign_key=None)


def _sparse_as_query_log_emits_today(column_id: str, name: str) -> Column:
    """Verbatim today's `connectors/query_log` row: ``Column(id=..., name=...)``.

    Its key flags therefore come out as a fabricated ``False`` rather than ``None``
    (`data_model.schema.rdbms.Column` defaults them to ``False``), which is exactly the
    two-state problem value coalescing cannot see through.
    """
    return Column(id=column_id, name=name)


def _expected_full_props(column_id: str, name: str, description: str) -> dict[str, Any]:
    """The stored properties of a fully-populated column under ``SHARED_SCOPE``."""
    return {
        "id": column_id,
        "name": name,
        "description": description,
        "type": "INT64",
        "is_primary_key": False,
        "is_foreign_key": True,
    }


def _write_columns(
    driver: Driver,
    columns: list[Column],
    policy: bool | MergePolicy,
    properties_list: list[str],
) -> None:
    """Write columns through the shared writer primitive the S5 generic writer consumes."""
    driver.execute_query(
        query_=_build_node_ingest_query(NodeLabel.COLUMN, policy, properties_list),
        parameters_={"rows": [column.model_dump() for column in columns]},
        routing_=RoutingControl.WRITE,
        database_=_DATABASE,
    )


def _write_references(
    driver: Driver, references: list[References], policy: bool | MergePolicy
) -> None:
    """Write REFERENCES edges — the one edge carrying a real, often-absent property."""
    driver.execute_query(
        query_=_build_relationship_ingest_query(
            RelationshipType.REFERENCES,
            NodeLabel.COLUMN,
            NodeLabel.COLUMN,
            "source_column_id",
            "target_column_id",
            policy,
            ["criteria"],
        ),
        parameters_={"rows": [reference.model_dump() for reference in references]},
        routing_=RoutingControl.WRITE,
        database_=_DATABASE,
    )


def _props(driver: Driver, column_id: str = _SOURCE_ID) -> dict[str, Any]:
    """The stored properties of one ``:Column``, as Neo4j actually holds them."""
    records, _, _ = driver.execute_query(
        query_="MATCH (n:Column {id: $id}) RETURN properties(n) AS props",
        parameters_={"id": column_id},
        routing_=RoutingControl.READ,
        database_=_DATABASE,
    )
    assert len(records) == 1, f"expected exactly one :Column {column_id!r}, got {len(records)}"
    return dict(records[0]["props"])


def _criteria(driver: Driver) -> Any:
    """The ``criteria`` property of the REFERENCES edge, or None when absent."""
    records, _, _ = driver.execute_query(
        query_="MATCH (:Column)-[r:REFERENCES]->(:Column) RETURN r.criteria AS criteria",
        routing_=RoutingControl.READ,
        database_=_DATABASE,
    )
    assert len(records) == 1, f"expected exactly one REFERENCES edge, got {len(records)}"
    return records[0]["criteria"]


def _wipe(driver: Driver) -> None:
    """Clear the graph mid-test so two feed orders can be compared in one test."""
    driver.execute_query(
        query_="MATCH (n) DETACH DELETE n", routing_=RoutingControl.WRITE, database_=_DATABASE
    )


# --- The contract ------------------------------------------------------------------


def test_sparse_then_full_loses_nothing(neo4j_driver) -> None:
    """A full row enriches a node a sparse producer already created."""
    _write_columns(
        neo4j_driver, [_sparse(_SOURCE_ID, "customer_id")], MergePolicy.COALESCE, SHARED_SCOPE
    )
    _write_columns(
        neo4j_driver,
        [_full(_SOURCE_ID, "customer_id", "FK to customers.")],
        MergePolicy.COALESCE,
        SHARED_SCOPE,
    )

    assert _props(neo4j_driver) == _expected_full_props(
        _SOURCE_ID, "customer_id", "FK to customers."
    )


def test_full_then_sparse_loses_nothing(neo4j_driver) -> None:
    """A sparse row's NULLs never erase what a fuller producer already wrote."""
    _write_columns(
        neo4j_driver,
        [_full(_SOURCE_ID, "customer_id", "FK to customers.")],
        MergePolicy.COALESCE,
        SHARED_SCOPE,
    )
    _write_columns(
        neo4j_driver, [_sparse(_SOURCE_ID, "customer_id")], MergePolicy.COALESCE, SHARED_SCOPE
    )

    assert _props(neo4j_driver) == _expected_full_props(
        _SOURCE_ID, "customer_id", "FK to customers."
    )


def test_feed_order_is_irrelevant(neo4j_driver) -> None:
    """Both feed orders converge on a byte-identical graph, nodes and edges alike."""
    sparse = [_sparse(_SOURCE_ID, "customer_id"), _sparse(_TARGET_ID, "customer_id")]
    full = [
        _full(_SOURCE_ID, "customer_id", "FK to customers."),
        _full(_TARGET_ID, "customer_id", "Customer primary key."),
    ]
    sparse_edge = [References(source_column_id=_SOURCE_ID, target_column_id=_TARGET_ID)]
    full_edge = [
        References(source_column_id=_SOURCE_ID, target_column_id=_TARGET_ID, criteria=_CRITERIA)
    ]

    _write_columns(neo4j_driver, sparse, MergePolicy.COALESCE, SHARED_SCOPE)
    _write_references(neo4j_driver, sparse_edge, MergePolicy.COALESCE)
    _write_columns(neo4j_driver, full, MergePolicy.COALESCE, SHARED_SCOPE)
    _write_references(neo4j_driver, full_edge, MergePolicy.COALESCE)
    sparse_first = dump_graph(neo4j_driver, _DATABASE)

    _wipe(neo4j_driver)

    _write_columns(neo4j_driver, full, MergePolicy.COALESCE, SHARED_SCOPE)
    _write_references(neo4j_driver, full_edge, MergePolicy.COALESCE)
    _write_columns(neo4j_driver, sparse, MergePolicy.COALESCE, SHARED_SCOPE)
    _write_references(neo4j_driver, sparse_edge, MergePolicy.COALESCE)
    full_first = dump_graph(neo4j_driver, _DATABASE)

    assert sparse_first == full_first
    # An empty-equals-empty pass would prove nothing: the converged graph really does
    # carry both producers' contributions.
    assert len(full_first["nodes"]) == 2
    assert len(full_first["relationships"]) == 1
    assert full_first["relationships"][0]["properties"] == {"criteria": _CRITERIA}
    assert all(node["properties"]["type"] == "INT64" for node in full_first["nodes"])


@pytest.mark.parametrize("sparse_first", [True, False], ids=["sparse-first", "full-first"])
def test_duplicate_ids_in_one_batch_coalesce_either_way(neo4j_driver, sparse_first: bool) -> None:
    """Order-independence holds *within* one UNWIND batch, so callers needn't dedupe it.

    ``UNWIND`` processes rows sequentially, so the second row for an id coalesces onto the state
    the first one left. ``OVERWRITE`` has no such property — the last row in the batch wins
    outright, which the sibling assertion below pins as the negative control.
    """
    sparse = _sparse(_SOURCE_ID, "customer_id")
    full = _full(_SOURCE_ID, "customer_id", "FK to customers.")
    batch = [sparse, full] if sparse_first else [full, sparse]

    _write_columns(neo4j_driver, batch, MergePolicy.COALESCE, SHARED_SCOPE)
    assert _props(neo4j_driver) == _expected_full_props(
        _SOURCE_ID, "customer_id", "FK to customers."
    )

    # Negative control: the same batch under OVERWRITE is order-dependent.
    _wipe(neo4j_driver)
    _write_columns(neo4j_driver, batch, MergePolicy.OVERWRITE, SHARED_SCOPE)
    expected = None if sparse_first is False else "FK to customers."
    assert _props(neo4j_driver).get("description") == expected


def test_re_emitting_a_row_is_a_no_op(neo4j_driver) -> None:
    """Idempotency: replaying either producer leaves the graph untouched."""
    full = [_full(_SOURCE_ID, "customer_id", "FK to customers.")]
    sparse = [_sparse(_SOURCE_ID, "customer_id")]

    _write_columns(neo4j_driver, full, MergePolicy.COALESCE, SHARED_SCOPE)
    _write_columns(neo4j_driver, sparse, MergePolicy.COALESCE, SHARED_SCOPE)
    settled = dump_graph(neo4j_driver, _DATABASE)

    for _ in range(2):
        _write_columns(neo4j_driver, full, MergePolicy.COALESCE, SHARED_SCOPE)
        _write_columns(neo4j_driver, sparse, MergePolicy.COALESCE, SHARED_SCOPE)

    assert dump_graph(neo4j_driver, _DATABASE) == settled
    assert settled["nodes"][0]["properties"]["description"] == "FK to customers."


def test_coalescing_never_mints_a_property_from_null(neo4j_driver) -> None:
    """A sparse row writes no property for what it does not know — absent, not NULL."""
    _write_columns(
        neo4j_driver, [_sparse(_SOURCE_ID, "customer_id")], MergePolicy.COALESCE, SHARED_SCOPE
    )

    assert _props(neo4j_driver) == {"id": _SOURCE_ID, "name": "customer_id"}


def test_relationship_property_is_coalesced(neo4j_driver) -> None:
    """An edge property survives a later edge row that does not carry it."""
    _write_columns(
        neo4j_driver,
        [_sparse(_SOURCE_ID, "customer_id"), _sparse(_TARGET_ID, "customer_id")],
        MergePolicy.COALESCE,
        ["name"],
    )
    _write_references(
        neo4j_driver,
        [References(source_column_id=_SOURCE_ID, target_column_id=_TARGET_ID, criteria=_CRITERIA)],
        MergePolicy.COALESCE,
    )
    _write_references(
        neo4j_driver,
        [References(source_column_id=_SOURCE_ID, target_column_id=_TARGET_ID)],
        MergePolicy.COALESCE,
    )

    assert _criteria(neo4j_driver) == _CRITERIA


def test_todays_query_log_row_needs_the_property_scope_layer_for_its_key_flags(
    neo4j_driver,
) -> None:
    """Today's real `query_log` row has a fabricated ``False``, not ``None``, key flag.

    So it is a *two-state* field, and value coalescing cannot see through it: put the key
    flags in scope and the sparse row's ``False`` replaces the full row's ``True``. What
    actually protects the graph today is that `connectors/query_log` writes
    ``properties_list=["name"]`` — the property-scope layer. Both halves are asserted
    here so the two-layer contract is proven against the producer as it exists, not only
    against the tri-state shape the normalized models will emit from S4.
    """
    full = [_full(_SOURCE_ID, "customer_id", "FK to customers.")]
    todays_sparse = [_sparse_as_query_log_emits_today(_SOURCE_ID, "customer_id")]

    # Coalescing alone: the fabricated False wins, because False is not NULL.
    _write_columns(neo4j_driver, full, MergePolicy.COALESCE, SHARED_SCOPE)
    assert _props(neo4j_driver)["is_foreign_key"] is True
    _write_columns(neo4j_driver, todays_sparse, MergePolicy.COALESCE, SHARED_SCOPE)
    assert _props(neo4j_driver)["is_foreign_key"] is False

    # With the real producer's scope, the same row cannot touch the flag at all.
    _wipe(neo4j_driver)
    _write_columns(neo4j_driver, full, MergePolicy.COALESCE, SHARED_SCOPE)
    _write_columns(neo4j_driver, todays_sparse, MergePolicy.COALESCE, ["name"])

    assert _props(neo4j_driver) == _expected_full_props(
        _SOURCE_ID, "customer_id", "FK to customers."
    )


# --- Negative controls: the contract is doing real work ----------------------------


def test_overwrite_erases_what_coalescing_preserves(neo4j_driver) -> None:
    """Sensitivity: the same feed under OVERWRITE loses the full row's properties."""
    _write_columns(
        neo4j_driver,
        [_full(_SOURCE_ID, "customer_id", "FK to customers.")],
        MergePolicy.OVERWRITE,
        SHARED_SCOPE,
    )
    _write_columns(
        neo4j_driver, [_sparse(_SOURCE_ID, "customer_id")], MergePolicy.OVERWRITE, SHARED_SCOPE
    )

    # Setting a property to NULL removes it in Neo4j, so the fuller data is simply gone.
    assert _props(neo4j_driver) == {"id": _SOURCE_ID, "name": "customer_id"}


def test_non_tri_state_field_is_not_protected_by_coalescing(neo4j_driver) -> None:
    """``nullable`` has no "unknown", so its fabricated True does replace a stored False.

    This is the documented reason the contract needs the property-scope layer as well as
    value coalescing — and why the normalized models default the *key* flags to ``None``.
    """
    scope = ["name", "nullable"]
    _write_columns(
        neo4j_driver,
        [_full(_SOURCE_ID, "customer_id", "FK to customers.")],
        MergePolicy.COALESCE,
        scope,
    )
    assert _props(neo4j_driver)["nullable"] is False

    _write_columns(neo4j_driver, [_sparse(_SOURCE_ID, "customer_id")], MergePolicy.COALESCE, scope)

    assert _props(neo4j_driver)["nullable"] is True


def test_property_scope_protects_a_non_tri_state_field(neo4j_driver) -> None:
    """Layer 1: leaving ``nullable`` out of the sparse producer's scope keeps it honest."""
    _write_columns(
        neo4j_driver,
        [_full(_SOURCE_ID, "customer_id", "FK to customers.")],
        MergePolicy.COALESCE,
        ["name", "nullable"],
    )
    _write_columns(
        neo4j_driver, [_sparse(_SOURCE_ID, "customer_id")], MergePolicy.COALESCE, ["name"]
    )

    assert _props(neo4j_driver)["nullable"] is False


# --- Parity: today's shipped behavior, characterized ------------------------------


@pytest.mark.parametrize("full_first", [True, False], ids=["full-then-sparse", "sparse-then-full"])
def test_todays_loader_default_is_non_clobbering_but_order_dependent(
    neo4j_driver, full_first: bool
) -> None:
    """Characterize `Neo4jRDBMSLoader`'s shipped CREATE_ONLY default on the sparse+full case.

    Reproduces the real pair of producers: a schema connector writing the full property
    set, and `connectors/query_log` writing ``properties_list=["name"]``. Today's writer
    never erases (D10's letter is met) but properties fire only ``ON CREATE``, so the
    fuller row is silently dropped whenever the sparse producer ran first. That is the
    order-dependence ``MergePolicy.COALESCE`` removes; this test is the before-picture,
    and it stays green because the legacy default is unchanged.
    """
    loader = Neo4jRDBMSLoader(neo4j_driver=neo4j_driver, database_name=_DATABASE)
    full = [_full(_SOURCE_ID, "customer_id", "FK to customers.")]
    sparse = [_sparse(_SOURCE_ID, "customer_id")]

    if full_first:
        loader.load_column_nodes(full)
        loader.load_column_nodes(sparse, properties_list=["name"])
    else:
        loader.load_column_nodes(sparse, properties_list=["name"])
        loader.load_column_nodes(full)

    props = _props(neo4j_driver)
    if full_first:
        # Non-clobber holds: the sparse row changed nothing.
        assert props["description"] == "FK to customers."
        assert props["type"] == "INT64"
        assert props["nullable"] is False
    else:
        # The fuller row never lands — the gap the contract closes.
        assert props == {"id": _SOURCE_ID, "name": "customer_id"}
