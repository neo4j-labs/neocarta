"""Declarative rename-mapping primitives for the metadata normalizer.

A mapping is a pure ``(source_field, target_field)`` rename — no coercion, no
derivation. Source-specific/derived logic lives in retrievers (layer 1); type
coercion lives in the record-model validators (layer 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from pydantic import BaseModel

Field: TypeAlias = str
"""A source or target field name."""

Mapping: TypeAlias = tuple[Field, Field]
"""A single ``(source_field, target_field)`` pure-rename pair."""

Mappings: TypeAlias = list[Mapping]
"""An ordered list of rename pairs (a list, not a dict, so one source may feed many targets)."""


def apply_mappings(row: dict[str, Any], mappings: Mappings) -> dict[str, Any]:
    """Rename a source row's keys according to ``mappings``.

    Pure key-renaming only: for each ``(source, target)`` pair, sets
    ``out[target] = row.get(source)``. Unmapped source keys are dropped; a
    missing source key yields ``None`` for its target(s); if two pairs share a
    target, the later pair wins. No coercion or derivation happens here — that
    is the record model's job.

    Args:
        row: A flattened source row keyed by source field names.
        mappings: Ordered ``(source, target)`` rename pairs.

    Returns:
        A new dict keyed by target field names.
    """
    out: dict[str, Any] = {}
    for source, target in mappings:
        out[target] = row.get(source)
    return out


@dataclass(frozen=True)
class RecordMapping:
    """Declarative mapping for one logical record type into one container field."""

    record_type: str
    target_model: type[BaseModel]
    mappings: Mappings
    container_field: str


NormalizationSpec: TypeAlias = list[RecordMapping]
"""An ordered list of ``RecordMapping`` — the full declarative spec for a container."""


class BaseMapping:
    """Overridable base for connector mappings (subclassed in PR 3).

    Named ``BaseMapping`` (not ``Mapping``) to avoid colliding with the
    ``Mapping`` type alias. Intentionally NOT re-exported from the package.
    """

    def mappings(self) -> Mappings:
        """Return this mapping's ``(source, target)`` pairs (empty by default)."""
        return []
