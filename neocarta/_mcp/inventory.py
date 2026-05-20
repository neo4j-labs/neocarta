"""Index and data inventory probes used to gate MCP tool registration."""

from neo4j import AsyncDriver, RoutingControl

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
