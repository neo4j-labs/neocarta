"""Spark-agnostic inferred foreign-key discovery over a loaded graph.

Proposes heuristic ``REFERENCES`` edges from Column facts already in Neo4j
(name/type/PK signals) and writes them tagged ``source="inferred_metadata"``.
Runs in-process (neo4j driver), independent of the Databricks Spark connector
that ingests the declared schema.
"""

from neocarta.enrichment.foreign_keys.infer import (
    InferredFKResult,
    infer_foreign_keys,
)

__all__ = ["InferredFKResult", "infer_foreign_keys"]
