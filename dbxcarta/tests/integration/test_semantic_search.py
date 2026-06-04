"""Integration tests for end-to-end semantic search through the graph.

Exercises the live embedding endpoint dimension, the Neo4j vector index, and
the graph expansion path. The graph contract stores only `embedding`, not the
source `embedding_text`, so self-ranking probes query with stored vectors.

Requires:
  - DBXCARTA_INCLUDE_EMBEDDINGS_TABLES=true in the most recent run — Table
    nodes must carry `embedding` vectors for the vector-index probes below.
  - A Databricks workspace reachable with the current SDK auth configuration.
"""

from __future__ import annotations

import pytest
import requests

pytestmark = pytest.mark.live

_TOP_K = 10
_SAMPLE = 5
_MIN_SELF_SIMILARITY = 0.99


def _tables_enabled(run_summary: dict) -> bool:
    flags = run_summary.get("embedding_flags") or {}
    return bool(flags.get("Table"))


def _embed_texts(ws, endpoint: str, texts: list[str]) -> list[list[float]]:
    """Call a Databricks Foundation Model API embedding endpoint.

    Uses ws.config.authenticate() so all auth schemes (PAT, OAuth, SP) work
    without assuming a token field is populated.
    """
    headers = ws.config.authenticate()
    resp = requests.post(
        f"{ws.config.host.rstrip('/')}/serving-endpoints/{endpoint}/invocations",
        headers=headers,
        json={"input": texts},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    data.sort(key=lambda x: x["index"])
    return [item["embedding"] for item in data]


def test_embedding_endpoint_returns_correct_dimension(neo4j_driver, ws, run_summary) -> None:
    """The live endpoint returns a vector whose length matches the index dimension."""
    if not _tables_enabled(run_summary):
        pytest.skip("Table embeddings not enabled in the latest run")

    endpoint = run_summary.get("embedding_model", "databricks-gte-large-en")

    with neo4j_driver.session() as session:
        row = session.run(
            "SHOW VECTOR INDEXES YIELD name, options WHERE name = 'table_embedding'"
        ).single()
    assert row is not None, "Vector index 'table_embedding' not found"
    expected_dim = row["options"]["indexConfig"]["vector.dimensions"]

    vecs = _embed_texts(ws, endpoint, ["tables related to customer orders"])
    assert len(vecs) == 1
    assert len(vecs[0]) == expected_dim


def test_table_semantic_self_ranking(neo4j_driver, run_summary) -> None:
    """Querying with a Table's own stored vector must recover that node.

    The graph no longer stores `embedding_text`; it stores only the vector.
    A self-vector score below the threshold indicates that the vector index is
    stale, missing the node, or reading the wrong property.

    This test is graph-size-independent: it checks the cosine score directly
    rather than rank, so it passes on a 3-table fixture as well as a
    million-row catalog.
    """
    if not _tables_enabled(run_summary):
        pytest.skip("Table embeddings not enabled in the latest run")

    with neo4j_driver.session() as session:
        rows = list(
            session.run(
                "MATCH (n:Table) WHERE n.embedding IS NOT NULL "
                f"RETURN n.id AS id, n.embedding AS vector LIMIT {_SAMPLE}"
            )
        )

    if not rows:
        pytest.skip("No Table nodes with embedding vectors found")

    with neo4j_driver.session() as session:
        for row in rows:
            result = session.run(
                "CALL db.index.vector.queryNodes('table_embedding', $k, $vec) "
                "YIELD node, score WHERE node.id = $id RETURN score",
                k=_TOP_K,
                vec=row["vector"],
                id=row["id"],
            ).single()
            assert result is not None, (
                f"Table '{row['id']}' not found in top-{_TOP_K} when its own "
                "stored embedding vector was queried"
            )
            assert result["score"] >= _MIN_SELF_SIMILARITY, (
                f"Table '{row['id']}' self-similarity score {result['score']:.4f} "
                f"< {_MIN_SELF_SIMILARITY} — index may be stale or property mapping is wrong"
            )


def test_graph_expansion_from_vector_search(neo4j_driver, run_summary) -> None:
    """A vector search result expands into a non-empty column subgraph.

    Uses a stored Table vector to find top-k Tables, then traverses
    HAS_COLUMN for the top result. This verifies that the vector index and
    relationship expansion still produce structured schema context.
    """
    if not _tables_enabled(run_summary):
        pytest.skip("Table embeddings not enabled in the latest run")

    with neo4j_driver.session() as session:
        probe = session.run(
            "MATCH (n:Table) WHERE n.embedding IS NOT NULL "
            "RETURN n.id AS id, n.embedding AS vector LIMIT 1"
        ).single()

    if probe is None:
        pytest.skip("No Table nodes with embedding vectors found")

    with neo4j_driver.session() as session:
        top_tables = list(
            session.run(
                "CALL db.index.vector.queryNodes('table_embedding', 5, $vec) "
                "YIELD node RETURN node.id AS id",
                vec=probe["vector"],
            )
        )
        assert top_tables, "Vector search returned no Table nodes"

        top_id = top_tables[0]["id"]
        columns = list(
            session.run(
                "MATCH (t:Table {id: $id})-[:HAS_COLUMN]->(c:Column) RETURN c.id AS id",
                id=top_id,
            )
        )

    assert columns, (
        f"Graph expansion from Table '{top_id}' returned no Column nodes — "
        "either the table has no columns in the graph or HAS_COLUMN relationships are missing"
    )
