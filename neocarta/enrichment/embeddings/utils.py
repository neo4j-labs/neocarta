"""Utilities for computing and storing node embeddings in Neo4j."""

import logging
from collections.abc import Callable
from math import ceil
from typing import Any

import pandas as pd
from neo4j import Driver, RoutingControl

from ...enums import NodeLabel
from ...errors import ConfigError

logger = logging.getLogger(__name__)


def get_nodes_to_embed(
    neo4j_driver: Driver,
    node_label: NodeLabel,
    min_length: int = 20,
    database_name: str = "neo4j",
) -> pd.DataFrame:
    """
    Get the nodes to embed.

    Parameters
    ----------
    neo4j_driver: Driver
        The Neo4j driver to use.
    node_label: str
        The label of the node to embed. Any label whose nodes carry a ``description`` property
        (e.g. Database, Schema, Table, Column, BusinessTerm, GovernanceTagKey, or the OSI labels).
    min_length: int
        The minimum length of the description to embed. Must be greater than 0.
    database_name: str
        The name of the database to get nodes from.

    Returns:
    -------
    pd.DataFrame
        The nodes to embed.
        - id: The id of the node.
        - node_label: The label of the node.
        - description: The description of the node.
    """
    if min_length <= 0:
        raise ConfigError("Minimum length must be greater than 0")

    query = f"""
MATCH (n:{node_label})
WHERE n.description IS NOT NULL
    AND n.embedding IS NULL
    AND size(n.description) > 0
RETURN n.id as id,
    labels(n)[0] as node_label,
    n.description as description
"""
    results = neo4j_driver.execute_query(
        query_=query,
        parameters_={"min_length": min_length},
        database_=database_name,
        routing_=RoutingControl.READ,
        result_transformer_=lambda x: x.data(),
    )

    return pd.DataFrame(results)


def _create_embeddings_for_batch_sync(
    embedding_fn: Callable[[list[str]], list[list[float] | None]], batch: pd.DataFrame
) -> list[tuple[str, list[float]]]:
    """
    Create embeddings for a batch of node descriptions to embed (sync version).

    Parameters
    ----------
    embedding_fn: Callable
        The embedding function to use. Must take in a list of node descriptions and return a list of embeddings, one per description in input order (None for any that failed).
    batch : pd.DataFrame
        A Pandas DataFrame where each row represents a node to embed.
        Has columns `id`, `node_label`, and `description`.

    Returns:
    -------
    list[tuple[str, list[float]]]
        A list of tuples, where the first element is the node id and the second element is the embedding for the node description.
    """
    embeddings = embedding_fn(batch["description"].tolist())
    return [
        (node_id, embedding)
        for node_id, embedding in zip(batch["id"], embeddings, strict=False)
        if embedding is not None
    ]


async def _create_embeddings_for_batch_async(
    embedding_fn: Callable[[list[str]], Any], batch: pd.DataFrame
) -> list[tuple[str, list[float]]]:
    """
    Create embeddings for a batch of node descriptions to embed (async version).

    Parameters
    ----------
    embedding_fn: Callable
        The embedding function to use. Must take in a list of node descriptions and return a list of embeddings, one per description in input order (None for any that failed).
    batch : pd.DataFrame
        A Pandas DataFrame where each row represents a node to embed.
        Has columns `id`, `node_label`, and `description`.

    Returns:
    -------
    list[tuple[str, list[float]]]
        A list of tuples, where the first element is the node id and the second element is the embedding for the node description.
    """
    embeddings = await embedding_fn(batch["description"].tolist())
    return [
        (node_id, embedding)
        for node_id, embedding in zip(batch["id"], embeddings, strict=False)
        if embedding is not None
    ]


