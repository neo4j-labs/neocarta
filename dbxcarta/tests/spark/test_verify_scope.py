"""Regression tests for catalog-scoped verify checks.

The verify node/edge/value count checks scope their Cypher to the resolved
catalog set so a shared Neo4j instance is not a source of false positives, and
so a multi-catalog run is checked against its aggregate summary totals rather
than one catalog's subset.

Two properties are pinned here:

1. Id normalization: node ids go through ``contract.generate_id`` (lowercased;
   spaces and hyphens become underscores). The scoping predicate must apply
   the same normalization, or a hyphenated catalog reads every scoped count as
   0 and a correct ingest fails the verify gate.
2. Multi-catalog scope: when ``settings.resolved_catalogs()`` lists more than
   one catalog, the count invariants must sum across all of them. Scoping to
   only the single primary catalog made every aggregate count mismatch on
   every multi-catalog run.
"""

from __future__ import annotations

import re

import pytest
from dbxcarta.spark import verify
from dbxcarta.spark.contract import generate_id, generate_value_id
from dbxcarta.spark.verify import graph as graph_mod
from dbxcarta.spark.verify import references as references_mod
from dbxcarta.spark.verify import values as values_mod

_NODE_LABEL = re.compile(r"\(n:(\w+)\)")
_REL_SRC = re.compile(r"\(src:(\w+)\)-\[r:(\w+)\]")

# A catalog/schema whose names contain hyphens — the exact trigger.
_CATALOG = "graph-enriched-lakehouse"
_SCHEMA = "graph-enriched-schema"

# A medallion-style multi-catalog set (the production Finance Genie shape:
# silver and gold, folded into one graph).
_SILVER = "graph-enriched-finance-silver"
_GOLD = "graph-enriched-finance-gold"


class _Result:
    def __init__(self, cnt: int) -> None:
        self._cnt = cnt

    def single(self):
        return {"cnt": self._cnt}


def _any_prefix(node_id: str, prefixes) -> bool:
    return any(node_id.startswith(p) for p in (prefixes or []))


class _Session:
    def __init__(self, nodes, rels) -> None:
        self._nodes = nodes
        self._rels = rels

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def run(self, cypher: str, **params):
        if "count(r)" in cypher:
            rel = _REL_SRC.search(cypher).group(2)
            prefixes = params.get("prefixes")
            cnt = sum(1 for rt, sid in self._rels if rt == rel and _any_prefix(sid, prefixes))
            return _Result(cnt)
        label = _NODE_LABEL.search(cypher).group(1)
        if "catalog_ids" in params:
            ids = set(params["catalog_ids"])
            cnt = sum(1 for lb, nid in self._nodes if lb == label and nid in ids)
        elif "prefixes" in params:
            cnt = sum(
                1 for lb, nid in self._nodes if lb == label and _any_prefix(nid, params["prefixes"])
            )
        else:
            cnt = sum(1 for lb, _ in self._nodes if lb == label)
        return _Result(cnt)


class _Driver:
    def __init__(self, nodes, rels=()) -> None:
        self._nodes = list(nodes)
        self._rels = list(rels)

    def session(self):
        return _Session(self._nodes, self._rels)


def test_scoped_catalog_normalizes_hyphens():
    catalog_id, prefix = verify.scoped_catalog({"catalog": _CATALOG})
    assert catalog_id == "graph_enriched_lakehouse"
    assert prefix == "graph_enriched_lakehouse."


def test_scoped_catalog_empty_summary():
    assert verify.scoped_catalog({}) == ("", ".")


def test_scoped_catalogs_falls_back_to_single_when_list_empty():
    ids, prefixes = verify.scoped_catalogs({"catalog": _CATALOG}, None)
    assert ids == ["graph_enriched_lakehouse"]
    assert prefixes == ["graph_enriched_lakehouse."]
    assert verify.scoped_catalogs({"catalog": _CATALOG}, []) == (ids, prefixes)


def test_scoped_catalogs_normalizes_every_resolved_catalog():
    ids, prefixes = verify.scoped_catalogs({"catalog": _SILVER}, [_SILVER, _GOLD])
    assert ids == [
        "graph_enriched_finance_silver",
        "graph_enriched_finance_gold",
    ]
    assert prefixes == [i + "." for i in ids]


def _graph_nodes(catalog=_CATALOG, schema=_SCHEMA):
    db_id = generate_id(catalog)
    schema_id = generate_id(catalog, schema)
    nodes = [("Database", db_id), ("Schema", schema_id)]
    for t in ["orders", "customers"]:
        nodes.append(("Table", generate_id(catalog, schema, t)))
    for col in ["id", "name", "total"]:
        nodes.append(("Column", generate_id(catalog, schema, "orders", col)))
    return nodes


