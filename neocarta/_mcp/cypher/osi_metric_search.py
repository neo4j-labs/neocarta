"""Metric-anchored OSI search cypher (vector / full-text / hybrid / business-term hybrid).

Each query anchors on ``:Metric`` nodes and projects a ``MetricContext`` payload. An
optional ``$domainId`` parameter scopes the search to a single semantic model when set
(pass ``None`` to search across all domains). The shared projection tail
(:data:`_METRIC_CONTEXT_TAIL`) takes ``metric`` and ``score`` from scope and returns the
metric with its owning domain, dialect-specific expressions, business-term synonyms, and
aspects.
"""

#: Optional domain scoping predicate. ``$domainId`` is ``None`` for an unscoped search.
_DOMAIN_FILTER = (
    "($domainId IS NULL OR EXISTS { (:Domain {id: $domainId})-[:HAS_METRIC]->(metric) })"
)

#: Projection shared by every metric search strategy. Expects ``metric`` and ``score``.
_METRIC_CONTEXT_TAIL = """
MATCH (owner:Domain)-[:HAS_METRIC]->(metric)
RETURN {
    metric_name: metric.name,
    metric_description: metric.description,
    domain_name: owner.name,
    expressions: COLLECT {
        MATCH (metric)-[:HAS_EXPRESSION]->(e:Expression)
        RETURN {dialect: e.dialect, expression: e.expression}
    },
    synonyms: COLLECT {
        MATCH (metric)-[:TAGGED_WITH]->(bt:BusinessTerm)
        RETURN bt.name
    },
    aspects: COLLECT {
        MATCH (metric)-[:HAS_ASPECT]->(a:Aspect)
        RETURN {
            aspect_type: CASE
                WHEN a:OsiAiContext THEN "ai_context"
                WHEN a:OsiCustomExtensions THEN "custom_extensions"
                ELSE "unknown"
            END,
            data: a.data,
            vendor_name: a.vendor_name
        }
    },
    metric_score: score
} AS result
ORDER BY score DESC
LIMIT $maxMetrics
"""


def get_context_by_metric_vector_search_cypher() -> str:
    """Get the cypher query to find metrics by embedding similarity to the query.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding to compare against ``metric_vector_index``.
    searchTopK : int
        Number of metric candidates to fetch from the vector index.
    maxMetrics : int
        Maximum number of metrics to return.
    domainId : str | None
        When set, restrict results to metrics owned by that domain.

    Uses the ``metric_vector_index`` index (library convention).
    """
    return f"""
CALL db.index.vector.queryNodes('metric_vector_index', $searchTopK, $queryEmbedding)
YIELD node AS metric, score
WHERE score > 0.5 AND {_DOMAIN_FILTER}
WITH metric, score
{_METRIC_CONTEXT_TAIL}
"""


def get_context_by_metric_full_text_search_cypher() -> str:
    """Get the cypher query to find metrics by full-text matching on name and description.

    Notes:
    -----
    Expected Cypher parameters:

    queryText : str
        Lucene query for ``metric_full_text_index``.
    searchTopK : int
        Number of metric candidates to fetch from the full-text index.
    maxMetrics : int
        Maximum number of metrics to return.
    domainId : str | None
        When set, restrict results to metrics owned by that domain.

    Uses the ``metric_full_text_index`` index (library convention).
    """
    return f"""
CALL db.index.fulltext.queryNodes('metric_full_text_index', $queryText, {{limit: $searchTopK}})
YIELD node AS metric, score
WHERE {_DOMAIN_FILTER}
WITH metric, score
{_METRIC_CONTEXT_TAIL}
"""


