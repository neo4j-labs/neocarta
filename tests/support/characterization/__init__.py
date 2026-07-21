"""Reusable characterization / golden-master harness (S0-SPIKE-1 / #291).

Two layers prove behavioral parity through the refactor:

- **Layer A (no Docker):** :func:`serialize_transform` freezes a connector's
  transform-level output (node/relationship model lists) to a canonical dict.
- **Layer B (Docker):** :func:`dump_graph` captures post-ingest Neo4j graph state
  deterministically.

Both are compared to committed JSON goldens via :func:`assert_matches_golden`.
:class:`DeterministicEmbeddingsConnector` stubs the one nondeterministic axis
(embeddings) for the optional enrichment-characterization layer. See
``docs/testing/characterization-harness.md`` for the reference pattern every later
"characterize-before-you-refactor" ticket reuses.
"""

from __future__ import annotations

from .bigquery_cache import make_mock_bigquery_client, seed_bigquery_schema_cache
from .embeddings import DeterministicEmbeddingsConnector
from .golden import assert_matches_golden, canonical_json
from .graph_dump import dump_graph, fetch_metadata_node
from .paths import DATASETS_CSV, repo_root
from .serialize import assert_transform_embeddings_absent, serialize_transform

__all__ = [
    "DATASETS_CSV",
    "DeterministicEmbeddingsConnector",
    "assert_matches_golden",
    "assert_transform_embeddings_absent",
    "canonical_json",
    "dump_graph",
    "fetch_metadata_node",
    "make_mock_bigquery_client",
    "repo_root",
    "seed_bigquery_schema_cache",
    "serialize_transform",
]
