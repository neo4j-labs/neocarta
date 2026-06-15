"""Base class for embedding connectors."""

import logging

import pandas as pd
from neo4j import Driver

from ...enums import NodeLabel
from ...ingest.indexes import create_vector_index
from .utils import (
    create_embeddings_in_batches_async,
    create_embeddings_in_batches_sync,
    get_nodes_to_embed,
    write_embeddings_to_graph,
)

logger = logging.getLogger(__name__)

_DIMENSION_PROBE_INPUT = "dimension probe"


class BaseEmbeddingsConnector:
    """Base class shared by all embedding connectors.

    Subclasses provide the provider-specific bits:

    * ``__init__`` — store the provider client(s) / config and call
      ``super().__init__`` with the common arguments.
    * ``_create_embedding_sync`` — return the embedding vector for a single
      description, or ``None`` on failure.
    * ``_create_embedding_async`` — async variant of the above.

    The batch loop, Neo4j read/write, vector-index creation and dimension
    probing are all handled here.
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        embedding_model: str,
        database_name: str = "neo4j",
        dimensions: int | None = None,
    ) -> None:
        """
        Initialize the base embeddings connector.

        Parameters
        ----------
        neo4j_driver: Driver
            The Neo4j driver to use.
        embedding_model: str
            The embedding model identifier.
        database_name: str
            The name of the Neo4j database to write embeddings to.
        dimensions: Optional[int]
            The embedding dimension, if known up front. When ``None`` the
            dimension is discovered on first use via a one-shot probe call.
        """
        self.neo4j_driver = neo4j_driver
        self.embedding_model = embedding_model
        self.database_name = database_name
        self._dimensions: int | None = dimensions

    @property
    def dimensions(self) -> int | None:
        """The embedding dimension (set up front or discovered on first use)."""
        return self._dimensions

    def _create_embedding_sync(self, description: str) -> list[float] | None:
        """
        Create an embedding for a single description (sync).

        Subclasses must override this.
        """
        raise NotImplementedError

    async def _create_embedding_async(self, description: str) -> list[float] | None:
        """
        Create an embedding for a single description (async).

        Subclasses must override this.
        """
        raise NotImplementedError

    def _create_embeddings_sync(self, descriptions: list[str]) -> list[list[float] | None]:
        """
        Create embeddings for a batch of descriptions in a single request (sync).

        Subclasses must override this.
        """
        raise NotImplementedError

    async def _create_embeddings_async(self, descriptions: list[str]) -> list[list[float] | None]:
        """
        Create embeddings for a batch of descriptions in a single request (async).

        Subclasses must override this.
        """
        raise NotImplementedError

    def _probe_dimensions_sync(self) -> int:
        """Discover the model's embedding dimension via one probe call."""
        if self._dimensions is not None:
            return self._dimensions
        vector = self._create_embedding_sync(_DIMENSION_PROBE_INPUT)
        if vector is None:
            raise RuntimeError(
                f"Failed to probe embedding dimension for model '{self.embedding_model}'. "
                "Check provider credentials and model id."
            )
        self._dimensions = len(vector)
        logger.info(
            "Detected embedding dimension %d for model %s",
            self._dimensions,
            self.embedding_model,
        )
        return self._dimensions

    async def _probe_dimensions_async(self) -> int:
        """Async variant of ``_probe_dimensions_sync``."""
        if self._dimensions is not None:
            return self._dimensions
        vector = await self._create_embedding_async(_DIMENSION_PROBE_INPUT)
        if vector is None:
            raise RuntimeError(
                f"Failed to probe embedding dimension for model '{self.embedding_model}'. "
                "Check provider credentials and model id."
            )
        self._dimensions = len(vector)
        logger.info(
            "Detected embedding dimension %d for model %s",
            self._dimensions,
            self.embedding_model,
        )
        return self._dimensions

    def create_embeddings_sync(
        self,
        nodes_to_embed_dataframe: pd.DataFrame,
        batch_size: int = 100,
    ) -> pd.DataFrame:
        """
        Create embeddings for a Pandas DataFrame of nodes to embed (sync).

        Parameters
        ----------
        nodes_to_embed_dataframe : pd.DataFrame
            A Pandas DataFrame where each row represents a node to embed.
            Has columns ``id``, ``node_label``, and ``description``.
        batch_size : int
            The number of nodes to process in each batch.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame where each row represents a node.
            Has columns ``id`` and ``embedding``.
        """
        results = create_embeddings_in_batches_sync(
            self._create_embeddings_sync, nodes_to_embed_dataframe, batch_size
        )
        logger.info("Embedded %d descriptions", len(results))
        return pd.DataFrame(results, columns=["id", "embedding"])

    async def create_embeddings_async(
        self,
        nodes_to_embed_dataframe: pd.DataFrame,
        batch_size: int = 100,
    ) -> pd.DataFrame:
        """
        Create embeddings for a Pandas DataFrame of nodes to embed (async).

        Parameters
        ----------
        nodes_to_embed_dataframe : pd.DataFrame
            A Pandas DataFrame where each row represents a node to embed.
            Has columns ``id``, ``node_label``, and ``description``.
        batch_size : int
            The number of nodes to process in each batch.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame where each row represents a node.
            Has columns ``id`` and ``embedding``.
        """
        results = await create_embeddings_in_batches_async(
            self._create_embeddings_async, nodes_to_embed_dataframe, batch_size
        )
        logger.info("Embedded %d descriptions", len(results))
        return pd.DataFrame(results, columns=["id", "embedding"])

    def run(
        self,
        node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
        batch_size: int = 100,
    ) -> None:
        """
        Sync workflow: fetch nodes missing embeddings, embed them, write back.

        Parameters
        ----------
        node_labels: list[NodeLabel]
            The labels of the nodes to embed.
        batch_size: int
            The number of nodes to process in each batch.
        """
        dimensions = self._probe_dimensions_sync()

        for label in node_labels:
            logger.info("Embedding %s nodes...", label)
            create_vector_index(self.neo4j_driver, label, dimensions, self.database_name)
            nodes_to_embed_dataframe = get_nodes_to_embed(
                self.neo4j_driver, label, self.database_name
            )
            embeddings = self.create_embeddings_sync(
                nodes_to_embed_dataframe=nodes_to_embed_dataframe,
                batch_size=batch_size,
            )
            if len(embeddings) > 0:
                write_embeddings_to_graph(embeddings, label, self.neo4j_driver, self.database_name)
            else:
                logger.info("No %s nodes needed embedding", label)

    async def arun(
        self,
        node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
        batch_size: int = 100,
    ) -> None:
        """
        Async workflow: fetch nodes missing embeddings, embed them, write back.

        Parameters
        ----------
        node_labels: list[NodeLabel]
            The labels of the nodes to embed.
        batch_size: int
            The number of nodes to process in each batch.
        """
        dimensions = await self._probe_dimensions_async()

        for label in node_labels:
            logger.info("Embedding %s nodes...", label)
            create_vector_index(self.neo4j_driver, label, dimensions, self.database_name)
            nodes_to_embed_dataframe = get_nodes_to_embed(
                self.neo4j_driver, label, self.database_name
            )
            embeddings = await self.create_embeddings_async(
                nodes_to_embed_dataframe=nodes_to_embed_dataframe,
                batch_size=batch_size,
            )
            if len(embeddings) > 0:
                write_embeddings_to_graph(embeddings, label, self.neo4j_driver, self.database_name)
            else:
                logger.info("No %s nodes needed embedding", label)
