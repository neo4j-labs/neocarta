"""Universal index functions independent of the source database."""

from neo4j import Driver, RoutingControl

from ..enums import NodeLabel
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
) -> dict:
    """
    Create a range index on a node's ``name`` property.

    A range index backs exact-equality ``MATCH (n:Label {name: $value})`` lookups, such as the
    ones the MCP catalog queries issue. Vector and full-text indexes do not back equality
    matches, so a dedicated range index is required for these lookups to seek rather than scan.

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
    name_index_query = f"""
CREATE INDEX {node_label.lower() + "_name_index"} IF NOT EXISTS
    FOR (n:{node_label})
    ON (n.name)
"""
    _, summary, _ = neo4j_driver.execute_query(
        query_=name_index_query,
        routing_=RoutingControl.WRITE,
        database_=database_name,
    )
    return summary.counters.__dict__


def create_memory_indexes(
    neo4j_driver: Driver,
    dimensions: int,
    database_name: str = "neo4j",
) -> dict:
    """
    Create the vector + full-text indexes backing the semantic-memory tools.

    The recall tool searches ``Phrase`` nodes via ``phrase_vector_index`` over
    their embeddings and ``phrase_full_text_index`` over their ``verbatim`` text,
    then rolls the hits up to the owning ``Task``. Run once per graph (see
    ``neocarta memory init-indexes``) before recall is used; capture writes the
    Phrase nodes and their embeddings regardless of whether these indexes exist
    yet, and a vector index built afterwards backfills over the existing nodes.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    dimensions: int
        The embedding dimension the Phrase vectors are stored at. Must match the
        embedder the MCP server uses, or vector recall will error at query time.
    database_name: str
        The name of the database to create the indexes in.

    Returns:
    -------
    dict
        The per-index creation summaries, keyed by index name.
    """
    return {
        "phrase_vector_index": create_vector_index(
            neo4j_driver,
            NodeLabel.PHRASE,
            dimensions=dimensions,
            database_name=database_name,
        ),
        "phrase_full_text_index": create_full_text_index(
            neo4j_driver,
            [NodeLabel.PHRASE],
            property_names=["verbatim"],
            database_name=database_name,
        ),
    }
