"""Marker/contract base for normalized-metadata intermediates."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class NormalizedMetadata(BaseModel):
    """Marker base for a normalized-metadata intermediate.

    A normalized-metadata object is the flat, source-mirroring intermediate that a
    connector's normalizer produces and the graph transformer consumes. This base
    carries no data fields of its own: its children (:class:`InformationSchemaTable`,
    :class:`Osi`) share essentially no fields, so the base exists only to give the
    normalizer a single return type plus a ``normalized_kind`` discriminator.
    Deterministic ids and embeddings are intentionally absent from the intermediate;
    they are generated later, in the graph-transform step.
    """

    model_config = ConfigDict(extra="forbid")

    normalized_kind: ClassVar[str]  # concrete children assign a value
