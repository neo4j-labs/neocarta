"""Utilities for generating and storing node descriptions in Neo4j."""

import logging
from collections.abc import Callable
from math import ceil
from typing import Any

import pandas as pd
from neo4j import Driver, RoutingControl

from ...enums import NodeLabel
from ...errors import ConfigError

logger = logging.getLogger(__name__)


def get_nodes_to_describe(
    neo4j_driver: Driver,
    node_label: NodeLabel,
    database_name: str = "neo4j",
) -> pd.DataFrame:
    """
    Get the nodes that are missing a description and need one generated.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_label: NodeLabel
        The label of the node to describe. Must be one of: Schema, Table, Column.
    database_name: str
        The name of the database to get nodes from.

    Returns:
    -------
    pd.DataFrame
        The nodes to describe.
        - id: The id of the node.
        - node_label: The label of the node.
        - name: The name of the node.
    """
    query = f"""
MATCH (n:{node_label})
WHERE n.description IS NULL OR size(n.description) = 0
RETURN n.id as id,
    labels(n)[0] as node_label,
    n.name as name
"""
    results = neo4j_driver.execute_query(
        query_=query,
        database_=database_name,
        routing_=RoutingControl.READ,
        result_transformer_=lambda x: x.data(),
    )

    return pd.DataFrame(results)


def get_node_context(
    neo4j_driver: Driver,
    node_id: str,
    node_label: NodeLabel,
    database_name: str = "neo4j",
    max_example_values: int = 5,
) -> dict[str, Any]:
    """
    Fetch immediate-neighbor context (and example values, for Columns) for a node.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_id: str
        The id of the node to fetch context for.
    node_label: NodeLabel
        The label of the node. Must be one of: Schema, Table, Column.
    database_name: str
        The name of the database to query.
    max_example_values: int
        The maximum number of example Value nodes to fetch for a Column.

    Returns:
    -------
    dict[str, Any]
        Context for the node, shape depends on node_label:
        - Schema: {"database_name": str | None, "table_names": list[str]}
        - Table: {"schema_name": str | None, "column_names": list[str]}
        - Column: {
              "table_name": str | None,
              "sibling_column_names": list[str],
              "column_type": str | None,
              "example_values": list[str],
          }
    """
    if node_label == NodeLabel.SCHEMA:
        query = """
MATCH (n:Schema {id: $node_id})
OPTIONAL MATCH (db:Database)-[:HAS_SCHEMA]->(n)
OPTIONAL MATCH (n)-[:HAS_TABLE]->(t:Table)
RETURN db.name as database_name, collect(DISTINCT t.name) as table_names
"""
    elif node_label == NodeLabel.TABLE:
        query = """
MATCH (n:Table {id: $node_id})
OPTIONAL MATCH (s:Schema)-[:HAS_TABLE]->(n)
OPTIONAL MATCH (n)-[:HAS_COLUMN]->(c:Column)
RETURN s.name as schema_name, collect(DISTINCT c.name) as column_names
"""
    elif node_label == NodeLabel.COLUMN:
        query = """
MATCH (n:Column {id: $node_id})
OPTIONAL MATCH (t:Table)-[:HAS_COLUMN]->(n)
OPTIONAL MATCH (t)-[:HAS_COLUMN]->(sibling:Column)
WHERE sibling.id <> n.id
OPTIONAL MATCH (n)-[:HAS_VALUE]->(v:Value)
WITH n, t, collect(DISTINCT sibling.name) as sibling_column_names,
    collect(DISTINCT v.value)[0..$max_example_values] as example_values
RETURN t.name as table_name, sibling_column_names, n.type as column_type, example_values
"""
    else:
        raise ConfigError(
            f"get_node_context does not support node_label '{node_label}'. "
            "Must be one of: Schema, Table, Column."
        )

    results = neo4j_driver.execute_query(
        query_=query,
        parameters_={"node_id": node_id, "max_example_values": max_example_values},
        database_=database_name,
        routing_=RoutingControl.READ,
        result_transformer_=lambda x: x.data(),
    )

    return results[0] if results else {}


