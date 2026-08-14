"""Cypher for the ``capture_task_memory`` tool.

Writes a user-confirmed question/SQL pair into semantic memory: a ``Task``
(merge key: id derived from its name) with an embedded ``Phrase`` child, and a
canonical ``Query`` linked to the ``Table`` / ``Column`` nodes it uses. Only the
Phrase carries an embedding.
"""


def capture_task_memory_cypher() -> str:
    """MERGE the Task/Phrase/Query graph and link the Query to catalog nodes.

    Idempotent by design: the Task merges on ``$task_id`` (its name), the Phrase
    on ``$phrase_id`` (its normalized wording), and the Query on ``$query_id``
    (the canonical-SQL hash). Re-capturing the same name attaches more phrasings;
    re-capturing a surface-variant SQL dedupes onto the one canonical Query. The
    ``HAS_QUERY`` relationship stamps ``captured_at`` so recall can pick the
    latest query for a Task.

    Notes:
    -----
    Expected Cypher parameters:

    task_id : str
        Deterministic Task id (``generate_task_id`` of the name).
    name : str
        PascalCase task name.
    observations : list[str]
        Analytical notes stored on the Task.
    phrase_id : str
        Deterministic Phrase id (``generate_phrase_id`` of the question).
    question : str
        The verbatim question, stored as ``Phrase.verbatim``.
    phrase_embedding : list[float]
        Embedding of the question; the only embedded node.
    query_id : str
        Canonical-SQL hash (``create_query_id`` of the canonical SQL).
    sql : str
        Canonical SQL text, stored as ``Query.query``.
    description : str
        One-sentence description of what the SQL computes.
    table_ids : list[str]
        Catalog ``Table`` ids parsed from the canonical SQL.
    column_ids : list[str]
        Catalog ``Column`` ids parsed from the canonical SQL.
    """
    return """
MERGE (t:Task:Memory {id: $task_id})
ON CREATE SET t.created_at = datetime()
SET t.name = $name,
    t.type = 'task',
    t.observations = $observations

MERGE (p:Phrase {id: $phrase_id})
ON CREATE SET p.created_at = datetime()
SET p.verbatim = $question,
    p.embedding = $phrase_embedding
MERGE (t)-[:HAS_PHRASE]->(p)

MERGE (q:Query {id: $query_id})
ON CREATE SET q.query = $sql,
    q.description = $description

MERGE (t)-[r:HAS_QUERY]->(q)
SET r.captured_at = datetime()

WITH q
CALL (q) {
    UNWIND $table_ids AS tid
    MATCH (tb:Table {id: tid})
    MERGE (q)-[:USES_TABLE]->(tb)
    RETURN collect(tb.id) AS linked_tables
}
CALL (q) {
    UNWIND $column_ids AS cid
    MATCH (c:Column {id: cid})
    MERGE (q)-[:USES_COLUMN]->(c)
    RETURN collect(c.id) AS linked_columns
}
RETURN linked_tables, linked_columns
"""
