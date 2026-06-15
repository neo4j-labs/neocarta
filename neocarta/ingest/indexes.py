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
        The label of the node to create a vector index for. Must be one of: Database, Schema, Table, Column.
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


def create_range_index(
    neo4j_driver: Driver,
    node_label: str,
    property_name: str,
    database_name: str = "neo4j",
) -> dict:
    """
    Create a range index on an arbitrary node property.

    A range index backs exact-equality and range ``MATCH``/``WHERE`` predicates so they seek
    rather than scan (vector and full-text indexes do not back equality matches).

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_label: str
        The label of the node to index. Its nodes must carry ``property_name``.
    property_name: str
        The property to index.
    database_name: str
        The name of the database to create the index in.

    Returns:
    -------
    dict
        The summary of the index created.
    """
    index_query = f"""
CREATE INDEX {node_label.lower()}_{property_name.lower()}_index IF NOT EXISTS
    FOR (n:{node_label})
    ON (n.{property_name})
"""
    _, summary, _ = neo4j_driver.execute_query(
        query_=index_query,
        routing_=RoutingControl.WRITE,
        database_=database_name,
    )
    return summary.counters.__dict__


def create_name_range_index(
    neo4j_driver: Driver,
    node_label: str,
    database_name: str = "neo4j",
) -> dict:
    """
    Create a range index on a node's ``name`` property.

    Thin wrapper over :func:`create_range_index` for the common ``name`` case, which backs the
    exact-equality ``MATCH (n:Label {name: $value})`` lookups the MCP catalog queries issue.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_label: str
        The label of the node to create a name range index for. Must be a label whose nodes
        carry a ``name`` property.
    database_name: str
        The name of the database to create the index in.

    Returns:
    -------
    dict
        The summary of the index created.
    """
    return create_range_index(neo4j_driver, node_label, "name", database_name)
