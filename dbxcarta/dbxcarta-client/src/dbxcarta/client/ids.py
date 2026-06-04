"""Helpers for parsing dbxcarta catalog node identifiers."""

from __future__ import annotations


def schema_from_node_id(node_id: str) -> str | None:
    """Extract the schema component from a catalog.schema.table[.column] ID."""
    parts = node_id.split(".")
    return parts[1] if len(parts) >= 3 else None


def catalog_from_node_id(node_id: str) -> str | None:
    """Extract the catalog component from a catalog.schema.table[.column] ID.

    Ingest builds every Table/Column id catalog-qualified, so the catalog is
    authoritative per node. Used to reconstruct multi-catalog FQNs rather
    than assuming a single configured catalog.
    """
    parts = node_id.split(".")
    return parts[0] if len(parts) >= 3 else None
