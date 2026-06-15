"""Pure-Python tests for the Databricks identifier builders.

These pin the node-identity contract: ``qualified_name`` is a lossless, injective
encoding of the identifier tuple, and ``node_id`` is its md5 — the collision-safe
MERGE key. No Spark needed (the Spark exprs are checked for agreement in
``test_schema_graph``).
"""

from __future__ import annotations

import hashlib

from neocarta.connectors.databricks.ingest.contract_expr import node_id, qualified_name


def test_qualified_name_lowercases_and_joins_with_dots():
    """The readable path is lowercased and dot-joined."""
    assert qualified_name("My-Catalog", "Sales", "Orders") == "my-catalog.sales.orders"


def test_qualified_name_preserves_hyphens():
    """Hyphens survive verbatim (the old scheme folded them to ``_``)."""
    assert qualified_name("c", "graph-enriched-schema") == "c.graph-enriched-schema"


def test_node_id_is_md5_of_qualified_name():
    """The MERGE key is exactly ``md5(qualified_name)`` — 32 lowercase hex chars."""
    expected = hashlib.md5(b"c.sales.orders", usedforsecurity=False).hexdigest()
    nid = node_id("c", "sales", "orders")
    assert nid == expected
    assert len(nid) == 32
    assert all(ch in "0123456789abcdef" for ch in nid)


def test_node_id_is_case_insensitive():
    """UC stores names lowercased, so case variants are the same object and id."""
    assert node_id("C", "Sales", "Orders") == node_id("c", "sales", "orders")


def test_hyphen_and_underscore_no_longer_collide():
    """The regression this scheme fixes: ``a-b`` and ``a_b`` are distinct Unity
    Catalog objects and must MERGE to distinct nodes. Under the old lossy
    normalization they collapsed to one id and corrupted the graph."""
    dashed = node_id("c", "graph-enriched-schema")
    scored = node_id("c", "graph_enriched_schema")
    assert dashed != scored
    assert qualified_name("c", "graph-enriched-schema") != qualified_name(
        "c", "graph_enriched_schema"
    )


def test_distinct_legal_tuples_get_distinct_ids():
    """Distinct identifier tuples produce distinct keys. Injectivity rests on a
    Unity Catalog guarantee — object names contain no ``.`` — so the dotted join
    is unambiguous (a part like ``b.c`` is not a legal UC name and cannot occur).
    The builder relies on that guarantee rather than enforcing it."""
    ids = {
        node_id("a", "b"),
        node_id("a", "b", "c"),
        node_id("a", "bc"),
        node_id("ab", "c"),
    }
    assert len(ids) == 4
