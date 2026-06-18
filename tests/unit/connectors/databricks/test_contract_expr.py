"""Pure-Python tests for the Databricks identifier builders.

These pin the node-identity contract: ``node_id`` is the shared neocarta
``compose_id`` (the MERGE key, uniform with the other connectors), and
``qualified_name`` is the lossless readable path stored alongside it. No Spark
needed (the Spark exprs are checked for agreement in ``test_schema_graph``).
"""

from __future__ import annotations

from neocarta.connectors.databricks.ingest.contract_expr import node_id, qualified_name
from neocarta.connectors.utils.generate_id import compose_id


def test_qualified_name_lowercases_and_joins_with_dots():
    """The readable path is lowercased and dot-joined."""
    assert qualified_name("My-Catalog", "Sales", "Orders") == "my-catalog.sales.orders"


def test_qualified_name_preserves_hyphens():
    """``qualified_name`` is lossless: hyphens survive verbatim."""
    assert qualified_name("c", "graph-enriched-schema") == "c.graph-enriched-schema"


def test_node_id_is_the_shared_compose_id():
    """The MERGE key is exactly the shared ``compose_id``: lowercase, spaces and
    hyphens folded to ``_``, dot-joined."""
    assert node_id("My-Catalog", "Sales", "Orders") == "my_catalog.sales.orders"
    assert node_id("c", "sales", "orders") == compose_id("c", "sales", "orders")


def test_node_id_is_case_insensitive():
    """UC stores names lowercased, so case variants are the same object and id."""
    assert node_id("C", "Sales", "Orders") == node_id("c", "sales", "orders")


def test_hyphen_and_underscore_fold_to_one_id():
    """The shared normalization is lossy: ``a-b`` and ``a_b`` fold to the same
    ``node_id`` and MERGE collapses them into one node. ``qualified_name`` keeps
    the distinct readable paths even where the id folds them."""
    dashed = node_id("c", "graph-enriched-schema")
    scored = node_id("c", "graph_enriched_schema")
    assert dashed == scored
    assert qualified_name("c", "graph-enriched-schema") != qualified_name(
        "c", "graph_enriched_schema"
    )


def test_distinct_arity_tuples_get_distinct_ids():
    """Tuples that differ by where the part boundaries fall produce distinct keys.
    The dotted join is unambiguous because Unity Catalog object names contain no
    ``.``, so a part like ``b.c`` cannot occur."""
    ids = {
        node_id("a", "b"),
        node_id("a", "b", "c"),
        node_id("a", "bc"),
        node_id("ab", "c"),
    }
    assert len(ids) == 4
