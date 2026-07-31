"""Extract Neo4j schema metadata via APOC (apoc.meta.schema)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd
from neo4j import RoutingControl
from neo4j.exceptions import ClientError

from ...._logging import log_stage
from ....errors import ConfigError
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


def _flatten_schema(schema_map: dict, cache: SchemaExtractorCache) -> None:
    """Flatten an ``apoc.meta.schema()`` map into the extractor cache frames.

    APOC reports schema per single label / relationship type. Each ``type == "node"``
    entry yields a node-label row plus its properties (with ``unique`` / ``indexed`` /
    ``existence`` flags) and its relationship endpoints; each ``type == "relationship"``
    entry yields a relationship-type row plus its properties.

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
        kind = entry.get("type")
        properties = entry.get("properties", {}) or {}
        if kind == "node":
            nodes.append({"label": name})
            for prop_name, meta in properties.items():
                node_props.append(_property_row("label", name, prop_name, meta))
            for rel_type, rel_meta in (entry.get("relationships", {}) or {}).items():
                endpoints.extend(_endpoint_rows(name, rel_type, rel_meta))
        elif kind == "relationship":
            rels.append({"type": name})
            for prop_name, meta in properties.items():
                rel_props.append(_property_row("rel_type", name, prop_name, meta))

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
        """Pre-flight: APOC (Core) must be installed on the source."""
        try:
            self._read("CALL apoc.version()", source_database)
        except ClientError as exc:  # procedure-not-found => APOC absent
            raise ConfigError(
                "APOC (Core) is required on the source Neo4j but was not found.",
                suggestion="Install the APOC (Core) plugin on the source Neo4j instance.",
            ) from exc

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
        APOC map. Raises ``ConfigError`` (via ``_ensure_apoc``) when the source lacks
        APOC.

        Args:
            source_database: The source database to introspect.

        Returns:
            The node-property frame (for the ``@log_stage`` row count).
        """
        self._ensure_apoc(source_database)
        rows = self._read("CALL apoc.meta.schema() YIELD value RETURN value", source_database)
        schema_map = rows[0]["value"] if rows else {}
        _flatten_schema(schema_map, self._cache)
        return self._cache.get("node_property_info", pd.DataFrame())
