"""Connector for creating OpenAI embeddings."""

import pandas as pd
from neo4j import Driver
from openai import AsyncOpenAI, OpenAI

from ...enums import NodeLabel
from ...errors import ConfigError
from ...ingest.indexes import create_vector_index
from .utils import (
    create_embeddings_in_batches_async,
    create_embeddings_in_batches_sync,
    get_nodes_to_embed,
    write_embeddings_to_graph,
)


class OpenAIEmbeddingsConnector:
    """Connector for creating OpenAI embeddings."""

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

        self.client = client
        self.async_client = async_client
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

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
        try:
            response = self.client.embeddings.create(
                model=self.embedding_model,
                input=description,
                encoding_format="float",
                dimensions=self.dimensions,
            )
            return response.data[0].embedding
        except Exception as e:
            print(e)
            return None

    async def _create_embedding_async(
        self,
        description: str,
    ) -> list[float] | None:
        """
        Create embedding for a single node's description.
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
        try:
            response = await self.async_client.embeddings.create(
                model=self.embedding_model,
                input=description,
                encoding_format="float",
                dimensions=self.dimensions,
            )
            return response.data[0].embedding
        except Exception as e:
            print(e)
            return None

    def create_embeddings_sync(
        self,
        nodes_to_embed_dataframe: pd.DataFrame,
        batch_size: int = 100,
    ) -> pd.DataFrame:
        """
        Create embeddings for a Pandas DataFrame of nodes to embed (sync version).

        Parameters
        ----------
        nodes_to_embed_dataframe : pd.DataFrame
            A Pandas DataFrame where each row represents a node to embed.
            Has columns `id`, `node_label`, and `description`.
        batch_size : int
            The number of nodes to process in each batch.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame where each row represents a node.
            Has columns `id`, and `embedding`.
        """
        results = create_embeddings_in_batches_sync(
            self._create_embedding_sync, nodes_to_embed_dataframe, batch_size
        )
        print(f"Successful Embeddings : {len(results)}")
        return pd.DataFrame(results, columns=["id", "embedding"])

    async def create_embeddings_async(
        self,
        nodes_to_embed_dataframe: pd.DataFrame,
        batch_size: int = 100,
    ) -> pd.DataFrame:
        """
        Create embeddings for a Pandas DataFrame of nodes to embed.

        Parameters
        ----------
        nodes_to_embed_dataframe : pd.DataFrame
            A Pandas DataFrame where each row represents a node to embed.
            Has columns `id`, `node_label`, and `description`.
        batch_size : int
            The number of nodes to process in each batch.

        Returns:
        -------
        pd.DataFrame
            A Pandas DataFrame where each row represents a node.
            Has columns `id`, and `embedding`.
        """
        results = await create_embeddings_in_batches_async(
            self._create_embedding_async, nodes_to_embed_dataframe, batch_size
        )
        print(f"Successful Embeddings : {len(results)}")
        return pd.DataFrame(results, columns=["id", "embedding"])

    def run(
        self,
        node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
        batch_size: int = 100,
    ) -> None:
        """
        This sync workflow:
        * Gathers nodes from the Neo4j database that are missing embeddings
        * Creates embeddings of the description fields on found nodes
        * Ingests embeddings into the Neo4j database.

        Parameters
        ----------
        node_labels: list[str]
            The labels of the nodes to embed.
        batch_size: int
            The number of nodes to process in each batch.

        Raises:
        ------
        ConfigError
            If a sync client is not provided.
        """
        if self.client is None:
            raise ConfigError("Sync client is not provided")

        for label in node_labels:
            print(f"Processing {label} nodes...")
            print("--------------------------------")
            # create vector index, if it doesn't exist
            create_vector_index(self.neo4j_driver, label, self.dimensions, self.database_name)
            # get nodes to embed
            nodes_to_embed_dataframe = get_nodes_to_embed(
                self.neo4j_driver, label, 20, self.database_name
            )
            # create embeddings
            embeddings = self.create_embeddings_sync(
                nodes_to_embed_dataframe=nodes_to_embed_dataframe,
                batch_size=batch_size,
            )
            if len(embeddings) > 0:
                # ingest embeddings into the Neo4j database
                print(
                    write_embeddings_to_graph(
                        embeddings, label, self.neo4j_driver, self.database_name
                    )
                )
            else:
                print(f"No embeddings found for {label} nodes")

    async def arun(
        self,
        node_labels: list[NodeLabel] = [NodeLabel.TABLE, NodeLabel.COLUMN],
        batch_size: int = 100,
    ) -> None:
        """
        This async workflow:
        * Gathers nodes from the Neo4j database that are missing embeddings
        * Creates embeddings of the description fields on found nodes
        * Ingests embeddings into the Neo4j database.

        Parameters
        ----------
        node_labels: list[str]
            The labels of the nodes to embed.
        batch_size: int
            The number of nodes to process in each batch.

        Raises:
        ------
        ConfigError
            If an async client is not provided.
        """
        if self.async_client is None:
            raise ConfigError("Async client is not provided")

        for label in node_labels:
            print(f"Processing {label} nodes...")
            print("--------------------------------")
            # create vector index, if it doesn't exist
            create_vector_index(self.neo4j_driver, label, self.dimensions, self.database_name)
            # get nodes to embed
            nodes_to_embed_dataframe = get_nodes_to_embed(
                self.neo4j_driver, label, 20, self.database_name
            )
            # create embeddings
            embeddings = await self.create_embeddings_async(
                nodes_to_embed_dataframe=nodes_to_embed_dataframe,
                batch_size=batch_size,
            )
            if len(embeddings) > 0:
                # ingest embeddings into the Neo4j database
                print(
                    write_embeddings_to_graph(
                        embeddings, label, self.neo4j_driver, self.database_name
                    )
                )
            else:
                print(f"No embeddings found for {label} nodes")
