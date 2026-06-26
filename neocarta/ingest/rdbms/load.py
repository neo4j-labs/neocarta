"""Common ingest functions for Neo4j."""

import logging
from functools import partial

from neo4j import Driver, RoutingControl

from ...data_model.glossary import (
    BusinessTerm,
    Category,
    Glossary,
    HasBusinessTerm,
    HasCategory,
    TaggedWith,
)
from ...data_model.governance import (
    GovernanceTag,
    GovernanceTagKey,
    GovernanceTagValue,
    HasDefinition,
    HasValueOption,
    TaggedWithGovernanceTag,
)
from ...data_model.instance import HasValue, Value
from ...data_model.metadata import NeocartaGraph
from ...data_model.query import CTE, Defines, Query, UsesColumn, UsesTable
from ...data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from ...enums import NodeLabel, RelationshipType
from ..indexes import create_full_text_index, create_name_range_index
from ..metadata import upsert_neocarta_graph_node
from ..utils import (
    _build_node_ingest_query,
    _build_relationship_ingest_query,
    _node_pattern,
    _relationship_pattern,
    _validate_properties_list,
    write_neo4j_constraints,
)
from .constraints import KEY_CONSTRAINTS_LOOKUP, UNIQUE_CONSTRAINTS_LOOKUP

logger = logging.getLogger(__name__)


