"""A deterministic embedding stub for characterizing the enrichment write path.

Embeddings are the pipeline's one nondeterministic axis (live LiteLLM vectors). The
two mandated harness layers are embedding-free by construction — enrichment is a
separate post-load pass — so this stub is used only when a golden deliberately
includes enrichment. Its vectors are a pure function of the input text
(``sha256``-derived), so an enriched-graph golden stays byte-reproducible across runs
and machines without a live provider.
"""

from __future__ import annotations

import hashlib
import struct
from typing import TYPE_CHECKING

from neocarta.enrichment.embeddings.base import BaseEmbeddingsConnector

if TYPE_CHECKING:
    from neo4j import Driver

_DEFAULT_DIMENSIONS = 8
_UINT32_MAX = 0xFFFFFFFF


class DeterministicEmbeddingsConnector(BaseEmbeddingsConnector):
    """A :class:`BaseEmbeddingsConnector` with hash-derived, reproducible vectors.

    Only the four provider hooks are overridden; the base class owns dimension
    probing, batching, index creation, and the Neo4j read/write.
    """

    def __init__(
        self,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        dimensions: int = _DEFAULT_DIMENSIONS,
    ) -> None:
        """Initialize the stub with a fixed embedding dimension."""
        super().__init__(
            neo4j_driver,
            embedding_model="deterministic-characterization",
            database_name=database_name,
            dimensions=dimensions,
        )

    def _vector(self, description: str) -> list[float]:
        """Return a deterministic unit-range vector derived from ``description``."""
        dimensions = self._dimensions or _DEFAULT_DIMENSIONS
        values: list[float] = []
        counter = 0
        while len(values) < dimensions:
            digest = hashlib.sha256(f"{description}:{counter}".encode()).digest()
            for offset in range(0, len(digest), 4):
                if len(values) >= dimensions:
                    break
                (raw,) = struct.unpack(">I", digest[offset : offset + 4])
                values.append(round(raw / _UINT32_MAX * 2 - 1, 6))
            counter += 1
        return values

    def _create_embedding_sync(self, description: str) -> list[float]:
        """Return the deterministic vector for a single description (sync)."""
        return self._vector(description)

    async def _create_embedding_async(self, description: str) -> list[float]:
        """Return the deterministic vector for a single description (async)."""
        return self._vector(description)

    def _create_embeddings_sync(self, descriptions: list[str]) -> list[list[float]]:
        """Return deterministic vectors for a batch of descriptions (sync)."""
        return [self._vector(description) for description in descriptions]

    async def _create_embeddings_async(self, descriptions: list[str]) -> list[list[float]]:
        """Return deterministic vectors for a batch of descriptions (async)."""
        return [self._vector(description) for description in descriptions]
