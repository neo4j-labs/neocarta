"""Base class for description generation connectors."""

import logging
from typing import Any

import pandas as pd
from neo4j import Driver

from ...enums import NodeLabel
from .utils import (
    generate_descriptions_in_batches_async,
    generate_descriptions_in_batches_sync,
    get_node_context,
    get_nodes_to_describe,
    write_descriptions_to_graph,
)

logger = logging.getLogger(__name__)

_SUPPORTED_LABELS = (NodeLabel.SCHEMA, NodeLabel.TABLE, NodeLabel.COLUMN)


class BaseDescriptionConnector:
    """Base class shared by all description generation connectors.

    Subclasses provide the provider-specific bits:

    * ``__init__`` — store the provider client(s) / config and call
      ``super().__init__`` with the common arguments.
    * ``_generate_description_sync`` — return the generated description for
      a single node's context, or ``None`` on failure.
    * ``_generate_description_async`` — async variant of the above.

    The batch loop, context fetching, and Neo4j read/write are all handled
    here, mirroring the structure of ``BaseEmbeddingsConnector``.
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        generation_model: str,
        database_name: str = "neo4j",
        max_example_values: int = 5,
    ) -> None:
        """
        Initialize the base description connector.

        Parameters
        ----------
        neo4j_driver: Driver
            The Neo4j driver to use.
        generation_model: str
            The text-generation model identifier.
        database_name: str
            The name of the Neo4j database to read context from / write
            descriptions to.
        max_example_values: int
            The maximum number of example Value nodes to fetch for a Column's
            context.
        """
        self.neo4j_driver = neo4j_driver
        self.generation_model = generation_model
        self.database_name = database_name
        self.max_example_values = max_example_values

    def _generate_description_sync(self, context: dict[str, Any]) -> str | None:
        """
        Generate a description for a single node's context (sync).

        Subclasses must override this.
        """
        raise NotImplementedError

    async def _generate_description_async(self, context: dict[str, Any]) -> str | None:
        """
        Generate a description for a single node's context (async).

        Subclasses must override this.
        """
        raise NotImplementedError

    def _generate_descriptions_sync(self, contexts: list[dict[str, Any]]) -> list[str | None]:
        """
        Generate descriptions for a batch of node contexts (sync).

        Default implementation calls ``_generate_description_sync`` once per
        context. Subclasses may override this to use a true batch API.
        """
        return [self._generate_description_sync(context) for context in contexts]

    async def _generate_descriptions_async(
        self, contexts: list[dict[str, Any]]
    ) -> list[str | None]:
        """
        Generate descriptions for a batch of node contexts (async).

        Default implementation calls ``_generate_description_async`` once per
        context. Subclasses may override this to use a true batch API.
        """
        return [await self._generate_description_async(context) for context in contexts]

    def _build_nodes_with_context(
        self, node_label: NodeLabel
    ) -> pd.DataFrame:
        """Fetch nodes missing a description and attach their context."""
        nodes_df = get_nodes_to_describe(self.neo4j_driver, node_label, self.database_name)
        if len(nodes_df) == 0:
            return nodes_df

        contexts = [
            get_node_context(
                self.neo4j_driver,
                node_id,
                node_label,
                self.database_name,
                self.max_example_values,
            )
            for node_id in nodes_df["id"]
        ]
        nodes_df = nodes_df.copy()
        for key in contexts[0] if contexts else []:
            nodes_df[key] = [c.get(key) for c in contexts]
        return nodes_df

    def run(
        self,
        node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
        batch_size: int = 20,
    ) -> None:
        """
        Sync workflow: fetch nodes missing descriptions, generate them, write back.

        Parameters
        ----------
        node_labels: list[NodeLabel]
            The labels of the nodes to describe. Must be a subset of
            Schema, Table, Column.
        batch_size: int
            The number of nodes to process in each batch.
        """
        for label in node_labels:
            if label not in _SUPPORTED_LABELS:
                logger.warning(
                    "Skipping unsupported node_label %s for description generation "
                    "(supported: %s)",
                    label,
                    _SUPPORTED_LABELS,
                )
                continue

            logger.info("Generating descriptions for %s nodes...", label)
            nodes_df = self._build_nodes_with_context(label)
            if len(nodes_df) == 0:
                logger.info("No %s nodes needed a description", label)
                continue

            results = generate_descriptions_in_batches_sync(
                self._generate_descriptions_sync, nodes_df, batch_size
            )
            logger.info("Generated %d descriptions", len(results))
            if results:
                descriptions_df = pd.DataFrame(results, columns=["id", "description"])
                write_descriptions_to_graph(
                    descriptions_df, label, self.neo4j_driver, self.database_name
                )

    async def arun(
        self,
        node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
        batch_size: int = 20,
    ) -> None:
        """
        Async workflow: fetch nodes missing descriptions, generate them, write back.

        Parameters
        ----------
        node_labels: list[NodeLabel]
            The labels of the nodes to describe. Must be a subset of
            Schema, Table, Column.
        batch_size: int
            The number of nodes to process in each batch.
        """
        for label in node_labels:
            if label not in _SUPPORTED_LABELS:
                logger.warning(
                    "Skipping unsupported node_label %s for description generation "
                    "(supported: %s)",
                    label,
                    _SUPPORTED_LABELS,
                )
                continue

            logger.info("Generating descriptions for %s nodes...", label)
            nodes_df = self._build_nodes_with_context(label)
            if len(nodes_df) == 0:
                logger.info("No %s nodes needed a description", label)
                continue

            results = await generate_descriptions_in_batches_async(
                self._generate_descriptions_async, nodes_df, batch_size
            )
            logger.info("Generated %d descriptions", len(results))
            if results:
                descriptions_df = pd.DataFrame(results, columns=["id", "description"])
                write_descriptions_to_graph(
                    descriptions_df, label, self.neo4j_driver, self.database_name
                )
