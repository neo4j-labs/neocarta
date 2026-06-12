"""Connector for creating embeddings via LiteLLM (multi-provider)."""

import logging
from typing import Any

import litellm
from neo4j import Driver

from .base import BaseEmbeddingsConnector

logger = logging.getLogger(__name__)


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
    pass an explicit ``dimensions`` (and the model must support it). Models
    that do not support dimension truncation ignore it gracefully via
    LiteLLM's ``drop_params`` — the probe then reports the model's native
    dimension, so the index and the stored vectors always agree.

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
        dimensions: int | None = None,
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
        dimensions: Optional[int]
            Requested embedding vector dimension, for models that support
            truncation. When ``None`` the model's native dimension is used.
            When set, it is forwarded to LiteLLM alongside ``drop_params`` so
            models that do not support truncation drop it instead of erroring.
        litellm_kwargs: Optional[dict[str, Any]]
            Additional keyword arguments forwarded verbatim to
            ``litellm.embedding`` / ``litellm.aembedding`` — e.g.
            ``api_key`` / ``api_base`` for LiteLLM Proxy / custom endpoints, or
            ``additional_drop_params=["dimensions"]`` for OpenAI-compatible
            endpoints that LiteLLM cannot introspect. Values here take
            precedence over ``dimensions``.
        """
        # Intentionally pass dimensions=None to the base so the dimension is
        # always probed on first use. The probe call carries the kwargs below,
        # so when ``drop_params`` drops an unsupported ``dimensions`` the probe
        # reports the model's actual native size and the vector index is
        # created to match the vectors that are really returned.
        super().__init__(
            neo4j_driver=neo4j_driver,
            embedding_model=embedding_model,
            database_name=database_name,
            dimensions=None,
        )
        self._call_kwargs: dict[str, Any] = dict(litellm_kwargs) if litellm_kwargs else {}
        if dimensions is not None:
            self._call_kwargs.setdefault("dimensions", dimensions)
            self._call_kwargs.setdefault("drop_params", True)

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
            logger.warning("Embedding request failed (%s)", type(e).__name__)
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
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            return None

    def _create_embeddings_sync(self, descriptions: list[str]) -> list[list[float] | None]:
        """
        Create embeddings for a batch of descriptions in a single request (sync).

        Parameters
        ----------
        descriptions: list[str]
            The descriptions of the nodes.

        Returns:
        -------
        list[Optional[list[float]]]
            One embedding vector per description, in input order. Raises if the
            batch request fails, rather than silently falling back to slow
            per-item calls.
        """
        try:
            response = litellm.embedding(
                model=self.embedding_model,
                input=descriptions,
                **self._call_kwargs,
            )
            ordered = sorted(response.data, key=lambda item: item["index"])
            return [item["embedding"] for item in ordered]
        except Exception as e:
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            raise

    async def _create_embeddings_async(self, descriptions: list[str]) -> list[list[float] | None]:
        """
        Create embeddings for a batch of descriptions in a single request (async).

        Parameters
        ----------
        descriptions: list[str]
            The descriptions of the nodes.

        Returns:
        -------
        list[Optional[list[float]]]
            One embedding vector per description, in input order. Raises if the
            batch request fails, rather than silently falling back to slow
            per-item calls.
        """
        try:
            response = await litellm.aembedding(
                model=self.embedding_model,
                input=descriptions,
                **self._call_kwargs,
            )
            ordered = sorted(response.data, key=lambda item: item["index"])
            return [item["embedding"] for item in ordered]
        except Exception as e:
            logger.warning("Embedding request failed (%s)", type(e).__name__)
            raise