def create_embeddings_in_batches_sync(
    embedding_fn: Callable[[list[str]], list[list[float] | None]],
    nodes_dataframe: pd.DataFrame,
    batch_size: int,
) -> list[tuple[str, list[Any]]]:
    """
    Create embeddings for a Pandas DataFrame of text chunks in batches (sync version).

    Parameters
    ----------
    embedding_fn: Callable[[list[str]], list[list[float] | None]]
        The embedding function to use. Must take in a list of node descriptions and return a list of embeddings, one per description in input order (None for any that failed).
    nodes_dataframe : pd.DataFrame
        A Pandas DataFrame where each row represents a node.
        Has columns `id`, `node_label`, and `description`.
    batch_size : int
        The number of nodes to process in each batch.

    Returns:
    -------
    list[tuple[str, list[Any]]]
        A list of tuples, where the first element is the node id and the second element is the embedding for the node description.
    """
    results = []

    for batch_idx, i in enumerate(range(0, len(nodes_dataframe), batch_size)):
        logger.debug(
            "Embedding batch %d/%d",
            batch_idx + 1,
            ceil(len(nodes_dataframe) / batch_size),
        )
        if i + batch_size >= len(nodes_dataframe):
            batch = nodes_dataframe.iloc[i:]
        else:
            batch = nodes_dataframe.iloc[i : i + batch_size]
        batch_results = _create_embeddings_for_batch_sync(embedding_fn, batch)

        # Add extracted records to the results list
        results.extend(batch_results)

    return results


async def create_embeddings_in_batches_async(
    embedding_fn: Callable[[list[str]], list[list[float] | None]],
    nodes_dataframe: pd.DataFrame,
    batch_size: int,
) -> list[tuple[str, list[Any]]]:
    """
    Create embeddings for a Pandas DataFrame of text chunks in batches.

    Parameters
    ----------
    embedding_fn: Callable[[list[str]], list[list[float] | None]]
        The embedding function to use. Must take in a list of node descriptions and return a list of embeddings, one per description in input order (None for any that failed).
    nodes_dataframe : pd.DataFrame
        A Pandas DataFrame where each row represents a node.
        Has columns `id`, `node_label`, and `description`.
    batch_size : int
        The number of nodes to process in each batch.

    Returns:
    -------
    list[tuple[str, list[Any]]]
        A list of tuples, where the first element is the node id and the second element is the embedding for the node description.
    """
    results = []

    for batch_idx, i in enumerate(range(0, len(nodes_dataframe), batch_size)):
        logger.debug(
            "Embedding batch %d/%d",
            batch_idx + 1,
            ceil(len(nodes_dataframe) / batch_size),
        )
        if i + batch_size >= len(nodes_dataframe):
            batch = nodes_dataframe.iloc[i:]
        else:
            batch = nodes_dataframe.iloc[i : i + batch_size]
        batch_results = await _create_embeddings_for_batch_async(embedding_fn, batch)

        # Add extracted records to the results list
        results.extend(batch_results)

    return results


def write_embeddings_to_graph(
    embeddings_df: pd.DataFrame,
    node_label: NodeLabel,
    neo4j_driver: Driver,
    database_name: str = "neo4j",
) -> None:
    """
    Write embeddings to Neo4j graph for a given node label.

    Parameters
    ----------
    embeddings_df : pd.DataFrame
        A Pandas DataFrame where each row represents a node.
        Has columns `id`, and `embedding`.
    node_label: str
        The label of the node to write embeddings to. Any label whose nodes carry a ``description``
        property (e.g. Database, Schema, Table, Column, BusinessTerm, GovernanceTagKey, or OSI labels).
    neo4j_driver: Driver
        The Neo4j driver to use.
    database_name: str
        The name of the database to write embeddings to.
    """
    query = f"""
    UNWIND $rows as row
    MATCH (n:{node_label} {{id: row.id}})
    CALL db.create.setNodeVectorProperty(n, 'embedding', row.embedding)
    """

    _, summary, _ = neo4j_driver.execute_query(
        query_=query,
        parameters_={"rows": embeddings_df.to_dict(orient="records")},
        database_=database_name,
        routing_=RoutingControl.WRITE,
    )

    logger.info("Wrote %d embeddings to (:%s)", summary.counters.properties_set, node_label)
    return summary.counters.__dict__
