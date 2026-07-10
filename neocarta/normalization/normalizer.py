"""The generic metadata-normalizer engine (pure rename; no coercion/Neo4j/ids)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .mapping import apply_mappings

if TYPE_CHECKING:
    from ..data_model.normalized import NormalizedMetadata
    from .mapping import NormalizationSpec
    from .retriever import Retriever


class MetadataNormalizer:
    """Turns a retriever's rows + a ``NormalizationSpec`` into a populated container.

    Does only key-renaming (via :func:`apply_mappings`); the record models coerce
    types at construction. Never generates ids or touches Neo4j.
    """

    def __init__(
        self,
        retriever: Retriever,
        spec: NormalizationSpec,
        container_type: type[NormalizedMetadata],
    ) -> None:
        """Store the retriever, declarative spec, and target container type."""
        self._retriever = retriever
        self._spec = spec
        self._container_type = container_type

    def normalize(self) -> NormalizedMetadata:
        """Stream, rename, and construct records into one ``NormalizedMetadata`` container.

        For each ``RecordMapping`` in the spec: stream its ``record_type`` rows,
        apply the rename, and construct ``target_model`` (validators coerce here),
        collecting the list under ``container_field``. Container fields absent
        from the spec fall back to the model's defaults (empty lists). One
        ``RecordMapping`` per ``container_field`` is expected — a duplicate lets
        the later entry win.

        Returns:
            A populated instance of the configured container type.
        """
        buckets = {}
        for record_mapping in self._spec:
            buckets[record_mapping.container_field] = [
                record_mapping.target_model(**apply_mappings(row, record_mapping.mappings))
                for row in self._retriever.stream(record_mapping.record_type)
            ]
        return self._container_type(**buckets)
