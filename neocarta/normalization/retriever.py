"""The streaming source contract consumed by the metadata normalizer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Iterable


@runtime_checkable
class Retriever(Protocol):
    """Streams already-flattened source rows for a logical record type.

    Layer-1 derived logic (PK/FK detection, platform/service constants,
    ``is_nullable`` decoding, FK-row filtering, self-ref skipping) lives in
    concrete retrievers (PR 3), not here. Rows are keyed by *source* field names.
    """

    def stream(self, record_type: str) -> Iterable[dict[str, Any]]:
        """Yield flattened source rows for ``record_type`` (keyed by source names)."""
        ...
