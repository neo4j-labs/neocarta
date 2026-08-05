"""Universal index functions independent of the source database."""

from neo4j import Driver, RoutingControl

from ..errors import ConfigError


def create_vector_index(
    neo4j_driver: Driver,
    node_label: str,
    dimensions: int = 768,
    database_name: str = "neo4j",
) -> dict:
    """
    Create a vector index according to the provided configuration.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_label: str
        The label of the node to create a vector index for. Any label whose nodes carry an
        ``embedding`` property (e.g. Database, Schema, Table, Column, BusinessTerm,
        GovernanceTagKey, or the OSI search labels).
    dimensions: int
        The dimensions of the vector index. Must be an integer greater than 0.
    database_name: str
        The name of the database to create a vector index for.

    Returns:
    -------
    dict
        The summary of the vector index created.
    """
    if dimensions <= 0:
        raise ConfigError("Dimensions must be an integer greater than 0")

    vector_index_query = f"""
CREATE VECTOR INDEX {node_label.lower() + "_vector_index"} IF NOT EXISTS
    FOR (n:{node_label})
    ON n.embedding
    OPTIONS {{
        indexConfig: {{
            `vector.dimensions`: {dimensions},
            `vector.similarity_function`: 'cosine'
        }}
    }}
"""
    _, summary, _ = neo4j_driver.execute_query(
        query_=vector_index_query,
        routing_=RoutingControl.WRITE,
        database_=database_name,
    )
    return summary.counters.__dict__


def create_full_text_index(
    neo4j_driver: Driver,
    node_labels: list[str],
    property_names: list[str] = ["name", "description"],
    database_name: str = "neo4j",
) -> dict:
    """
    Create a full text index according to the provided configuration.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_labels: list[str]
        The labels of the nodes to create a full text index for.
    property_names: list[str]
        The names of the properties to create a full text index for.
    database_name: str
        The name of the database to create a full text index for.
    """
    labels_lower_sorted = sorted([label.lower() for label in node_labels])
    query = f"""
CREATE FULLTEXT INDEX {"_".join(labels_lower_sorted) + "_full_text_index"} IF NOT EXISTS
    FOR (n:{"|".join(node_labels)})
    ON EACH [n.{" , n.".join(property_names)}]
    """

    _, summary, _ = neo4j_driver.execute_query(
        query_=query,
        routing_=RoutingControl.WRITE,
        database_=database_name,
    )
    return summary.counters.__dict__


def create_name_range_index(
    neo4j_driver: Driver,
    node_label: str,
    database_name: str = "neo4j",
    property_name: str = "name",
) -> dict:
    """
    Create a range index on a node's name-like property.

    A range index backs exact-equality ``MATCH (n:Label {prop: $value})`` lookups, such as the
    ones the MCP catalog queries issue. Vector and full-text indexes do not back equality
    matches, so a dedicated range index is required for these lookups to seek rather than scan.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_label: str
        The label of the node to create a range index for.
    database_name: str
        The name of the database to create the index in.
    property_name: str
        The property that holds the searchable name. Defaults to ``"name"``; pass ``"label"``
        for ``Node`` and ``"type"`` for ``Relationship`` (LPG), whose searchable name is not
        ``name``. The default keeps the generated index name (e.g. ``table_name_index``) and
        Cypher identical to before, so existing callers are unaffected.

    Returns:
    -------
    dict
        The summary of the index created.
    """
    name_index_query = f"""
CREATE INDEX {node_label.lower() + "_" + property_name.lower() + "_index"} IF NOT EXISTS
    FOR (n:{node_label})
    ON (n.{property_name})
"""
    _, summary, _ = neo4j_driver.execute_query(
        query_=name_index_query,
        routing_=RoutingControl.WRITE,
        database_=database_name,
    )
    return summary.counters.__dict__
