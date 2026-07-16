"""OSI definition-gathering cypher (metric expressions)."""


def get_metric_expression_cypher() -> str:
    """
    Get the cypher query returning the dialect-specific expression(s) for a metric.

    Notes:
    -----
    Expected Cypher parameters:

    metricId : str | None
        The resolved ``:Metric`` id when a ``domain_name`` was supplied (via
        ``generate_metric_id``); ``None`` to match the metric by name across all domains.
    metricName : str
        The metric name, used when ``metricId`` is ``None``.
    dialect : str | None
        When set, restrict to expressions of that SQL dialect.

    Returns:
    -------
    str
        Each row has ``dialect`` and ``expression``.
    """
    return """
MATCH (m:Metric)
WHERE ($metricId IS NULL OR m.id = $metricId)
  AND ($metricId IS NOT NULL OR m.name = $metricName)
MATCH (m)-[:HAS_EXPRESSION]->(e:Expression)
WHERE $dialect IS NULL OR e.dialect = $dialect
RETURN DISTINCT e.dialect AS dialect, e.expression AS expression
ORDER BY dialect
    """


# NOTE: aspect retrieval is intentionally not a standalone tool/query. Aspects are embedded
# in the context payloads instead — DomainContext (domain/table/column/metric/join via
# get_domain_context_cypher), MetricContext (metric search), and the table/column search hits
# — so there is no separate get_aspects cypher.
