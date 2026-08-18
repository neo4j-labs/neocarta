"""Unit tests for the semantic-memory cypher factories (no database required)."""

from neocarta._mcp.cypher import (
    capture_task_memory_cypher,
    recall_task_memory_expand_cypher,
    recall_task_memory_fulltext_cypher,
    recall_task_memory_vector_cypher,
)


def test_capture_merges_task_on_id_with_no_secondary_label() -> None:
    """Task is merged on $task_id and carries :Task only.

    A secondary :Memory label would opt these nodes into the generic
    mcp-neo4j-memory contract, which expands one undirected hop out of every
    :Memory node and requires each neighbour to have a `name`. Phrase and Query
    have none, so the label broke that server's read_graph for the whole graph.
    """
    cypher = capture_task_memory_cypher()
    assert "MERGE (t:Task {id: $task_id})" in cypher
    assert ":Memory" not in cypher
    # `type` existed only to populate that server's Entity.type; :Task says it now.
    assert "t.type" not in cypher


def test_capture_accumulates_observations_without_duplicates() -> None:
    """Observations append across captures rather than overwriting.

    Re-capturing an existing task name must not erase what earlier captures
    learned — phrasings accumulate, and observations have to accumulate with
    them — while re-passing an identical note must not duplicate it.
    """
    cypher = capture_task_memory_cypher()
    assert (
        "t.observations =\n"
        "        [o IN coalesce(t.observations, []) WHERE NOT o IN $observations] + $observations"
    ) in cypher
    # A bare assignment would clobber prior captures.
    assert "t.observations = $observations" not in cypher


def test_capture_merges_phrase_and_query_and_links_catalog() -> None:
    """Phrase/Query merge on their deterministic ids; only Phrase is embedded."""
    cypher = capture_task_memory_cypher()
    assert "MERGE (p:Phrase {id: $phrase_id})" in cypher
    assert "MERGE (q:Query {id: $query_id})" in cypher
    assert "p.embedding = $phrase_embedding" in cypher
    assert "q.embedding" not in cypher
    assert "MERGE (t)-[:HAS_PHRASE]->(p)" in cypher
    # captured_at lets recall pick the latest Query for a re-captured Task.
    assert "MERGE (t)-[r:HAS_QUERY]->(q)" in cypher
    assert "r.captured_at = datetime()" in cypher
    # Catalog links MATCH (never MERGE) the Table/Column nodes, so capture cannot
    # invent catalog objects the connectors did not load.
    assert "MATCH (tb:Table {id: tid})" in cypher
    assert "MERGE (q)-[:USES_TABLE]->(tb)" in cypher
    assert "MATCH (c:Column {id: cid})" in cypher
    assert "MERGE (q)-[:USES_COLUMN]->(c)" in cypher


def test_recall_search_branches_roll_phrases_up_to_task() -> None:
    """Both branches search Phrase indexes and max-pool to the owning Task."""
    vector = recall_task_memory_vector_cypher()
    assert "phrase_vector_index" in vector
    assert "$vectorFloor" in vector
    assert "MATCH (t:Task)-[:HAS_PHRASE]->(p)" in vector
    assert "max(score) AS score" in vector

    fulltext = recall_task_memory_fulltext_cypher()
    assert "phrase_full_text_index" in fulltext
    assert "MATCH (t:Task)-[:HAS_PHRASE]->(p)" in fulltext
    assert "max(score) AS score" in fulltext


def test_recall_expand_returns_observations() -> None:
    """Expand projects observations so the notes reach the calling agent.

    Capture has always written `observations`, but nothing read them: neither
    search branch indexes them and the expand projection omitted them, so they
    were reachable only through the (now removed) :Memory label.
    """
    cypher = recall_task_memory_expand_cypher()
    assert "coalesce(t.observations, []) AS observations" in cypher


def test_recall_expand_picks_latest_query_and_projects_lineage() -> None:
    """Expand is keyed by elementId and returns the most recent Query's lineage."""
    cypher = recall_task_memory_expand_cypher()
    assert "elementId(t) = $eid" in cypher
    assert "ORDER BY r.captured_at DESC" in cypher
    assert "collect(q)[0] AS q" in cypher
    for field in ("task_name", "phrasings", "query_description", "sql", "tables", "columns"):
        assert f"AS {field}" in cypher
