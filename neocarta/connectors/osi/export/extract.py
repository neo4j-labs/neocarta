"""Extract an OSI semantic model subgraph from Neo4j."""

import json
from typing import Any

from neo4j import Driver


class OsiGraphExtractor:
    """
    Read an OSI semantic model from Neo4j by name and return a structured snapshot
    that the export transformer can serialize back to OSI YAML.

    The snapshot is keyed close to the OSI YAML shape so the transformer step is
    largely a YAML serialization with minor reshaping.

    Parameters
    ----------
    driver : neo4j.Driver
        Connected Neo4j driver.
    database_name : str, default "neo4j"
        Target Neo4j database.
    """

    def __init__(self, driver: Driver, database_name: str = "neo4j") -> None:
        """Initialize the extractor with a Neo4j driver and target database name."""
        self.driver = driver
        self.database_name = database_name
        self.snapshot: dict[str, Any] | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def extract(self, semantic_model_name: str) -> dict[str, Any]:
        """
        Read the OSI semantic model with the given ``name`` from Neo4j.

        Parameters
        ----------
        semantic_model_name : str
            Matches against :OsiSemanticModel.name.

        Returns:
        -------
        dict[str, Any]
            A snapshot shaped close to the OSI YAML format: top-level keys
            ``name``, ``description``, ``osi_version``, ``ai_context``,
            ``custom_extensions``, ``datasets``, ``relationships``, ``metrics``.
            Cached on the instance as :attr:`snapshot`.

        Raises:
        ------
        ValueError
            If no OsiSemanticModel with the given name is found.
        """
        with self.driver.session(database=self.database_name) as session:
            sm = self._read_semantic_model(session, semantic_model_name)
            if sm is None:
                raise ValueError(f"No OsiSemanticModel found with name {semantic_model_name!r}")

            aspects_by_parent = self._read_aspects(session, sm["id"])
            sm_ai_context, sm_custom_extensions = self._partition_aspects(
                aspects_by_parent.get(sm["id"], [])
            )

            tables = self._read_tables(session, sm["id"], aspects_by_parent)
            queries = self._read_queries(session, sm["id"], aspects_by_parent)
            datasets = self._merge_datasets(session, tables, queries, aspects_by_parent)

            relationships = self._read_relationships(session, sm["id"], aspects_by_parent)
            metrics = self._read_metrics(session, sm["id"], aspects_by_parent)

        snapshot: dict[str, Any] = {
            "name": sm["name"],
            "description": sm.get("description"),
            "osi_version": sm.get("osi_version"),
            "ai_context": sm_ai_context,
            "custom_extensions": sm_custom_extensions,
            "datasets": datasets,
            "relationships": relationships,
            "metrics": metrics,
        }
        self.snapshot = snapshot
        return snapshot

    # ------------------------------------------------------------------ #
    # Cypher reads
    # ------------------------------------------------------------------ #

    def _read_semantic_model(self, session: Any, name: str) -> dict[str, Any] | None:
        """Read the OsiSemanticModel root node by name."""
        cypher = (
            "MATCH (sm:OsiSemanticModel {name: $name}) "
            "RETURN sm.id AS id, sm.name AS name, sm.description AS description, "
            "sm.osi_version AS osi_version "
            "LIMIT 1"
        )
        record = session.run(cypher, name=name).single()
        return dict(record) if record else None

    def _read_aspects(self, session: Any, sm_id: str) -> dict[str, list[dict[str, Any]]]:
        """
        Read all aspects attached to entities within the semantic model.

        Returns a mapping ``parent_id -> [aspect dict, ...]``. Each aspect dict has
        ``id``, ``data``, ``vendor_name``, and ``labels`` (the Neo4j label list,
        used to distinguish OsiAiContext vs OsiCustomExtensions in the transformer).
        """
        cypher = """
        MATCH (sm:OsiSemanticModel {id: $sm_id})
        CALL {
            WITH sm
            MATCH (sm)-[:HAS_ASPECT]->(a:Aspect)
            RETURN sm.id AS parent_id, a
            UNION
            WITH sm
            MATCH (sm)-[:HAS_TABLE|HAS_QUERY]->(owner)-[:HAS_ASPECT]->(a:Aspect)
            RETURN owner.id AS parent_id, a
            UNION
            WITH sm
            MATCH (sm)-[:HAS_TABLE|HAS_QUERY]->(owner)-[:HAS_COLUMN]->(c:Column)-[:HAS_ASPECT]->(a:Aspect)
            RETURN c.id AS parent_id, a
            UNION
            WITH sm
            MATCH (sm)-[:HAS_METRIC]->(m:Metric)-[:HAS_ASPECT]->(a:Aspect)
            RETURN m.id AS parent_id, a
            UNION
            WITH sm
            MATCH (sm)-[:HAS_TABLE|HAS_QUERY]->(owner)
            MATCH (j:Join)-[:HAS_SOURCE_TABLE|HAS_TARGET_TABLE]->(owner)
            MATCH (j)-[:HAS_ASPECT]->(a:Aspect)
            RETURN j.id AS parent_id, a
        }
        RETURN DISTINCT parent_id,
               a.id AS aspect_id, a.data AS data, a.vendor_name AS vendor_name,
               labels(a) AS labels
        """
        result = session.run(cypher, sm_id=sm_id)
        aspects_by_parent: dict[str, list[dict[str, Any]]] = {}
        for record in result:
            parent_id = record["parent_id"]
            aspects_by_parent.setdefault(parent_id, []).append(
                {
                    "id": record["aspect_id"],
                    "data": record["data"],
                    "vendor_name": record["vendor_name"],
                    "labels": list(record["labels"] or []),
                }
            )
        return aspects_by_parent

    def _read_tables(
        self,
        session: Any,
        sm_id: str,
        aspects_by_parent: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Read Table datasets (OsiTable nodes) owned by the semantic model."""
        cypher = (
            "MATCH (sm:OsiSemanticModel {id: $sm_id})-[:HAS_TABLE]->(t:Table) "
            "RETURN t.id AS id, t.name AS name, t.source AS source, "
            "t.description AS description, t.primary_key AS primary_key, "
            "t.unique_keys AS unique_keys"
        )
        tables: list[dict[str, Any]] = []
        for record in session.run(cypher, sm_id=sm_id):
            ai, customs = self._partition_aspects(aspects_by_parent.get(record["id"], []))
            # ``unique_keys`` is JSON-encoded at load time because Neo4j can't
            # store nested lists as property values; decode back to a list of lists.
            unique_keys_raw = record["unique_keys"]
            unique_keys: list[list[str]] | None
            if unique_keys_raw is None:
                unique_keys = None
            else:
                try:
                    unique_keys = json.loads(unique_keys_raw)
                except (ValueError, json.JSONDecodeError):
                    unique_keys = None
            tables.append(
                {
                    "kind": "table",
                    "id": record["id"],
                    "name": record["name"],
                    "source": record["source"],
                    "description": record["description"],
                    "primary_key": list(record["primary_key"] or []) or None,
                    "unique_keys": unique_keys,
                    "ai_context": ai,
                    "custom_extensions": customs,
                }
            )
        return tables

    def _read_queries(
        self,
        session: Any,
        sm_id: str,
        aspects_by_parent: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Read Query datasets owned by the semantic model."""
        cypher = (
            "MATCH (sm:OsiSemanticModel {id: $sm_id})-[:HAS_QUERY]->(q:Query) "
            "RETURN q.id AS id, q.name AS name, q.content AS content, "
            "q.description AS description"
        )
        queries: list[dict[str, Any]] = []
        for record in session.run(cypher, sm_id=sm_id):
            ai, customs = self._partition_aspects(aspects_by_parent.get(record["id"], []))
            queries.append(
                {
                    "kind": "query",
                    "id": record["id"],
                    "name": record["name"],
                    "source": record["content"],
                    "description": record["description"],
                    "ai_context": ai,
                    "custom_extensions": customs,
                }
            )
        return queries

    def _merge_datasets(
        self,
        session: Any,
        tables: list[dict[str, Any]],
        queries: list[dict[str, Any]],
        aspects_by_parent: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Combine tables and queries into a single datasets list, each with its fields."""
        all_owners = tables + queries
        owner_ids = [o["id"] for o in all_owners]
        if not owner_ids:
            return []

        fields_by_owner = self._read_fields(session, owner_ids, aspects_by_parent)

        merged: list[dict[str, Any]] = []
        for owner in all_owners:
            owner_id = owner["id"]
            entry: dict[str, Any] = {
                "name": owner["name"],
                "source": owner["source"],
                "description": owner["description"],
                "ai_context": owner["ai_context"],
                "custom_extensions": owner["custom_extensions"],
                "fields": fields_by_owner.get(owner_id, []),
            }
            if owner["kind"] == "table":
                entry["primary_key"] = owner.get("primary_key")
                entry["unique_keys"] = owner.get("unique_keys")
            merged.append(entry)
        return merged

    def _read_fields(
        self,
        session: Any,
        owner_ids: list[str],
        aspects_by_parent: dict[str, list[dict[str, Any]]],
    ) -> dict[str, list[dict[str, Any]]]:
        """
        Read column rows for the given owner ids and group by owner.

        Table-backed datasets attach columns via ``:HAS_COLUMN``; query-backed
        datasets attach via ``:USES_COLUMN`` (matching the query_log connector's
        existing semantics). The Cypher matches either rel type so both flavors
        of OSI dataset return their fields uniformly.
        """
        cypher = (
            "UNWIND $owner_ids AS owner_id "
            "MATCH (owner {id: owner_id})-[:HAS_COLUMN|USES_COLUMN]->(c:Column) "
            "OPTIONAL MATCH (c)-[:HAS_EXPRESSION]->(e:Expression) "
            "WITH owner_id, c, "
            "collect(DISTINCT CASE WHEN e IS NOT NULL "
            "    THEN {dialect: e.dialect, expression: e.expression} END) AS expressions "
            "RETURN owner_id, c.id AS column_id, c.name AS name, c.label AS label, "
            "c.description AS description, c.is_primary_key AS is_primary_key, "
            "c.is_foreign_key AS is_foreign_key, c.is_time_dimension AS is_time_dimension, "
            "expressions"
        )
        result = session.run(cypher, owner_ids=owner_ids)
        fields_by_owner: dict[str, list[dict[str, Any]]] = {}
        for record in result:
            ai, customs = self._partition_aspects(aspects_by_parent.get(record["column_id"], []))
            expressions = [e for e in (record["expressions"] or []) if e is not None]
            fields_by_owner.setdefault(record["owner_id"], []).append(
                {
                    "id": record["column_id"],
                    "name": record["name"],
                    "label": record["label"],
                    "description": record["description"],
                    "is_primary_key": bool(record["is_primary_key"]),
                    "is_foreign_key": bool(record["is_foreign_key"]),
                    # Preserve None — Neo4j returns missing properties as None,
                    # and the export transformer treats None as "no dimension key".
                    "is_time_dimension": record["is_time_dimension"],
                    "expressions": expressions,
                    "ai_context": ai,
                    "custom_extensions": customs,
                }
            )
        return fields_by_owner

    def _read_relationships(
        self,
        session: Any,
        sm_id: str,
        aspects_by_parent: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """
        Read OSI relationships (Join nodes) whose source and target are both owned
        by this semantic model. Returns one entry per Join with resolved dataset
        names and the ordered column pairs participating in the join.

        ``from_columns`` and ``to_columns`` come from the Join node's own properties
        (populated at ingest time) so positional pairing for composite-key joins is
        preserved. We don't try to recover order from USED_IN_JOIN edges — Cypher's
        ``collect`` doesn't guarantee order, and USED_IN_JOIN has no position field.
        """
        cypher = """
        MATCH (sm:OsiSemanticModel {id: $sm_id})-[:HAS_TABLE|HAS_QUERY]->(src)
        MATCH (sm)-[:HAS_TABLE|HAS_QUERY]->(tgt)
        MATCH (j:Join)-[:HAS_SOURCE_TABLE]->(src)
        MATCH (j)-[:HAS_TARGET_TABLE]->(tgt)
        RETURN j.id AS id, j.name AS name, src.name AS from_dataset,
               tgt.name AS to_dataset,
               j.from_columns AS from_columns,
               j.to_columns AS to_columns
        """
        result = session.run(cypher, sm_id=sm_id)
        relationships: list[dict[str, Any]] = []
        for record in result:
            _, customs = self._partition_aspects(aspects_by_parent.get(record["id"], []))
            relationships.append(
                {
                    "name": record["name"],
                    "from": record["from_dataset"],
                    "to": record["to_dataset"],
                    "from_columns": list(record["from_columns"] or []),
                    "to_columns": list(record["to_columns"] or []),
                    "custom_extensions": customs,
                }
            )
        return relationships

    def _read_metrics(
        self,
        session: Any,
        sm_id: str,
        aspects_by_parent: dict[str, list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        """Read Metric nodes owned by the semantic model, with their expressions."""
        cypher = """
        MATCH (sm:OsiSemanticModel {id: $sm_id})-[:HAS_METRIC]->(m:Metric)
        OPTIONAL MATCH (m)-[:HAS_EXPRESSION]->(e:Expression)
        WITH m,
             collect(DISTINCT CASE WHEN e IS NOT NULL
                 THEN {dialect: e.dialect, expression: e.expression} END) AS expressions
        RETURN m.id AS id, m.name AS name, m.description AS description, expressions
        """
        result = session.run(cypher, sm_id=sm_id)
        metrics: list[dict[str, Any]] = []
        for record in result:
            ai, customs = self._partition_aspects(aspects_by_parent.get(record["id"], []))
            expressions = [e for e in (record["expressions"] or []) if e is not None]
            metrics.append(
                {
                    "name": record["name"],
                    "description": record["description"],
                    "expressions": expressions,
                    "ai_context": ai,
                    "custom_extensions": customs,
                }
            )
        return metrics

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _partition_aspects(
        aspects: list[dict[str, Any]],
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """
        Split aspect dicts into (ai_context_payload, custom_extensions_list).

        OSI YAML carries one ``ai_context`` string per entity, but the graph can
        have at most one OsiAiContext per content hash. If multiple distinct
        OsiAiContext nodes are linked from the same entity, only the first is
        returned (this is rare given content-addressed ids).
        """
        ai_context: str | None = None
        customs: list[dict[str, Any]] = []
        for aspect in aspects:
            labels = aspect.get("labels") or []
            if "OsiAiContext" in labels:
                if ai_context is None:
                    ai_context = aspect.get("data")
            elif "OsiCustomExtensions" in labels:
                customs.append(
                    {
                        "vendor_name": aspect.get("vendor_name"),
                        "data": aspect.get("data"),
                    }
                )
        return ai_context, customs
