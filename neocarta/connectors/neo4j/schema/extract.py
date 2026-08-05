"""Extract Neo4j schema metadata via APOC (apoc.meta.schema)."""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING

import pandas as pd
from neo4j import RoutingControl

from ...._logging import log_stage
from ....errors import ConfigError, TransformError
from ....ingest.lpg import RESERVED_NODE_LABELS, RESERVED_RELATIONSHIP_TYPES
from ....warnings import Neo4jSchemaWarning
from .._errors import wrap_neo4j_errors

if TYPE_CHECKING:
    from neo4j import Driver

    from .models import SchemaExtractorCache

logger = logging.getLogger(__name__)


def _property_row(owner_key: str, owner: str, prop_name: str, meta: dict) -> dict:
    """Build one property row from an APOC property-meta map."""
    return {
        owner_key: owner,
        "property": prop_name,
        "type": meta.get("type"),
        "unique": bool(meta.get("unique", False)),
        "indexed": bool(meta.get("indexed", meta.get("index", False))),
        "existence": bool(meta.get("existence", False)),
    }


def _property_rows(owner_key: str, owner: str, properties: dict) -> list[dict]:
    """Build property rows for one owner, skipping malformed (non-dict) metas."""
    rows = []
    for prop_name, meta in properties.items():
        if not isinstance(meta, dict):
            warnings.warn(
                f"Skipping malformed property {prop_name!r} on {owner!r}.",
                Neo4jSchemaWarning,
                stacklevel=2,
            )
            continue
        rows.append(_property_row(owner_key, owner, prop_name, meta))
    return rows


def _endpoint_rows(label: str, rel_type: str, rel_meta: dict) -> list[dict]:
    """Build endpoint rows for one relationship entry, oriented by ``direction``."""
    direction = rel_meta.get("direction")
    rows = []
    for other in rel_meta.get("labels", []) or []:
        if direction == "in":
            rows.append({"type": rel_type, "source_label": other, "target_label": label})
        else:  # "out" (or unspecified): this label is the source
            rows.append({"type": rel_type, "source_label": label, "target_label": other})
    return rows


def _warn_reserved(kind: str, name: str) -> None:
    """Warn that a reserved LPG label / relationship type is being excluded."""
    warnings.warn(
        f"Skipping reserved LPG {kind} {name!r}: it belongs to neocarta's own graph "
        "vocabulary, which the Neo4j connector reserves and never ingests as source "
        "schema (so repeated ingestion stays idempotent even when the source and target "
        "are the same database). If the source genuinely uses this name, its objects "
        "are not ingested (reserved namespace).",
        Neo4jSchemaWarning,
        stacklevel=3,
    )


def _flatten_schema(schema_map: dict, cache: SchemaExtractorCache) -> None:
    """Flatten an ``apoc.meta.schema()`` map into the extractor cache frames.

    APOC reports schema per single label / relationship type. Each ``type == "node"``
    entry yields a node-label row plus its properties (with ``unique`` / ``indexed`` /
    ``existence`` flags) and its relationship endpoints; each ``type == "relationship"``
    entry yields a relationship-type row plus its properties.

    Labels and relationship types in neocarta's own LPG vocabulary
    (``RESERVED_NODE_LABELS`` / ``RESERVED_RELATIONSHIP_TYPES``) are always excluded —
    together with any endpoint row touching them. The Neo4j connector reserves this
    vocabulary unconditionally: when the source and target are the same database (which
    they always are on single-database editions), re-describing neocarta's own metadata
    would otherwise break ingest idempotency. A source that genuinely uses one of these
    names is indistinguishable from neocarta's metadata and is dropped (reserved
    namespace).

    Args:
        schema_map: The value returned by ``CALL apoc.meta.schema()``.
        cache: The extractor cache to populate in place.
    """
    nodes: list[dict] = []
    rels: list[dict] = []
    node_props: list[dict] = []
    rel_props: list[dict] = []
    endpoints: list[dict] = []

    for name, entry in schema_map.items():
        if not isinstance(entry, dict):
            warnings.warn(
                f"Skipping malformed apoc.meta.schema() entry for {name!r}.",
                Neo4jSchemaWarning,
                stacklevel=2,
            )
            continue
        kind = entry.get("type")
        properties = entry.get("properties", {})
        if not isinstance(properties, dict):
            properties = {}
        if kind == "node":
            if name in RESERVED_NODE_LABELS:
                _warn_reserved("node label", name)
                continue
            nodes.append({"label": name})
            node_props.extend(_property_rows("label", name, properties))
            relationships = entry.get("relationships", {})
            if not isinstance(relationships, dict):
                warnings.warn(
                    f"Skipping malformed relationships on {name!r}.",
                    Neo4jSchemaWarning,
                    stacklevel=2,
                )
                relationships = {}
            for rel_type, rel_meta in relationships.items():
                if isinstance(rel_meta, dict):
                    endpoints.extend(_endpoint_rows(name, rel_type, rel_meta))
        elif kind == "relationship":
            if name in RESERVED_RELATIONSHIP_TYPES:
                _warn_reserved("relationship type", name)
                continue
            rels.append({"type": name})
            rel_props.extend(_property_rows("rel_type", name, properties))

    # Drop endpoint rows referencing reserved vocabulary. A reserved node entry is
    # skipped above (so its own edges never reach here), but a genuine source node in a
    # shared database can still point at a reserved-label node or use a reserved
    # relationship type; those edges have no emitted Node/Relationship to attach to.
    endpoints = [
        e
        for e in endpoints
        if e["type"] not in RESERVED_RELATIONSHIP_TYPES
        and e["source_label"] not in RESERVED_NODE_LABELS
        and e["target_label"] not in RESERVED_NODE_LABELS
    ]

    cache["node_info"] = pd.DataFrame(nodes, columns=["label"])
    cache["relationship_info"] = pd.DataFrame(rels, columns=["type"])
    cache["node_property_info"] = pd.DataFrame(
        node_props, columns=["label", "property", "type", "unique", "indexed", "existence"]
    )
    cache["relationship_property_info"] = pd.DataFrame(
        rel_props, columns=["rel_type", "property", "type", "unique", "indexed", "existence"]
    )
    cache["relationship_endpoint_info"] = (
        pd.DataFrame(endpoints, columns=["type", "source_label", "target_label"])
        .drop_duplicates()
        .reset_index(drop=True)
    )


