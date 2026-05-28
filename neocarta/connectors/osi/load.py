"""OSI-specific Neo4j loader extensions.

Adds load methods for OSI node and relationship types on top of the base
:class:`Neo4jRDBMSLoader`. Methods cover:

- Secondary-label node loaders (e.g. ``:Table:OsiTable``).
- Polymorphic-source relationship loaders (HAS_ASPECT, HAS_EXPRESSION).
- BusinessTerm MERGE-on-name for synonyms-derived BTs.
"""

import json

from ...data_model.rdbms import (
    BusinessTerm,
    DomainHasTable,
    Expression,
    HasAspect,
    HasExpression,
    HasMetric,
    HasQuery,
    HasSourceTable,
    HasTargetTable,
    Join,
    Metric,
    OsiAiContext,
    OsiColumn,
    OsiCustomExtensions,
    OsiSemanticModel,
    OsiTable,
    QueryHasColumn,
    TaggedWith,
    UsedInJoin,
)
from ...enums import NodeLabel, RelationshipType
from ...ingest.rdbms.load import Neo4jRDBMSLoader
from ...ingest.utils import (
    _build_node_ingest_query,
    _build_relationship_ingest_query,
    _validate_properties_list,
)


class OsiNeo4jLoader(Neo4jRDBMSLoader):
    """
    Neo4j loader with OSI-specific load methods layered onto :class:`Neo4jRDBMSLoader`.

    Used by :class:`neocarta.connectors.osi.OsiConnector` for both ingest and export
    wiring. Inherits all of the base loader's methods (Database, Schema, Table, etc.)
    and adds OSI node and relationship loaders here.
    """

    # ------------------------------------------------------------------ #
    # Node loaders
    # ------------------------------------------------------------------ #

    def load_osi_semantic_model_nodes(
        self,
        nodes: list[OsiSemanticModel],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "osi_version"],
    ) -> dict:
        """Load OsiSemanticModel nodes (``:Domain:OsiSemanticModel``)."""
        _validate_properties_list(OsiSemanticModel, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.DOMAIN])
        query = _build_node_ingest_query(
            NodeLabel.DOMAIN,
            overwrite_existing,
            properties_list,
            secondary_labels=[NodeLabel.OSI_SEMANTIC_MODEL],
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_osi_table_nodes(
        self,
        nodes: list[OsiTable],
        overwrite_existing: bool = False,
        properties_list: list[str] = [
            "name",
            "description",
            "source",
            "primary_key",
            "unique_keys",
        ],
    ) -> dict:
        """
        Load OsiTable nodes (``:Table:OsiTable``).

        Neo4j cannot store nested lists as property values, so ``unique_keys``
        (``list[list[str]]``) is JSON-encoded to a single string at write time
        and decoded on export by the graph extractor.
        """
        _validate_properties_list(OsiTable, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.TABLE])
        query = _build_node_ingest_query(
            NodeLabel.TABLE,
            overwrite_existing,
            properties_list,
            secondary_labels=[NodeLabel.OSI_TABLE],
        )
        rows: list[dict] = []
        for node in nodes:
            row = node.model_dump()
            if row.get("unique_keys") is not None:
                row["unique_keys"] = json.dumps(row["unique_keys"])
            rows.append(row)
        return self._run_write(query, rows)

    def load_osi_column_nodes(
        self,
        nodes: list[OsiColumn],
        overwrite_existing: bool = False,
        properties_list: list[str] = [
            "name",
            "description",
            "label",
            "is_primary_key",
            "is_foreign_key",
            "is_time_dimension",
        ],
    ) -> dict:
        """Load OsiColumn nodes (``:Column:OsiColumn``)."""
        _validate_properties_list(OsiColumn, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.COLUMN])
        query = _build_node_ingest_query(
            NodeLabel.COLUMN,
            overwrite_existing,
            properties_list,
            secondary_labels=[NodeLabel.OSI_COLUMN],
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_metric_nodes(
        self,
        nodes: list[Metric],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
    ) -> dict:
        """Load Metric nodes."""
        _validate_properties_list(Metric, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.METRIC])
        query = _build_node_ingest_query(
            NodeLabel.METRIC, overwrite_existing, properties_list
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_join_nodes(
        self,
        nodes: list[Join],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name"],
    ) -> dict:
        """Load Join nodes."""
        _validate_properties_list(Join, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.JOIN])
        query = _build_node_ingest_query(
            NodeLabel.JOIN, overwrite_existing, properties_list
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_expression_nodes(
        self,
        nodes: list[Expression],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["dialect", "expression"],
    ) -> dict:
        """Load Expression nodes."""
        _validate_properties_list(Expression, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.EXPRESSION])
        query = _build_node_ingest_query(
            NodeLabel.EXPRESSION, overwrite_existing, properties_list
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_osi_ai_context_nodes(
        self,
        nodes: list[OsiAiContext],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["data"],
    ) -> dict:
        """Load OsiAiContext aspect nodes (``:Aspect:OsiAiContext``)."""
        _validate_properties_list(OsiAiContext, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.ASPECT])
        query = _build_node_ingest_query(
            NodeLabel.ASPECT,
            overwrite_existing,
            properties_list,
            secondary_labels=[NodeLabel.OSI_AI_CONTEXT],
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_osi_custom_extensions_nodes(
        self,
        nodes: list[OsiCustomExtensions],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["data", "vendor_name"],
    ) -> dict:
        """Load OsiCustomExtensions aspect nodes (``:Aspect:OsiCustomExtensions``)."""
        _validate_properties_list(OsiCustomExtensions, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.ASPECT])
        query = _build_node_ingest_query(
            NodeLabel.ASPECT,
            overwrite_existing,
            properties_list,
            secondary_labels=[NodeLabel.OSI_CUSTOM_EXTENSIONS],
        )
        return self._run_write(query, [n.model_dump() for n in nodes])

    def load_business_term_nodes_by_name(
        self,
        nodes: list[BusinessTerm],
        properties_list: list[str] = ["description"],
    ) -> dict:
        """
        MERGE BusinessTerm nodes on ``name`` rather than ``id``.

        Used for OSI synonyms-derived BTs so they dedupe against catalog BTs
        (e.g. from Dataplex) that share the same name. Existing BTs keep their
        original id; new BTs get the id provided by the OSI ingest transformer.
        """
        _validate_properties_list(BusinessTerm, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.BUSINESS_TERM])
        set_extras = ", ".join(f"n.{p} = row.{p}" for p in properties_list)
        # Only set id on first create — never overwrite an existing BT's id.
        cypher = f"""
UNWIND $rows AS row
MERGE (n:{NodeLabel.BUSINESS_TERM} {{name: row.name}})
ON CREATE SET n.id = row.id{', ' + set_extras if set_extras else ''}
""".strip()
        return self._run_write(cypher, [n.model_dump() for n in nodes])

    # ------------------------------------------------------------------ #
    # Relationship loaders
    # ------------------------------------------------------------------ #

    def load_domain_has_table_relationships(
        self,
        rels: list[DomainHasTable],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """(:Domain)-[:HAS_TABLE]->(:Table)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_TABLE,
            NodeLabel.DOMAIN,
            NodeLabel.TABLE,
            "domain_id",
            "table_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(query, [r.model_dump() for r in rels])

    def load_has_query_relationships(
        self,
        rels: list[HasQuery],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """(:Domain)-[:HAS_QUERY]->(:Query)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_QUERY,
            NodeLabel.DOMAIN,
            NodeLabel.QUERY,
            "domain_id",
            "query_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(query, [r.model_dump() for r in rels])

    def load_query_has_column_relationships(
        self,
        rels: list[QueryHasColumn],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """(:Query)-[:HAS_COLUMN]->(:Column) — shares the rel type with Table→Column."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_COLUMN,
            NodeLabel.QUERY,
            NodeLabel.COLUMN,
            "query_id",
            "column_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(query, [r.model_dump() for r in rels])

    def load_has_metric_relationships(
        self,
        rels: list[HasMetric],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """(:Domain)-[:HAS_METRIC]->(:Metric)."""
        query = _build_relationship_ingest_query(
            RelationshipType.HAS_METRIC,
            NodeLabel.DOMAIN,
            NodeLabel.METRIC,
            "domain_id",
            "metric_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(query, [r.model_dump() for r in rels])

    def load_has_aspect_relationships(self, rels: list[HasAspect]) -> dict:
        """
        Polymorphic source → Aspect: (Domain|Schema|Table|Column|Query|Metric|Join)
        -[:HAS_ASPECT]->(:Aspect).

        Matches the source node by id (no label constraint) so any of the allowed
        source labels resolves correctly.
        """
        cypher = f"""
UNWIND $rows AS row
MATCH (s {{id: row.source_id}})
MATCH (a:{NodeLabel.ASPECT} {{id: row.aspect_id}})
MERGE (s)-[:{RelationshipType.HAS_ASPECT}]->(a)
""".strip()
        return self._run_write(cypher, [r.model_dump() for r in rels])

    def load_has_expression_relationships(
        self, rels: list[HasExpression]
    ) -> dict:
        """
        Polymorphic source → Expression: (Column|Metric)-[:HAS_EXPRESSION]->(:Expression).
        Source matched by id only.
        """
        cypher = f"""
UNWIND $rows AS row
MATCH (s {{id: row.source_id}})
MATCH (e:{NodeLabel.EXPRESSION} {{id: row.expression_id}})
MERGE (s)-[:{RelationshipType.HAS_EXPRESSION}]->(e)
""".strip()
        return self._run_write(cypher, [r.model_dump() for r in rels])

    def load_has_source_table_relationships(
        self, rels: list[HasSourceTable]
    ) -> dict:
        """(:Join)-[:HAS_SOURCE_TABLE]->(:Table) (target matched by id, may be Query)."""
        cypher = f"""
UNWIND $rows AS row
MATCH (j:{NodeLabel.JOIN} {{id: row.join_id}})
MATCH (t {{id: row.table_id}})
MERGE (j)-[:{RelationshipType.HAS_SOURCE_TABLE}]->(t)
""".strip()
        return self._run_write(cypher, [r.model_dump() for r in rels])

    def load_has_target_table_relationships(
        self, rels: list[HasTargetTable]
    ) -> dict:
        """(:Join)-[:HAS_TARGET_TABLE]->(:Table) (target matched by id, may be Query)."""
        cypher = f"""
UNWIND $rows AS row
MATCH (j:{NodeLabel.JOIN} {{id: row.join_id}})
MATCH (t {{id: row.table_id}})
MERGE (j)-[:{RelationshipType.HAS_TARGET_TABLE}]->(t)
""".strip()
        return self._run_write(cypher, [r.model_dump() for r in rels])

    def load_used_in_join_relationships(
        self,
        rels: list[UsedInJoin],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """(:Column)-[:USED_IN_JOIN]->(:Join)."""
        query = _build_relationship_ingest_query(
            RelationshipType.USED_IN_JOIN,
            NodeLabel.COLUMN,
            NodeLabel.JOIN,
            "column_id",
            "join_id",
            overwrite_existing,
            properties_list,
        )
        return self._run_write(query, [r.model_dump() for r in rels])

    def load_osi_tagged_with_relationships(
        self,
        rels: list[TaggedWith],
        business_term_nodes: list[BusinessTerm],
    ) -> dict:
        """
        Polymorphic entity → BusinessTerm: (Column|Table|Schema|Metric)
        -[:TAGGED_WITH]->(:BusinessTerm).

        BusinessTerm is matched by ``name`` rather than ``id``: synonyms-derived
        BTs go through :meth:`load_business_term_nodes_by_name` which MERGEs on
        name, so a pre-existing BT (e.g. from Dataplex) keeps its original id.
        The OSI-derived id we hold in :class:`TaggedWith` may not match what's
        in the graph — looking up by name resolves to the right node either way.

        ``business_term_nodes`` is required so we can resolve each
        ``business_term_id`` back to its name before running the Cypher.
        """
        bt_id_to_name = {bt.id: bt.name for bt in business_term_nodes}
        rows: list[dict] = []
        for rel in rels:
            name = bt_id_to_name.get(rel.business_term_id)
            if name is None:
                continue
            rows.append({"entity_id": rel.entity_id, "business_term_name": name})
        cypher = f"""
UNWIND $rows AS row
MATCH (s {{id: row.entity_id}})
MATCH (b:{NodeLabel.BUSINESS_TERM} {{name: row.business_term_name}})
MERGE (s)-[:{RelationshipType.TAGGED_WITH}]->(b)
""".strip()
        return self._run_write(cypher, rows)
