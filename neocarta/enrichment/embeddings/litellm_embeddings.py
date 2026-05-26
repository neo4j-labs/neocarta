"""Connector for creating embeddings via LiteLLM (multi-provider)."""

from typing import Any

import litellm
from neo4j import Driver

from .base import BaseEmbeddingsConnector


class LiteLLMEmbeddingsConnector(BaseEmbeddingsConnector):
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
        super().__init__(
            neo4j_driver=neo4j_driver,
            embedding_model=embedding_model,
            database_name=database_name,
            dimensions=None,
        )
        self._call_kwargs: dict[str, Any] = dict(litellm_kwargs) if litellm_kwargs else {}

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
            return response.data[0]["embedding"]
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
            return response.data[0]["embedding"]
        except Exception as e:
            print(e)
            return None