class Neo4jRDBMSLoader:
    """
    Loader class for loading RDBMS metadata into Neo4j.
    Loads nodes and relationships into Neo4j.
    """

    def __init__(self, neo4j_driver: Driver, database_name: str = "neo4j") -> None:
        """Initialize the Neo4j loader."""
        self.neo4j_driver = neo4j_driver
        self.database_name = database_name

        self._write_node_constraint = partial(
            write_neo4j_constraints,
            neo4j_driver=self.neo4j_driver,
            key_constraints=KEY_CONSTRAINTS_LOOKUP,
            unique_constraints=UNIQUE_CONSTRAINTS_LOOKUP,
            database_name=self.database_name,
        )

        self._create_full_text_index = partial(
            create_full_text_index,
            neo4j_driver=self.neo4j_driver,
            database_name=self.database_name,
        )

        self._create_name_range_index = partial(
            create_name_range_index,
            neo4j_driver=self.neo4j_driver,
            database_name=self.database_name,
        )

    def _run_write(self, cypher: str, rows: list[dict], *, pattern: str | None = None) -> dict:
        """
        Execute a write Cypher against the configured database and return counters.

        When ``pattern`` is supplied, the graph pattern written and the Neo4j
        merge counters are logged (INFO: pattern + created/properties_set;
        DEBUG: the full counters dict). The pattern string is the only place a
        label/relationship-type is surfaced — no row data or Cypher text is
        logged.

        Parameters
        ----------
        cypher : str
            The write Cypher to execute.
        rows : list[dict]
            The ``$rows`` parameter for the UNWIND-based ingest query.
        pattern : str, optional
            Human-readable graph pattern for the log line, e.g.
            ``"(:Column)-[:TAGGED_WITH]->(:BusinessTerm)"``.

        Returns:
        -------
        dict
            The Neo4j summary counters.
        """
        _, summary, _ = self.neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"rows": rows},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        counters = summary.counters
        if pattern is not None:
            if logger.isEnabledFor(logging.INFO):
                created = counters.nodes_created or counters.relationships_created
                logger.info(
                    "Ingested %s — created %s, properties_set %s",
                    pattern,
                    created,
                    counters.properties_set,
                )
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Merge counters for %s: %s", pattern, counters.__dict__)
        return counters.__dict__

    def load_database_nodes(
        self,
        database_nodes: list[Database],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "service", "platform"],
        create_name_index: bool = True,
    ) -> dict:
        """Load Database nodes into Neo4j."""
        _validate_properties_list(Database, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.DATABASE])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.DATABASE)
        query = _build_node_ingest_query(NodeLabel.DATABASE, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in database_nodes],
            pattern=_node_pattern(NodeLabel.DATABASE),
        )

    def load_schema_nodes(
        self,
        schema_nodes: list[Schema],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load Schema nodes into Neo4j."""
        _validate_properties_list(Schema, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.SCHEMA])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.SCHEMA)
        if create_full_text_index:
            self._create_full_text_index(node_labels=[NodeLabel.SCHEMA])
        query = _build_node_ingest_query(NodeLabel.SCHEMA, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in schema_nodes],
            pattern=_node_pattern(NodeLabel.SCHEMA),
        )

    def load_table_nodes(
        self,
        table_nodes: list[Table],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load Table nodes into Neo4j."""
        _validate_properties_list(Table, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.TABLE])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.TABLE)
        if create_full_text_index:
            self._create_full_text_index(node_labels=[NodeLabel.TABLE])
        query = _build_node_ingest_query(NodeLabel.TABLE, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in table_nodes],
            pattern=_node_pattern(NodeLabel.TABLE),
        )

    def load_column_nodes(
        self,
        column_nodes: list[Column],
        overwrite_existing: bool = False,
        properties_list: list[str] = [
            "name",
            "description",
            "type",
            "nullable",
            "is_primary_key",
            "is_foreign_key",
        ],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load Column nodes into Neo4j."""
        _validate_properties_list(Column, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.COLUMN])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.COLUMN)
        if create_full_text_index:
            self._create_full_text_index(node_labels=[NodeLabel.COLUMN])
        query = _build_node_ingest_query(NodeLabel.COLUMN, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in column_nodes],
            pattern=_node_pattern(NodeLabel.COLUMN),
        )

    def load_value_nodes(
        self,
        value_nodes: list[Value],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["value"],
    ) -> dict:
        """Load Value nodes into Neo4j."""
        _validate_properties_list(Value, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.VALUE])
        query = _build_node_ingest_query(NodeLabel.VALUE, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in value_nodes],
            pattern=_node_pattern(NodeLabel.VALUE),
        )

    def load_has_schema_relationships(
        self,
        has_schema_relationships: list[HasSchema],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load HAS_SCHEMA relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(HasSchema, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_SCHEMA,
            NodeLabel.DATABASE,
            NodeLabel.SCHEMA,
            "database_id",
            "schema_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_schema_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_SCHEMA, NodeLabel.DATABASE, NodeLabel.SCHEMA
            ),
        )

    def load_has_table_relationships(
        self,
        has_table_relationships: list[HasTable],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load HAS_TABLE relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(HasTable, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_TABLE,
            NodeLabel.SCHEMA,
            NodeLabel.TABLE,
            "schema_id",
            "table_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_table_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_TABLE, NodeLabel.SCHEMA, NodeLabel.TABLE
            ),
        )

    def load_has_column_relationships(
        self,
        has_column_relationships: list[HasColumn],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load HAS_COLUMN relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(HasColumn, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_COLUMN,
            NodeLabel.TABLE,
            NodeLabel.COLUMN,
            "table_id",
            "column_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_column_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_COLUMN, NodeLabel.TABLE, NodeLabel.COLUMN
            ),
        )

    def load_references_relationships(
        self,
        references_relationships: list[References],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["criteria"],
    ) -> dict:
        """Load REFERENCES relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(References, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.REFERENCES,
            NodeLabel.COLUMN,
            NodeLabel.COLUMN,
            "source_column_id",
            "target_column_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in references_relationships],
            pattern=_relationship_pattern(
                RelationshipType.REFERENCES, NodeLabel.COLUMN, NodeLabel.COLUMN
            ),
        )

    def load_glossary_nodes(
        self,
        glossary_nodes: list[Glossary],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_name_index: bool = True,
    ) -> dict:
        """Load Glossary nodes into Neo4j."""
        _validate_properties_list(Glossary, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.GLOSSARY])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.GLOSSARY)
        query = _build_node_ingest_query(NodeLabel.GLOSSARY, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in glossary_nodes],
            pattern=_node_pattern(NodeLabel.GLOSSARY),
        )

    def load_category_nodes(
        self,
        category_nodes: list[Category],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_name_index: bool = True,
    ) -> dict:
        """Load Category nodes into Neo4j."""
        _validate_properties_list(Category, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.CATEGORY])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.CATEGORY)
        query = _build_node_ingest_query(NodeLabel.CATEGORY, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in category_nodes],
            pattern=_node_pattern(NodeLabel.CATEGORY),
        )

    def load_business_term_nodes(
        self,
        business_term_nodes: list[BusinessTerm],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load BusinessTerm nodes into Neo4j."""
        _validate_properties_list(BusinessTerm, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.BUSINESS_TERM])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.BUSINESS_TERM)
        if create_full_text_index:
            self._create_full_text_index(node_labels=[NodeLabel.BUSINESS_TERM])
        query = _build_node_ingest_query(
            NodeLabel.BUSINESS_TERM, overwrite_existing, properties_list
        )

        return self._run_write(
            query,
            [n.model_dump() for n in business_term_nodes],
            pattern=_node_pattern(NodeLabel.BUSINESS_TERM),
        )

    def load_has_category_relationships(
        self,
        has_category_relationships: list[HasCategory],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load HAS_CATEGORY relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(HasCategory, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_CATEGORY,
            NodeLabel.GLOSSARY,
            NodeLabel.CATEGORY,
            "glossary_id",
            "category_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_category_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_CATEGORY, NodeLabel.GLOSSARY, NodeLabel.CATEGORY
            ),
        )

    def load_has_business_term_relationships(
        self,
        has_business_term_relationships: list[HasBusinessTerm],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load HAS_BUSINESS_TERM relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(HasBusinessTerm, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_BUSINESS_TERM,
            NodeLabel.CATEGORY,
            NodeLabel.BUSINESS_TERM,
            "category_id",
            "business_term_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_business_term_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_BUSINESS_TERM, NodeLabel.CATEGORY, NodeLabel.BUSINESS_TERM
            ),
        )

    def load_column_tagged_with_relationships(
        self,
        tagged_with_relationships: list[TaggedWith],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load TAGGED_WITH relationships from Column nodes into Neo4j."""
        if properties_list:
            _validate_properties_list(TaggedWith, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.TAGGED_WITH,
            NodeLabel.COLUMN,
            NodeLabel.BUSINESS_TERM,
            "source_id",
            "business_term_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in tagged_with_relationships],
            pattern=_relationship_pattern(
                RelationshipType.TAGGED_WITH, NodeLabel.COLUMN, NodeLabel.BUSINESS_TERM
            ),
        )

    def load_table_tagged_with_relationships(
        self,
        tagged_with_relationships: list[TaggedWith],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load TAGGED_WITH relationships from Table nodes into Neo4j."""
        if properties_list:
            _validate_properties_list(TaggedWith, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.TAGGED_WITH,
            NodeLabel.TABLE,
            NodeLabel.BUSINESS_TERM,
            "source_id",
            "business_term_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in tagged_with_relationships],
            pattern=_relationship_pattern(
                RelationshipType.TAGGED_WITH, NodeLabel.TABLE, NodeLabel.BUSINESS_TERM
            ),
        )

    def load_governance_tag_key_nodes(
        self,
        governance_tag_key_nodes: list[GovernanceTagKey],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
        create_full_text_index: bool = True,
        create_name_index: bool = True,
    ) -> dict:
        """Load GovernanceTagKey nodes into Neo4j.

        The full-text index over (name, description) makes the tag key the
        agent-searchable surface for the governance layer.
        """
        _validate_properties_list(GovernanceTagKey, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.GOVERNANCE_TAG_KEY])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.GOVERNANCE_TAG_KEY)
        if create_full_text_index:
            self._create_full_text_index(node_labels=[NodeLabel.GOVERNANCE_TAG_KEY])
        query = _build_node_ingest_query(
            NodeLabel.GOVERNANCE_TAG_KEY, overwrite_existing, properties_list
        )

        return self._run_write(
            query,
            [n.model_dump() for n in governance_tag_key_nodes],
            pattern=_node_pattern(NodeLabel.GOVERNANCE_TAG_KEY),
        )

    def load_governance_tag_value_nodes(
        self,
        governance_tag_value_nodes: list[GovernanceTagValue],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name"],
        create_name_index: bool = True,
    ) -> dict:
        """Load GovernanceTagValue nodes into Neo4j.

        Defaults to name-only: governance-tag values carry no description on most
        platforms (Databricks/Snowflake), so the connector writes ``name`` alone.
        Pass ``properties_list=["name", "description"]`` for a source (e.g. GCP)
        whose values do carry descriptions.
        """
        _validate_properties_list(GovernanceTagValue, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.GOVERNANCE_TAG_VALUE])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.GOVERNANCE_TAG_VALUE)
        query = _build_node_ingest_query(
            NodeLabel.GOVERNANCE_TAG_VALUE, overwrite_existing, properties_list
        )

        return self._run_write(
            query,
            [n.model_dump() for n in governance_tag_value_nodes],
            pattern=_node_pattern(NodeLabel.GOVERNANCE_TAG_VALUE),
        )

    def load_governance_tag_nodes(
        self,
        governance_tag_nodes: list[GovernanceTag],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["key", "value"],
    ) -> dict:
        """Load GovernanceTag (assignment) nodes into Neo4j."""
        _validate_properties_list(GovernanceTag, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.GOVERNANCE_TAG])
        query = _build_node_ingest_query(
            NodeLabel.GOVERNANCE_TAG, overwrite_existing, properties_list
        )

        return self._run_write(
            query,
            [n.model_dump() for n in governance_tag_nodes],
            pattern=_node_pattern(NodeLabel.GOVERNANCE_TAG),
        )

    def load_has_value_option_relationships(
        self,
        has_value_option_relationships: list[HasValueOption],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:GovernanceTagKey)-[:HAS_VALUE_OPTION]->(:GovernanceTagValue) relationships."""
        if properties_list:
            _validate_properties_list(HasValueOption, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_VALUE_OPTION,
            NodeLabel.GOVERNANCE_TAG_KEY,
            NodeLabel.GOVERNANCE_TAG_VALUE,
            "governance_tag_key_id",
            "governance_tag_value_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_value_option_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_VALUE_OPTION,
                NodeLabel.GOVERNANCE_TAG_KEY,
                NodeLabel.GOVERNANCE_TAG_VALUE,
            ),
        )

    def load_has_definition_relationships(
        self,
        has_definition_relationships: list[HasDefinition],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:GovernanceTag)-[:HAS_DEFINITION]->(:GovernanceTagValue) relationships."""
        if properties_list:
            _validate_properties_list(HasDefinition, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_DEFINITION,
            NodeLabel.GOVERNANCE_TAG,
            NodeLabel.GOVERNANCE_TAG_VALUE,
            "governance_tag_id",
            "governance_tag_value_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_definition_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_DEFINITION,
                NodeLabel.GOVERNANCE_TAG,
                NodeLabel.GOVERNANCE_TAG_VALUE,
            ),
        )

    def load_column_tagged_with_governance_tag_relationships(
        self,
        tagged_with_relationships: list[TaggedWithGovernanceTag],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Column)-[:TAGGED_WITH]->(:GovernanceTag) relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(TaggedWithGovernanceTag, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.TAGGED_WITH,
            NodeLabel.COLUMN,
            NodeLabel.GOVERNANCE_TAG,
            "source_id",
            "governance_tag_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in tagged_with_relationships],
            pattern=_relationship_pattern(
                RelationshipType.TAGGED_WITH, NodeLabel.COLUMN, NodeLabel.GOVERNANCE_TAG
            ),
        )

    def load_table_tagged_with_governance_tag_relationships(
        self,
        tagged_with_relationships: list[TaggedWithGovernanceTag],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Table)-[:TAGGED_WITH]->(:GovernanceTag) relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(TaggedWithGovernanceTag, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.TAGGED_WITH,
            NodeLabel.TABLE,
            NodeLabel.GOVERNANCE_TAG,
            "source_id",
            "governance_tag_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in tagged_with_relationships],
            pattern=_relationship_pattern(
                RelationshipType.TAGGED_WITH, NodeLabel.TABLE, NodeLabel.GOVERNANCE_TAG
            ),
        )

    def load_schema_tagged_with_governance_tag_relationships(
        self,
        tagged_with_relationships: list[TaggedWithGovernanceTag],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Schema)-[:TAGGED_WITH]->(:GovernanceTag) relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(TaggedWithGovernanceTag, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.TAGGED_WITH,
            NodeLabel.SCHEMA,
            NodeLabel.GOVERNANCE_TAG,
            "source_id",
            "governance_tag_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in tagged_with_relationships],
            pattern=_relationship_pattern(
                RelationshipType.TAGGED_WITH, NodeLabel.SCHEMA, NodeLabel.GOVERNANCE_TAG
            ),
        )

    def load_has_value_relationships(
        self,
        has_value_relationships: list[HasValue],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load HAS_VALUE relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(HasValue, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.HAS_VALUE,
            NodeLabel.COLUMN,
            NodeLabel.VALUE,
            "column_id",
            "value_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in has_value_relationships],
            pattern=_relationship_pattern(
                RelationshipType.HAS_VALUE, NodeLabel.COLUMN, NodeLabel.VALUE
            ),
        )

    def load_query_nodes(
        self,
        query_nodes: list[Query],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["content"],
    ) -> dict:
        """Load Query nodes into Neo4j."""
        _validate_properties_list(Query, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.QUERY])
        query = _build_node_ingest_query(NodeLabel.QUERY, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in query_nodes],
            pattern=_node_pattern(NodeLabel.QUERY),
        )

    def load_cte_nodes(
        self,
        cte_nodes: list[CTE],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "definition", "query_id"],
        create_name_index: bool = True,
    ) -> dict:
        """Load CTE nodes into Neo4j."""
        _validate_properties_list(CTE, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.CTE])
        if create_name_index:
            self._create_name_range_index(node_label=NodeLabel.CTE)
        query = _build_node_ingest_query(NodeLabel.CTE, overwrite_existing, properties_list)

        return self._run_write(
            query,
            [n.model_dump() for n in cte_nodes],
            pattern=_node_pattern(NodeLabel.CTE),
        )

    def load_defines_relationships(
        self,
        defines_relationships: list[Defines],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load (:Query)-[:DEFINES]->(:CTE) relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(Defines, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.DEFINES,
            NodeLabel.QUERY,
            NodeLabel.CTE,
            "query_id",
            "cte_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in defines_relationships],
            pattern=_relationship_pattern(RelationshipType.DEFINES, NodeLabel.QUERY, NodeLabel.CTE),
        )

    def load_uses_table_relationships(
        self,
        uses_table_relationships: list[UsesTable],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load USES_TABLE relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(UsesTable, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.USES_TABLE,
            NodeLabel.QUERY,
            NodeLabel.TABLE,
            "query_id",
            "table_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in uses_table_relationships],
            pattern=_relationship_pattern(
                RelationshipType.USES_TABLE, NodeLabel.QUERY, NodeLabel.TABLE
            ),
        )

    def upsert_neocarta_graph_node(self, version: str | None = None) -> NeocartaGraph:
        """
        Create or update the singleton ``__neocarta_graph__`` metadata node.

        Connectors should invoke this once per run so that the graph carries an
        up-to-date record of which neocarta version last wrote to it.

        Parameters
        ----------
        version: str, optional
            Override the recorded neocarta version. Defaults to the installed
            ``neocarta`` package version; explicit overrides should be reserved
            for tests.

        Returns:
        -------
        NeocartaGraph
            The current state of the metadata node after the upsert.
        """
        return upsert_neocarta_graph_node(
            neo4j_driver=self.neo4j_driver,
            database_name=self.database_name,
            version=version,
        )

    def load_uses_column_relationships(
        self,
        uses_column_relationships: list[UsesColumn],
        overwrite_existing: bool = False,
        properties_list: list[str] = [],
    ) -> dict:
        """Load USES_COLUMN relationships into Neo4j."""
        if properties_list:
            _validate_properties_list(UsesColumn, properties_list)

        query = _build_relationship_ingest_query(
            RelationshipType.USES_COLUMN,
            NodeLabel.QUERY,
            NodeLabel.COLUMN,
            "query_id",
            "column_id",
            overwrite_existing,
            properties_list,
        )

        return self._run_write(
            query,
            [n.model_dump() for n in uses_column_relationships],
            pattern=_relationship_pattern(
                RelationshipType.USES_COLUMN, NodeLabel.QUERY, NodeLabel.COLUMN
            ),
        )
