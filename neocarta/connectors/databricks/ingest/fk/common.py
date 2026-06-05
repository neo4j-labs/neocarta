"""Shared data structure for declared foreign-key discovery.

Only the declared-FK path lives in the connector; the heuristic inference rule
layer was relocated to ``neocarta.enrichment.foreign_keys.rules`` (Spark-free,
run in-process over the loaded graph). ``FKEdge`` carries an emitted REFERENCES
edge between the declared reader and the ``schema_graph`` DataFrame builder.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from neocarta.connectors.databricks.contract import EdgeSource


@dataclass(frozen=True, slots=True)
class FKEdge:
    """Emitted REFERENCES edge, tuple-converted once in
    ``schema_graph.build_references_rel``.

    `source` is an EdgeSource enum (not a magic string); the DataFrame builder
    serializes `.value` at the tuple boundary.
    """

    source_column_id: str
    target_column_id: str
    confidence: float
    source: EdgeSource
    criteria: str | None
