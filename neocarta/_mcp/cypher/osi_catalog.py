"""OSI catalog / listing cypher queries (domains, metrics-by-domain)."""


def list_domains_cypher() -> str:
    """
    Get the cypher query to list every OSI domain (semantic model) with size counts.

    Returns one row per ``:Domain`` node with its name, description, and the number of
    metrics, datasets (tables), columns, and joins it owns. The counts let an agent gauge
    how large a ``get_domain_context`` payload would be before requesting it.

    Returns:
    -------
    str
        Each row has ``domain_name``, ``domain_description``, ``num_metrics``,
        ``num_tables``, ``num_columns``, and ``num_joins``.
    """
    return """
MATCH (d:Domain)
RETURN
    d.name AS domain_name,
    d.description AS domain_description,
    COUNT { (d)-[:HAS_METRIC]->(:Metric) } AS num_metrics,
    COUNT { (d)-[:HAS_TABLE]->(:Table) } AS num_tables,
    COUNT { (d)-[:HAS_TABLE]->(:Table)-[:HAS_COLUMN]->(:Column) } AS num_columns,
    COUNT { MATCH (d)-[:HAS_TABLE]->(:Table)<-[:HAS_SOURCE_TABLE]-(j:Join) RETURN DISTINCT j } AS num_joins
ORDER BY domain_name
    """


def list_metrics_by_domain_cypher() -> str:
    """
    Get the cypher query to list the metrics owned by a domain.

    Notes:
    -----
    Expected Cypher parameters:

    domainId : str
        The ``:Domain`` node id (resolve from the domain name via
        ``generate_osi_semantic_model_id``).

    Returns:
    -------
    str
        Each row has ``metric_name``, ``metric_description``, and ``domain_name``.
    """
    return """
MATCH (d:Domain {id: $domainId})-[:HAS_METRIC]->(m:Metric)
RETURN m.name AS metric_name, m.description AS metric_description, d.name AS domain_name
ORDER BY metric_name
    """
