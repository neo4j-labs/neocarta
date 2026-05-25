"""Connector for creating embeddings via LiteLLM (multi-provider)."""

from typing import Any

import litellm
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

_DIMENSION_PROBE_INPUT = "dimension probe"


class LiteLLMEmbeddingsConnector:
    """Connector for creating embeddings through LiteLLM.

    LiteLLM exposes a single, OpenAI-compatible interface over many providers
    (OpenAI, Azure OpenAI, Cohere, Bedrock, Vertex, Gemini, Ollama,
    HuggingFace, ...). Provider routing is driven by the ``embedding_model``
    string — e.g. ``"text-embedding-3-small"`` (OpenAI),
    ``"gemini-embedding-001"``.

    The vector dimension is auto-detected from the model on first use (one
    probe call) and the Neo4j vector index is created at that size, so no
    manual dimension config is required. If you need a non-default size,
    pass an explicit ``dimensions`` to ``litellm_kwargs`` (and the model
    must support it).

    Authentication is read from provider-specific environment variables
    (``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ``COHERE_API_KEY``, ``AZURE_*``,
    ``AWS_*``, etc.). For advanced setups (LiteLLM Proxy, custom endpoints,
    overlapping keys), pass ``api_key`` / ``api_base`` via ``litellm_kwargs``.
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        embedding_model: str = "text-embedding-3-small",
        database_name: str = "neo4j",
        litellm_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """
        Initialize the LiteLLM Embeddings Connector.

        Parameters
        ----------
        neo4j_driver: Driver
            The Neo4j driver to use.
        embedding_model: str
            The model identifier in LiteLLM format (provider prefix optional
            for OpenAI). Examples: ``"text-embedding-3-small"``,
            ``"gemini-embedding-001"``.
        database_name: str
            The name of the Neo4j database to write embeddings to.
        litellm_kwargs: Optional[dict[str, Any]]
            Additional keyword arguments forwarded verbatim to
            ``litellm.embedding`` / ``litellm.aembedding`` — e.g.
            ``dimensions`` for models that support truncation, or
            ``api_key`` / ``api_base`` for LiteLLM Proxy / custom endpoints.
        """
        self.neo4j_driver = neo4j_driver
        self.embedding_model = embedding_model
        self.database_name = database_name
        self._dimensions: int | None = None
        self._call_kwargs: dict[str, Any] = dict(litellm_kwargs) if litellm_kwargs else {}

    @property
    def dimensions(self) -> int | None:
        """The detected embedding dimension (set after the first embed call)."""
        return self._dimensions

    def _create_embedding_sync(self, description: str) -> list[float] | None:
        """
        Create an embedding for a single description (sync).

        Parameters
        ----------
        description: str
            The description of the node.

        Returns:
        -------
        Optional[list[float]]
            The embedding vector, or ``None`` if the API call fails.
        """
        try:
            response = litellm.embedding(
                model=self.embedding_model,
                input=[description],
                **self._call_kwargs,
            )
            vector = response.data[0]["embedding"]
            if self._dimensions is None:
                self._dimensions = len(vector)
            return vector
        except Exception as e:
            print(e)
            return None

    async def _create_embedding_async(self, description: str) -> list[float] | None:
        """
        Create an embedding for a single description (async).

        Parameters
        ----------
        description: str
            The description of the node.

        Returns:
        -------
        Optional[list[float]]
            The embedding vector, or ``None`` if the API call fails.
        """
        try:
            response = await litellm.aembedding(
                model=self.embedding_model,
                input=[description],
                **self._call_kwargs,
            )
            vector = response.data[0]["embedding"]
            if self._dimensions is None:
                self._dimensions = len(vector)
            return vector
        except Exception as e:
            print(e)
            return None

    def _probe_dimensions_sync(self) -> int:
        """Run a tiny embed call to discover the model's native vector size."""
        vector = self._create_embedding_sync(_DIMENSION_PROBE_INPUT)
        if vector is None:
            raise RuntimeError(
                f"Failed to probe embedding dimension for model '{self.embedding_model}'. "
                "Check provider credentials and model id."
            )
        return len(vector)

    async def _probe_dimensions_async(self) -> int:
        """Async variant of ``_probe_dimensions_sync``."""
        vector = await self._create_embedding_async(_DIMENSION_PROBE_INPUT)
        if vector is None:
            raise RuntimeError(
                f"Failed to probe embedding dimension for model '{self.embedding_model}'. "
                "Check provider credentials and model id."
            )
        return len(vector)

    def create_embeddings_sync(
        self,
        nodes_to_embed_dataframe: pd.DataFrame,
        batch_size: int = 100,
    ) -> pd.DataFrame:
        """
        Create embeddings for a DataFrame of nodes (sync).

        Parameters
        ----------
        nodes_to_embed_dataframe : pd.DataFrame
            Has columns ``id``, ``node_label``, and ``description``.
        batch_size : int
            The number of nodes to process in each batch.

        Returns:
        -------
        pd.DataFrame
            Has columns ``id`` and ``embedding``.
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
        Create embeddings for a DataFrame of nodes (async).

        Parameters
        ----------
        nodes_to_embed_dataframe : pd.DataFrame
            Has columns ``id``, ``node_label``, and ``description``.
        batch_size : int
            The number of nodes to process in each batch.

        Returns:
        -------
        pd.DataFrame
            Has columns ``id`` and ``embedding``.
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
        Sync workflow: fetch nodes missing embeddings, embed them, write back.

        Parameters
        ----------
        node_labels: list[NodeLabel]
            The labels of the nodes to embed.
        batch_size: int
            The number of nodes to process in each batch.
        """
        dimensions = self._probe_dimensions_sync()
        print(f"Detected embedding dimension: {dimensions}")

        for label in node_labels:
            print(f"Processing {label} nodes...")
            print("--------------------------------")
            create_vector_index(self.neo4j_driver, label, dimensions, self.database_name)
            nodes_to_embed_dataframe = get_nodes_to_embed(
                self.neo4j_driver, label, 20, self.database_name
            )
            embeddings = self.create_embeddings_sync(
                nodes_to_embed_dataframe=nodes_to_embed_dataframe,
                batch_size=batch_size,
            )
            if len(embeddings) > 0:
                print(
                    write_embeddings_to_graph(
                        embeddings, label, self.neo4j_driver, self.database_name
                    )
                )
            else:
                print(f"No embeddings found for {label} nodes")

        self.neo4j_driver.close()

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
        print(f"Detected embedding dimension: {dimensions}")

        for label in node_labels:
            print(f"Processing {label} nodes...")
            print("--------------------------------")
            create_vector_index(self.neo4j_driver, label, dimensions, self.database_name)
            nodes_to_embed_dataframe = get_nodes_to_embed(
                self.neo4j_driver, label, 20, self.database_name
            )
            embeddings = await self.create_embeddings_async(
                nodes_to_embed_dataframe=nodes_to_embed_dataframe,
                batch_size=batch_size,
            )
            if len(embeddings) > 0:
                print(
                    write_embeddings_to_graph(
                        embeddings, label, self.neo4j_driver, self.database_name
                    )
                )
            else:
                print(f"No embeddings found for {label} nodes")

        self.neo4j_driver.close()