def get_context_by_metric_hybrid_search_cypher() -> str:
    """Get the cypher query to find metrics via hybrid vector + full-text search.

    Combines a vector search over ``metric_vector_index`` with a full-text search over
    ``metric_full_text_index``. Scores from each branch are min-max normalized by the
    branch's own maximum score and merged by taking the maximum across branches per metric.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding for the vector branch.
    queryText : str
        Lucene query for the full-text branch.
    searchTopK : int
        Number of metric candidates to fetch from each branch's index.
    maxMetrics : int
        Maximum number of metrics to return.
    domainId : str | None
        When set, restrict results to metrics owned by that domain.
    """
    return f"""
CALL () {{
  // vector search metrics
  CALL db.index.vector.queryNodes('metric_vector_index', $searchTopK, $queryEmbedding)
  YIELD node AS metric, score AS metricScore
  WHERE metricScore > 0.5

  WITH collect({{node:metric, score:metricScore}}) AS nodes, max(metricScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search metrics
  CALL db.index.fulltext.queryNodes('metric_full_text_index', $queryText, {{limit: $searchTopK}})
  YIELD node AS metric, score AS metricScore

  WITH collect({{node:metric, score:metricScore}}) AS nodes, max(metricScore) AS ft_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / ft_index_max_score) AS score
}}
WITH node AS metric, max(score) AS score
WHERE {_DOMAIN_FILTER}
{_METRIC_CONTEXT_TAIL}
"""


def get_context_by_metric_business_term_hybrid_search_cypher() -> str:
    """Get the cypher query to find metrics via hybrid vector + business-term-bridged full-text search.

    The full-text branch finds BusinessTerm nodes matching the query, then finds Metric
    nodes that (a) also match the query in ``metric_full_text_index`` AND (b) are
    TAGGED_WITH one of those BusinessTerm nodes. For each (metric, bt) pair the full-text
    branch score is ``(metricScore/maxMetricScore + btScore/maxBtScore) / 2`` — each
    component min-max normalized by its own branch maximum and averaged so the result is in
    [0,1] and directly comparable to the vector branch's normalized score. Combined with a
    vector search on ``metric_vector_index`` via per-branch normalization and max-merge per
    metric.

    Notes:
    -----
    Expected Cypher parameters:

    queryEmbedding : list[float]
        Embedding for the vector branch.
    queryText : str
        Lucene query for both full-text branches (business term + metric).
    searchTopK : int
        Number of candidates to fetch from each index call (vector + both full-text).
    maxMetrics : int
        Maximum number of metrics to return.
    domainId : str | None
        When set, restrict results to metrics owned by that domain.
    """
    return f"""
CALL () {{
  // vector search metrics
  CALL db.index.vector.queryNodes('metric_vector_index', $searchTopK, $queryEmbedding)
  YIELD node AS metric, score AS metricScore
  WHERE metricScore > 0.5

  WITH collect({{node:metric, score:metricScore}}) AS nodes, max(metricScore) AS vector_index_max_score
  UNWIND nodes AS n
  RETURN n.node AS node, (n.score / vector_index_max_score) AS score

  UNION

  // full-text search business terms, then bridge to metrics tagged with those terms.
  CALL db.index.fulltext.queryNodes('businessterm_full_text_index', $queryText, {{limit: $searchTopK}})
  YIELD node AS bt, score AS btScore
  WITH bt, btScore
  CALL db.index.fulltext.queryNodes('metric_full_text_index', $queryText, {{limit: $searchTopK}})
  YIELD node AS metric, score AS metricScore
  WHERE EXISTS {{(bt:BusinessTerm)<-[:TAGGED_WITH]-(metric:Metric)}}
  WITH collect({{
            node:metric,
            metricScore:metricScore,
            businessTerm:bt,
            btScore:btScore}}) AS nodes,
        max(metricScore) AS ft_metric_max_score,
        max(btScore) AS ft_bt_max_score
  UNWIND nodes AS n
  RETURN n.node AS node,
         ((n.metricScore / ft_metric_max_score) + (n.btScore / ft_bt_max_score)) / 2.0 AS score
}}
WITH node AS metric, max(score) AS score
WHERE {_DOMAIN_FILTER}
{_METRIC_CONTEXT_TAIL}
"""