class Neo4jSchemaExtractor:
    """Read a source Neo4j database's schema into cached DataFrames via APOC."""

    def __init__(self, source_neo4j_driver: Driver | None, source_name: str) -> None:
        """Initialize the extractor.

        Args:
            source_neo4j_driver: Driver for the SOURCE Neo4j to introspect.
            source_name: Caller-supplied name identifying the source DBMS (the
                Database node identity).
        """
        self.source_neo4j_driver = source_neo4j_driver
        self.source_name = source_name
        self._cache: SchemaExtractorCache = {}

    def _read(self, query: str, source_database: str) -> list[dict]:
        """Run a READ query against the source and return row dicts (no data logged)."""
        return self.source_neo4j_driver.execute_query(
            query_=query,
            routing_=RoutingControl.READ,
            database_=source_database,
            result_transformer_=lambda r: [rec.data() for rec in r],
        )

    def _ensure_apoc(self, source_database: str) -> None:
        """Pre-flight: the source must expose the ``apoc.meta.schema`` procedure.

        Checks procedure existence via ``SHOW PROCEDURES`` rather than catching an
        error, so a genuine privilege failure (which raises) propagates to
        ``wrap_neo4j_errors`` as an ``ExtractionError`` instead of being misreported
        as a missing plugin.
        """
        rows = self._read(
            "SHOW PROCEDURES YIELD name WHERE name = 'apoc.meta.schema' RETURN count(*) AS c",
            source_database,
        )
        if not rows or rows[0].get("c", 0) < 1:
            raise ConfigError(
                "APOC (Core) is required on the source Neo4j but 'apoc.meta.schema' was not found.",
                suggestion="Install the APOC (Core) plugin on the source Neo4j instance.",
            )

    # --- property accessors ---
    @property
    def database_info(self) -> pd.DataFrame:
        """Return cached database seed info (or an empty frame)."""
        return self._cache.get("database_info", pd.DataFrame())

    @property
    def schema_info(self) -> pd.DataFrame:
        """Return cached schema seed info (or an empty frame)."""
        return self._cache.get("schema_info", pd.DataFrame())

    @property
    def node_info(self) -> pd.DataFrame:
        """Return cached node-label info (or an empty frame)."""
        return self._cache.get("node_info", pd.DataFrame())

    @property
    def relationship_info(self) -> pd.DataFrame:
        """Return cached relationship-type info (or an empty frame)."""
        return self._cache.get("relationship_info", pd.DataFrame())

    @property
    def node_property_info(self) -> pd.DataFrame:
        """Return cached node-property info (or an empty frame)."""
        return self._cache.get("node_property_info", pd.DataFrame())

    @property
    def relationship_property_info(self) -> pd.DataFrame:
        """Return cached relationship-property info (or an empty frame)."""
        return self._cache.get("relationship_property_info", pd.DataFrame())

    @property
    def relationship_endpoint_info(self) -> pd.DataFrame:
        """Return cached relationship-endpoint info (or an empty frame)."""
        return self._cache.get("relationship_endpoint_info", pd.DataFrame())

    # --- extract methods ---
    @log_stage(count=False)
    def extract_database_info(self, source_database: str = "neo4j") -> pd.DataFrame:
        """Build the Database/Schema seed rows from source_name + source_database."""
        db = pd.DataFrame([{"source_name": self.source_name}])
        schema = pd.DataFrame([{"source_name": self.source_name, "database": source_database}])
        self._cache["database_info"] = db
        self._cache["schema_info"] = schema
        return db

    @wrap_neo4j_errors
    @log_stage
    def extract_schema(self, source_database: str = "neo4j") -> pd.DataFrame:
        """Read the source schema via ``apoc.meta.schema()`` and flatten into caches.

        Populates node_info, relationship_info, node_property_info,
        relationship_property_info, and relationship_endpoint_info from the single
        APOC map. neocarta's own reserved LPG vocabulary is always excluded (see
        ``_flatten_schema``). Raises ``ConfigError`` (via ``_ensure_apoc``) when the
        source lacks APOC.

        Args:
            source_database: The source database to introspect.

        Returns:
            The node-property frame (for the ``@log_stage`` row count).
        """
        self._ensure_apoc(source_database)
        rows = self._read("CALL apoc.meta.schema() YIELD value RETURN value", source_database)
        if not rows or "value" not in rows[0]:
            raise TransformError(
                "Unexpected apoc.meta.schema() result shape (no 'value' returned).",
                suggestion="Check the APOC version on the source Neo4j.",
            )
        schema_map = rows[0]["value"]
        if not isinstance(schema_map, dict):
            raise TransformError("Unexpected apoc.meta.schema() 'value' shape (not a map).")
        _flatten_schema(schema_map, self._cache)
        if self._cache["node_info"].empty:
            warnings.warn(
                "Source database has no node labels; only Database/Schema will be written.",
                Neo4jSchemaWarning,
                stacklevel=2,
            )
        return self._cache.get("node_property_info", pd.DataFrame())
