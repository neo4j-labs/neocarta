"""Cypher for the ``recall_task_memory`` tool.

Recall is a hybrid search over ``Phrase`` nodes rolled up to their ``Task``:
a vector branch and a full-text branch each search phrasings and max-pool to
the owning Task, and the tool fuses the two branches in Python. A third getter
expands a chosen Task to its latest canonical ``Query`` and the tables/columns
that query uses.
"""


def recall_task_memory_vector_cypher() -> str:
    """Vector branch: search phrasings, roll up to their Task by max-pool.

    Searches the ``phrase_vector_index`` and keeps only phrasings scoring at or
    above ``$vectorFloor`` (a pre-normalization relevance floor), then max-pools
    to the owning Task, carrying the best-matching phrasing alongside the max
    score.

    Notes:
    -----
    Expected Cypher parameters:

    embedding : list[float]
        Query embedding compared against ``phrase_vector_index``.
    topK : int
        Number of phrase candidates to fetch from the vector index.
    vectorFloor : float
        Minimum cosine a phrasing must score to survive the roll-up.
    """
    return """
CALL db.index.vector.queryNodes('phrase_vector_index', $topK, $embedding)
YIELD node AS p, score
WHERE score >= $vectorFloor
MATCH (t:Task)-[:HAS_PHRASE]->(p)
WITH t, score, p.verbatim AS verbatim ORDER BY score DESC
WITH t, collect(verbatim)[0] AS matched_phrase, max(score) AS score
RETURN elementId(t) AS eid, score, matched_phrase
ORDER BY score DESC
"""


def recall_task_memory_fulltext_cypher() -> str:
    """Full-text branch: same Phrase -> Task max-pool roll-up.

    Searches the ``phrase_full_text_index`` and max-pools the Lucene scores to
    the owning Task.

    Notes:
    -----
    Expected Cypher parameters:

    queryText : str
        Lucene query (already sanitised with ``remove_lucene_chars``).
    topK : int
        Number of phrase candidates to fetch from the full-text index.
    """
    return """
CALL db.index.fulltext.queryNodes('phrase_full_text_index', $queryText, {limit: $topK})
YIELD node AS p, score
MATCH (t:Task)-[:HAS_PHRASE]->(p)
WITH t, max(score) AS score
RETURN elementId(t) AS eid, score
ORDER BY score DESC
"""


def phrase_vector_index_dimension_cypher() -> str:
    """Return the configured vector dimension of ``phrase_vector_index``.

    Used only on the recall anomaly path (the vector branch produced nothing) to
    diagnose an embedding-dimension mismatch: this index dimension is compared
    against the length of the query embedding. Yields no rows if the index is
    absent.

    Notes:
    -----
    Expected Cypher parameters: none.
    """
    return """
SHOW INDEXES YIELD name, type, options
WHERE name = 'phrase_vector_index' AND type = 'VECTOR'
RETURN options.indexConfig.`vector.dimensions` AS index_dim
"""


def recall_task_memory_expand_cypher() -> str:
    """Expand one ranked Task to its phrasings, observations and canonical Query.

    Picks the most recently captured ``Query`` (by ``captured_at`` on the
    ``HAS_QUERY`` relationship) and returns the Task's phrasings and accumulated
    ``observations`` plus the tables/columns that query uses. The observations
    are the analytical notes capture recorded (chosen metric definition, join
    path, weighting) — the calling agent needs them to judge whether the stored
    SQL answers *this* question, not just a similarly worded one.

    Notes:
    -----
    Expected Cypher parameters:

    eid : str
        ``elementId`` of the Task to expand (from a search branch).
    """
    return """
MATCH (t:Task) WHERE elementId(t) = $eid
MATCH (t)-[r:HAS_QUERY]->(q:Query)
WITH t, q, r ORDER BY r.captured_at DESC
WITH t, collect(q)[0] AS q
RETURN t.name AS task_name,
       coalesce(t.observations, []) AS observations,
       [(t)-[:HAS_PHRASE]->(p) | p.verbatim] AS phrasings,
       q.description AS query_description,
       q.query AS sql,
       COLLECT { MATCH (q)-[:USES_TABLE]->(tb:Table)  RETURN DISTINCT tb.id } AS tables,
       COLLECT { MATCH (q)-[:USES_COLUMN]->(c:Column) RETURN DISTINCT c.id }  AS columns
"""
