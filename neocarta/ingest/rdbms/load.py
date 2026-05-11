"""Common ingest functions for Neo4j."""

from functools import partial

from neo4j import Driver, RoutingControl

from ...data_model.rdbms import (
    CTE,
    BusinessTerm,
    Category,
    Column,
    Database,
    Defines,
    Glossary,
    HasBusinessTerm,
    HasCategory,
    HasColumn,
    HasSchema,
    HasTable,
    HasValue,
    Query,
    References,
    Schema,
    Table,
    TaggedWith,
    UsesColumn,
    UsesTable,
    Value,
)
from ...enums import NodeLabel, RelationshipType
from ..utils import (
    _build_node_ingest_query,
    _build_relationship_ingest_query,
    _validate_properties_list,
    write_neo4j_constraints,
)
from .constraints import KEY_CONSTRAINTS_LOOKUP, UNIQUE_CONSTRAINTS_LOOKUP


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

    def load_database_nodes(
        self,
        database_nodes: list[Database],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description", "service", "platform"],
    ) -> dict:
        """Load Database nodes into Neo4j."""
        _validate_properties_list(Database, properties_list)
        self._write_node_constraint(node_labels=[NodeLabel.DATABASE])
        query = _build_node_ingest_query(NodeLabel.DATABASE, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in database_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )

        return summary.counters.__dict__

    def load_schema_nodes(
        self,
        schema_nodes: list[Schema],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
    ) -> dict:
        """Load Schema nodes into Neo4j."""
        _validate_properties_list(Schema, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.SCHEMA])
        query = _build_node_ingest_query(NodeLabel.SCHEMA, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in schema_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

    def load_table_nodes(
        self,
        table_nodes: list[Table],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
    ) -> dict:
        """Load Table nodes into Neo4j."""
        _validate_properties_list(Table, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.TABLE])
        query = _build_node_ingest_query(NodeLabel.TABLE, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in table_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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
    ) -> dict:
        """Load Column nodes into Neo4j."""
        _validate_properties_list(Column, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.COLUMN])
        query = _build_node_ingest_query(NodeLabel.COLUMN, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in column_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in value_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in has_schema_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in has_table_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in has_column_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in references_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

    def load_glossary_nodes(
        self,
        glossary_nodes: list[Glossary],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
    ) -> dict:
        """Load Glossary nodes into Neo4j."""
        _validate_properties_list(Glossary, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.GLOSSARY])
        query = _build_node_ingest_query(NodeLabel.GLOSSARY, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in glossary_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

    def load_category_nodes(
        self,
        category_nodes: list[Category],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
    ) -> dict:
        """Load Category nodes into Neo4j."""
        _validate_properties_list(Category, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.CATEGORY])
        query = _build_node_ingest_query(NodeLabel.CATEGORY, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in category_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

    def load_business_term_nodes(
        self,
        business_term_nodes: list[BusinessTerm],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "description"],
    ) -> dict:
        """Load BusinessTerm nodes into Neo4j."""
        _validate_properties_list(BusinessTerm, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.BUSINESS_TERM])
        query = _build_node_ingest_query(
            NodeLabel.BUSINESS_TERM, overwrite_existing, properties_list
        )

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in business_term_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in has_category_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in has_business_term_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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
            "entity_id",
            "business_term_id",
            overwrite_existing,
            properties_list,
        )

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in tagged_with_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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
            "entity_id",
            "business_term_id",
            overwrite_existing,
            properties_list,
        )

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in tagged_with_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in has_value_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in query_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

    def load_cte_nodes(
        self,
        cte_nodes: list[CTE],
        overwrite_existing: bool = False,
        properties_list: list[str] = ["name", "definition", "query_id"],
    ) -> dict:
        """Load CTE nodes into Neo4j."""
        _validate_properties_list(CTE, properties_list)

        self._write_node_constraint(node_labels=[NodeLabel.CTE])
        query = _build_node_ingest_query(NodeLabel.CTE, overwrite_existing, properties_list)

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in cte_nodes]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in defines_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in uses_table_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__

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

        _, summary, _ = self.neo4j_driver.execute_query(
            query_=query,
            parameters_={"rows": [n.model_dump() for n in uses_column_relationships]},
            routing_=RoutingControl.WRITE,
            database_=self.database_name,
        )
        return summary.counters.__dict__
