"""Connector for creating OpenAI embeddings."""

import logging

from neo4j import Driver
from openai import AsyncOpenAI, OpenAI

from ...errors import ConfigError
from .base import BaseEmbeddingsConnector

logger = logging.getLogger(__name__)


class OpenAIEmbeddingsConnector(BaseEmbeddingsConnector):
    """Connector for creating embeddings via the OpenAI Python SDK."""

    def __init__(
        self,
        neo4j_driver: Driver,
        client: OpenAI | None = None,
        async_client: AsyncOpenAI | None = None,
        embedding_model: str = "text-embedding-3-small",
        dimensions: int = 768,
        database_name: str = "neo4j",
    ) -> None:
        """
        Initialize the OpenAI Embeddings Connector.

        Parameters
        ----------
        neo4j_driver: Driver
            The Neo4j driver to use.
        client: Optional[OpenAI]
            The sync embedding client to use.
        async_client: Optional[AsyncOpenAI]
            The async embedding client to use.
        embedding_model: str
            The embedding model to use.
        dimensions: int
            The dimensions of the embeddings.
        database_name: str
            The name of the Neo4j database to write embeddings to.
        """
        if client is None and async_client is None:
            raise ValueError("Either client or async_client must be provided")

        super().__init__(
            neo4j_driver=neo4j_driver,
            embedding_model=embedding_model,
            database_name=database_name,
            dimensions=dimensions,
        )
        self.client = client
        self.async_client = async_client

    def _create_embedding_sync(self, description: str) -> list[float] | None:
        """
        Create embedding for a single node's description (sync version).
        If embedding creation fails, return None.

        Parameters
        ----------
        description: str
            The description of the node.

        Returns:
        -------
        Optional[list[float]]
            The embedding for the node description.
            If embedding creation fails, return None.
        """
        if self.client is None:
            raise ConfigError("Sync client is not provided")
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=description,
                encoding_format="float",
                dimensions=self.dimensions,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            return None

    async def _create_embedding_async(self, description: str) -> list[float] | None:
        """
        Create embedding for a single node's description (async version).
        If embedding creation fails, return None.

        Parameters
        ----------
        description: str
            The description of the node.

        Returns:
        -------
        Optional[list[float]]
            The embedding for the node description.
            If embedding creation fails, return None.
        """
        if self.async_client is None:
            raise ConfigError("Async client is not provided")
        try:
            response = await self.async_client.embeddings.create(
                model=self.embedding_model,
                input=description,
                encoding_format="float",
                dimensions=self.dimensions,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            return None

    def _create_embeddings_sync(self, descriptions: list[str]) -> list[list[float] | None]:
        """
        Create embeddings for a batch of node descriptions (sync version).
        Raises if the batch request fails, rather than silently falling back to
        slow per-item calls.

        Parameters
        ----------
        descriptions: list[str]
            The descriptions of the nodes.

        Returns:
        -------
        list[Optional[list[float]]]
            One embedding per description, in input order.
        """
        if self.client is None:
            raise ConfigError("Sync client is not provided")
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=descriptions,
                encoding_format="float",
                dimensions=self.dimensions,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            return [item.embedding for item in ordered]
        except Exception as e:
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            raise

    async def _create_embeddings_async(self, descriptions: list[str]) -> list[list[float] | None]:
        """
        Create embeddings for a batch of node descriptions (async version).
        Raises if the batch request fails, rather than silently falling back to
        slow per-item calls.

        Parameters
        ----------
        descriptions: list[str]
            The descriptions of the nodes.

        Returns:
        -------
        list[Optional[list[float]]]
            One embedding per description, in input order.
        """
        if self.async_client is None:
            raise ConfigError("Async client is not provided")
        try:
            response = await self.async_client.embeddings.create(
                model=self.embedding_model,
                input=descriptions,
                encoding_format="float",
                dimensions=self.dimensions,
            )
            ordered = sorted(response.data, key=lambda item: item.index)
            return [item.embedding for item in ordered]
        except Exception as e:
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            raise