def _generate_descriptions_for_batch_sync(
    description_fn: Callable[[list[dict[str, Any]]], list[str | None]], batch: pd.DataFrame
) -> list[tuple[str, str]]:
    """
    Generate descriptions for a batch of nodes (sync version).

    Parameters
    ----------
    description_fn: Callable
        The description function to use. Must take in a list of context dicts
        (one per node, each with at minimum a "name" and "node_label" key) and
        return a list of descriptions, one per node in input order (None for
        any that failed).
    batch : pd.DataFrame
        A Pandas DataFrame where each row represents a node to describe.
        Has columns `id`, `node_label`, `name`, and `context`.

    Returns:
    -------
    list[tuple[str, str]]
        A list of (node id, generated description) tuples for nodes that
        succeeded.
    """
    contexts = batch.to_dict(orient="records")
    descriptions = description_fn(contexts)
    return [
        (node_id, description)
        for node_id, description in zip(batch["id"], descriptions, strict=False)
        if description is not None
    ]


async def _generate_descriptions_for_batch_async(
    description_fn: Callable[[list[dict[str, Any]]], Any], batch: pd.DataFrame
) -> list[tuple[str, str]]:
    """Async variant of :func:`_generate_descriptions_for_batch_sync`."""
    contexts = batch.to_dict(orient="records")
    descriptions = await description_fn(contexts)
    return [
        (node_id, description)
        for node_id, description in zip(batch["id"], descriptions, strict=False)
        if description is not None
    ]


def generate_descriptions_in_batches_sync(
    description_fn: Callable[[list[dict[str, Any]]], list[str | None]],
    nodes_dataframe: pd.DataFrame,
    batch_size: int,
) -> list[tuple[str, str]]:
    """
    Generate descriptions for a Pandas DataFrame of nodes in batches (sync version).

    Parameters
    ----------
    description_fn: Callable
        The description function to use.
    nodes_dataframe : pd.DataFrame
        A Pandas DataFrame where each row represents a node.
        Has columns `id`, `node_label`, `name`, and `context`.
    batch_size : int
        The number of nodes to process in each batch.

    Returns:
    -------
    list[tuple[str, str]]
        A list of (node id, generated description) tuples.
    """
    results = []

    for batch_idx, i in enumerate(range(0, len(nodes_dataframe), batch_size)):
        logger.debug(
            "Generating descriptions for batch %d/%d",
            batch_idx + 1,
            ceil(len(nodes_dataframe) / batch_size),
        )
        if i + batch_size >= len(nodes_dataframe):
            batch = nodes_dataframe.iloc[i:]
        else:
            batch = nodes_dataframe.iloc[i : i + batch_size]
        batch_results = _generate_descriptions_for_batch_sync(description_fn, batch)
        results.extend(batch_results)

    return results


async def generate_descriptions_in_batches_async(
    description_fn: Callable[[list[dict[str, Any]]], list[str | None]],
    nodes_dataframe: pd.DataFrame,
    batch_size: int,
) -> list[tuple[str, str]]:
    """Async variant of :func:`generate_descriptions_in_batches_sync`."""
    results = []

    for batch_idx, i in enumerate(range(0, len(nodes_dataframe), batch_size)):
        logger.debug(
            "Generating descriptions for batch %d/%d",
            batch_idx + 1,
            ceil(len(nodes_dataframe) / batch_size),
        )
        if i + batch_size >= len(nodes_dataframe):
            batch = nodes_dataframe.iloc[i:]
        else:
            batch = nodes_dataframe.iloc[i : i + batch_size]
        batch_results = await _generate_descriptions_for_batch_async(description_fn, batch)
        results.extend(batch_results)

    return results


def write_descriptions_to_graph(
    descriptions_df: pd.DataFrame,
    node_label: NodeLabel,
    neo4j_driver: Driver,
    database_name: str = "neo4j",
) -> int:
    """
    Write generated descriptions to Neo4j graph for a given node label.

    Parameters
    ----------
    descriptions_df : pd.DataFrame
        A Pandas DataFrame where each row represents a node.
        Has columns `id` and `description`.
    node_label: NodeLabel
        The label of the node to write descriptions to. Must be one of: Schema, Table, Column.
    neo4j_driver: Driver
        The Neo4j driver to use.
    database_name: str
        The name of the database to write descriptions to.

    Returns:
    -------
    int
        The number of descriptions written.
    """
    query = f"""
    UNWIND $rows as row
    MATCH (n:{node_label} {{id: row.id}})
    SET n.description = row.description
    """

    neo4j_driver.execute_query(
        query_=query,
        parameters_={"rows": descriptions_df.to_dict(orient="records")},
        database_=database_name,
        routing_=RoutingControl.WRITE,
    )

    written = len(descriptions_df)
    logger.info("Wrote %d descriptions to (:%s)", written, node_label)
    return written
