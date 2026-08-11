"""Reusable characterization / golden-master harness (S0-SPIKE-1 / #291).

Two layers prove behavioral parity through the refactor, both compared to committed
JSON goldens via :func:`assert_matches_golden`:

- **Layer A (no Docker):** :func:`serialize_transform` freezes a connector's
  transform-level output (node/relationship model lists + any ``get_properties``
  allowlist).
- **Layer R (no Docker):** :func:`dump_records` freezes the **normalized records** a
  connector emits, before any graph shaping — the S1-band target in
  ``docs/testing/test-quality-inventory.md``, added by S1.6 (#297).
- **Layer B (Docker):** :func:`dump_graph` captures post-ingest Neo4j graph state
  deterministically.

See ``docs/testing/characterization-harness.md`` for the reference pattern every later
"characterize-before-you-refactor" ticket reuses.
"""

from __future__ import annotations

from pathlib import Path

from .bigquery_cache import make_mock_bigquery_client, seed_bigquery_schema_cache
from .golden import assert_matches_golden, canonical_json
from .graph_dump import dump_graph
from .normalized_dump import dump_records
from .serialize import serialize_transform

DATASETS_CSV: Path = Path(__file__).resolve().parents[3] / "datasets" / "csv"
"""The committed CSV sample dataset — the deterministic offline input for the CSV connector."""

__all__ = [
    "DATASETS_CSV",
    "assert_matches_golden",
    "canonical_json",
    "dump_graph",
    "dump_records",
    "make_mock_bigquery_client",
    "seed_bigquery_schema_cache",
    "serialize_transform",
]
