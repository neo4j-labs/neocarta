"""Ingest helpers for the Neocarta graph metadata node."""

from neo4j import Driver, RoutingControl

from .. import __version__
from ..data_model.metadata import NeocartaGraph
from ..enums import NodeLabel

UPSERT_NEOCARTA_GRAPH_CYPHER = f"""
MERGE (n:`{NodeLabel.NEOCARTA_GRAPH}`)
ON CREATE SET
    n.initial_version = $version,
    n.latest_version = $version,
    n.create_date = datetime(),
    n.last_updated = datetime()
ON MATCH SET
    n.latest_version = $version,
    n.last_updated = datetime()
RETURN n.initial_version AS initial_version,
       n.latest_version AS latest_version,
       n.create_date AS create_date,
       n.last_updated AS last_updated
"""

FETCH_NEOCARTA_GRAPH_CYPHER = f"""
MATCH (n:`{NodeLabel.NEOCARTA_GRAPH}`)
RETURN n.initial_version AS initial_version,
       n.latest_version AS latest_version,
       n.create_date AS create_date,
       n.last_updated AS last_updated
"""


def upsert_neocarta_graph_node(
    neo4j_driver: Driver,
    database_name: str = "neo4j",
    version: str | None = None,
) -> NeocartaGraph:
    """
    Create or update the singleton ``__neocarta_graph__`` metadata node.

    On creation the node's ``initial_version`` and ``create_date`` are stamped
    with the calling library version and the current time; on subsequent runs
    only ``latest_version`` and ``last_updated`` are refreshed.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver used to write to the graph.
    database_name: str
        The name of the target Neo4j database.
    version: str, optional
        The neocarta version to record. Defaults to the installed
        ``neocarta`` package version.

    Returns:
    -------
    NeocartaGraph
        The current state of the metadata node after the upsert.
    """
    records, _, _ = neo4j_driver.execute_query(
        query_=UPSERT_NEOCARTA_GRAPH_CYPHER,
        parameters_={"version": version or __version__},
        routing_=RoutingControl.WRITE,
        database_=database_name,
    )
    record = records[0]
    return NeocartaGraph(
        initial_version=record["initial_version"],
        latest_version=record["latest_version"],
        create_date=record["create_date"].to_native(),
        last_updated=record["last_updated"].to_native(),
    )
