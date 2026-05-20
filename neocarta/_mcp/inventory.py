"""Index and data inventory probes used to gate MCP tool registration."""

from neo4j import AsyncDriver, RoutingControl

from ..data_model.metadata import NeocartaGraph
from ..ingest.metadata import FETCH_NEOCARTA_GRAPH_CYPHER
from .cypher import list_search_indexes_cypher


async def fetch_index_inventory(
    neo4j_driver: AsyncDriver, neo4j_database: str
) -> set[tuple[str, str]]:
    """
    Return the set of ``(label, index_type)`` pairs for indexes present in the database.

    Only node-scoped VECTOR and FULLTEXT indexes are considered. A FULLTEXT index spanning
    multiple labels contributes one tuple per label.

    Parameters
    ----------
    neo4j_driver: AsyncDriver
        The Neo4j async driver used to query the database.
    neo4j_database: str
        The target database name.

    Returns:
    -------
    set[tuple[str, str]]
        Pairs like ``("Table", "VECTOR")`` or ``("BusinessTerm", "FULLTEXT")``.
    """
    records = await neo4j_driver.execute_query(
        query_=list_search_indexes_cypher(),
        database_=neo4j_database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda x: x.data(),
    )
    return {(record["labelsOrTypes"][0], record["type"]) for record in records}


async def has_business_term_nodes(neo4j_driver: AsyncDriver, neo4j_database: str) -> bool:
    """
    Return ``True`` if at least one ``:BusinessTerm`` node exists in the database.

    Parameters
    ----------
    neo4j_driver: AsyncDriver
        The Neo4j async driver used to query the database.
    neo4j_database: str
        The target database name.
    """
    cypher = "MATCH (b:BusinessTerm) RETURN count(b) > 0 AS present"
    records = await neo4j_driver.execute_query(
        query_=cypher,
        database_=neo4j_database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda x: x.data(),
    )
    return bool(records and records[0].get("present"))


async def fetch_neocarta_graph_metadata(
    neo4j_driver: AsyncDriver, neo4j_database: str
) -> NeocartaGraph | None:
    """
    Read the singleton ``__neocarta_graph__`` metadata node, if present.

    Parameters
    ----------
    neo4j_driver: AsyncDriver
        The Neo4j async driver used to query the database.
    neo4j_database: str
        The target database name.

    Returns:
    -------
    NeocartaGraph or None
        The metadata node, or ``None`` if no metadata node has been written
        to the graph yet (e.g. when the MCP server is pointed at a graph
        that pre-dates this feature or was not loaded via a neocarta
        connector).
    """
    records = await neo4j_driver.execute_query(
        query_=FETCH_NEOCARTA_GRAPH_CYPHER,
        database_=neo4j_database,
        routing_=RoutingControl.READ,
        result_transformer_=lambda x: x.data(),
    )
    if not records:
        return None
    record = records[0]
    return NeocartaGraph(
        initial_version=record["initial_version"],
        latest_version=record["latest_version"],
        create_date=record["create_date"].to_native(),
        last_updated=record["last_updated"].to_native(),
    )
