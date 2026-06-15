"""OSI definition-gathering cypher (metric expressions, entity aspects)."""

#: Aspect projection shared by the get_aspects queries. Expects an ``:Aspect`` bound as ``a``.
_ASPECT_RESULT = """
RETURN {
    aspect_type: CASE
        WHEN a:OsiAiContext THEN "ai_context"
        WHEN a:OsiCustomExtensions THEN "custom_extensions"
        ELSE "unknown"
    END,
    data: a.data,
    vendor_name: a.vendor_name
} AS result
"""

#: Entity types addressable by id (resolvable via generate_id helpers in the tool layer).
_ID_ADDRESSED_ENTITIES = frozenset({"domain", "metric", "join"})

#: Entity types addressed by name, scoped to a domain subgraph.
_NAME_ADDRESSED_ENTITIES = frozenset({"table", "column"})


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


def get_aspects_cypher(entity_type: str) -> str:
    """
    Get the cypher query returning the aspects attached to an OSI entity.

    ``domain`` / ``metric`` / ``join`` entities are matched by their resolved id
    (``$entityId``); ``table`` / ``column`` entities are matched by name (``$entityName``)
    scoped to a domain (``$domainId``), since their ids require database/schema components
    not available from a name alone.

    Parameters
    ----------
    entity_type : str
        One of ``domain``, ``metric``, ``join``, ``table``, ``column``.

    Notes:
    -----
    Expected Cypher parameters: ``entityId`` (id-addressed types), or ``entityName`` and
    ``domainId`` (name-addressed types).

    Returns:
    -------
    str
        Each row has a ``result`` map matching the ``AspectContext`` model.
    """
    if entity_type in _ID_ADDRESSED_ENTITIES:
        return f"""
MATCH (n {{id: $entityId}})
MATCH (n)-[:HAS_ASPECT]->(a:Aspect)
{_ASPECT_RESULT}
"""
    if entity_type == "table":
        return f"""
MATCH (:Domain {{id: $domainId}})-[:HAS_TABLE]->(t:Table {{name: $entityName}})
MATCH (t)-[:HAS_ASPECT]->(a:Aspect)
{_ASPECT_RESULT}
"""
    if entity_type == "column":
        return f"""
MATCH (:Domain {{id: $domainId}})-[:HAS_TABLE]->(:Table)-[:HAS_COLUMN]->(c:Column {{name: $entityName}})
MATCH (c)-[:HAS_ASPECT]->(a:Aspect)
{_ASPECT_RESULT}
"""
    raise ValueError(
        f"Unsupported entity_type {entity_type!r}; expected one of "
        f"{sorted(_ID_ADDRESSED_ENTITIES | _NAME_ADDRESSED_ENTITIES)}"
    )