def test_node_counts_pass_with_hyphenated_catalog():
    """The exact production scenario: correct graph, hyphenated catalog."""
    summary = {
        "catalog": _CATALOG,
        "row_counts": {"databases": 1, "schemas": 1, "tables": 2, "columns": 3},
    }
    driver = _Driver(_graph_nodes())
    assert graph_mod._check_node_counts(driver, summary) == []


def test_node_counts_still_flag_a_real_mismatch():
    """The fix must not blanket-pass: a genuinely missing node still fails."""
    summary = {
        "catalog": _CATALOG,
        "row_counts": {"databases": 1, "schemas": 1, "tables": 2, "columns": 3},
    }
    nodes = [
        *[n for n in _graph_nodes() if n[0] != "Table"][:1],
        ("Table", generate_id(_CATALOG, _SCHEMA, "orders")),
    ]
    violations = graph_mod._check_node_counts(_Driver(nodes), summary)
    codes = {v.code for v in violations}
    assert "graph.node_count_mismatch.Table" in codes


def test_node_counts_pass_for_multi_catalog_aggregate():
    """A medallion run: 2 catalogs written, summary counts the aggregate.

    Scoping to only the primary (silver) catalog would see 1 Database / 1
    Schema / 2 Tables / 3 Columns and mismatch the 2/2/4/6 aggregate. With the
    full resolved-catalog scope the sums match.
    """
    nodes = _graph_nodes(_SILVER, _SCHEMA) + _graph_nodes(_GOLD, _SCHEMA)
    summary = {
        "catalog": _SILVER,
        "row_counts": {"databases": 2, "schemas": 2, "tables": 4, "columns": 6},
    }
    assert graph_mod._check_node_counts(_Driver(nodes), summary, catalogs=[_SILVER, _GOLD]) == []


def test_node_counts_multi_catalog_flags_missing_catalog():
    """If one catalog's nodes are missing, the aggregate still mismatches."""
    nodes = _graph_nodes(_SILVER, _SCHEMA)
    summary = {
        "catalog": _SILVER,
        "row_counts": {"databases": 2, "schemas": 2, "tables": 4, "columns": 6},
    }
    codes = {
        v.code
        for v in graph_mod._check_node_counts(_Driver(nodes), summary, catalogs=[_SILVER, _GOLD])
    }
    assert "graph.node_count_mismatch.Database" in codes
    assert "graph.node_count_mismatch.Table" in codes


def test_references_edge_count_scoped_with_hyphenated_catalog():
    summary = {
        "catalog": _CATALOG,
        "row_counts": {"fk_edges": 1, "fk_inferred_metadata_accepted": 0},
    }
    src_col = generate_id(_CATALOG, _SCHEMA, "orders", "customer_id")
    driver = _Driver(nodes=(), rels=[("REFERENCES", src_col)])
    assert references_mod._check_edge_count(driver, summary) == []


def test_references_edge_count_multi_catalog_aggregate():
    """Inferred edges land per-catalog (cross-catalog pairing is blocked); the
    aggregate REFERENCES total must sum across every resolved catalog."""
    rels = [
        ("REFERENCES", generate_id(_SILVER, _SCHEMA, "orders", "customer_id")),
        ("REFERENCES", generate_id(_GOLD, _SCHEMA, "orders", "customer_id")),
    ]
    summary = {
        "catalog": _SILVER,
        "row_counts": {"fk_edges": 0, "fk_inferred_metadata_accepted": 2},
    }
    assert (
        references_mod._check_edge_count(
            _Driver(nodes=(), rels=rels), summary, catalogs=[_SILVER, _GOLD]
        )
        == []
    )
    # Scoping to silver alone would see 1, not the aggregate 2 -> mismatch.
    assert references_mod._check_edge_count(_Driver(nodes=(), rels=rels), summary)


def test_value_count_scoped_with_hyphenated_catalog():
    summary = {"catalog": _CATALOG, "row_counts": {"value_nodes": 2}}
    col_id = generate_id(_CATALOG, _SCHEMA, "orders", "status")
    value_nodes = [
        ("Value", generate_value_id(col_id, "open")),
        ("Value", generate_value_id(col_id, "closed")),
    ]
    assert values_mod._check_value_count(_Driver(value_nodes), summary) == []


def test_value_count_multi_catalog_aggregate():
    silver_col = generate_id(_SILVER, _SCHEMA, "orders", "status")
    gold_col = generate_id(_GOLD, _SCHEMA, "orders", "status")
    value_nodes = [
        ("Value", generate_value_id(silver_col, "open")),
        ("Value", generate_value_id(silver_col, "closed")),
        ("Value", generate_value_id(gold_col, "open")),
    ]
    summary = {"catalog": _SILVER, "row_counts": {"value_nodes": 3}}
    assert (
        values_mod._check_value_count(_Driver(value_nodes), summary, catalogs=[_SILVER, _GOLD])
        == []
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
