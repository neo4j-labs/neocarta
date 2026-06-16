"""Transform open Unity Catalog REST metadata into schema graph nodes/relationships."""

from ....data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    Schema,
    Table,
)
from ...utils.generate_id import (
    generate_column_id,
    generate_database_id,
    generate_schema_id,
    generate_table_id,
)
from .models import CatalogInfo, ColumnInfo, SchemaInfo, TableInfo


class UnityCatalogSchemaTransformer:
    """Transformer producing Database/Schema/Table/Column nodes + HAS_* edges from UC data."""

    def __init__(self) -> None:
        """Initialize empty node and relationship caches."""
        self.database_nodes: list[Database] = []
        self.schema_nodes: list[Schema] = []
        self.table_nodes: list[Table] = []
        self.column_nodes: list[Column] = []
        self.has_schema_relationships: list[HasSchema] = []
        self.has_table_relationships: list[HasTable] = []
        self.has_column_relationships: list[HasColumn] = []

    def transform_to_database_nodes(self, catalog_info: list[CatalogInfo]) -> list[Database]:
        """Build :Database nodes from one row per catalog."""
        nodes = [
            Database(
                id=generate_database_id(row["catalog_name"]),
                name=row["catalog_name"],
                description=row["comment"],
                service="UNITY_CATALOG",
                platform="DATABRICKS",
            )
            for row in catalog_info
        ]
        self.database_nodes = nodes
        return nodes

    def transform_to_schema_nodes(self, schema_info: list[SchemaInfo]) -> list[Schema]:
        """Build :Schema nodes from one row per (catalog, schema)."""
        nodes = [
            Schema(
                id=generate_schema_id(row["catalog_name"], row["schema_name"]),
                name=row["schema_name"],
                description=row["comment"],
            )
            for row in schema_info
        ]
        self.schema_nodes = nodes
        return nodes

    def transform_to_table_nodes(self, table_info: list[TableInfo]) -> list[Table]:
        """Build :Table nodes from one row per (catalog, schema, table). Views fold in here."""
        nodes = [
            Table(
                id=generate_table_id(row["catalog_name"], row["schema_name"], row["table_name"]),
                name=row["table_name"],
                description=row["comment"],
            )
            for row in table_info
        ]
        self.table_nodes = nodes
        return nodes

    def transform_to_column_nodes(self, column_info: list[ColumnInfo]) -> list[Column]:
        """Build :Column nodes from one row per (catalog, schema, table, column).

        The open Unity Catalog API exposes no key/constraint metadata, so
        ``is_primary_key`` and ``is_foreign_key`` are always ``False``.
        """
        nodes = [
            Column(
                id=generate_column_id(
                    row["catalog_name"],
                    row["schema_name"],
                    row["table_name"],
                    row["column_name"],
                ),
                name=row["column_name"],
                description=row["comment"],
                type=row["column_type"],
                nullable=row["nullable"],
                is_primary_key=False,
                is_foreign_key=False,
            )
            for row in column_info
        ]
        self.column_nodes = nodes
        return nodes

    def transform_to_has_schema_relationships(
        self, schema_info: list[SchemaInfo]
    ) -> list[HasSchema]:
        """Build (:Database)-[:HAS_SCHEMA]->(:Schema) edges."""
        rels = [
            HasSchema(
                database_id=generate_database_id(row["catalog_name"]),
                schema_id=generate_schema_id(row["catalog_name"], row["schema_name"]),
            )
            for row in schema_info
        ]
        self.has_schema_relationships = rels
        return rels

    def transform_to_has_table_relationships(self, table_info: list[TableInfo]) -> list[HasTable]:
        """Build (:Schema)-[:HAS_TABLE]->(:Table) edges."""
        rels = [
            HasTable(
                schema_id=generate_schema_id(row["catalog_name"], row["schema_name"]),
                table_id=generate_table_id(
                    row["catalog_name"], row["schema_name"], row["table_name"]
                ),
            )
            for row in table_info
        ]
        self.has_table_relationships = rels
        return rels

    def transform_to_has_column_relationships(
        self, column_info: list[ColumnInfo]
    ) -> list[HasColumn]:
        """Build (:Table)-[:HAS_COLUMN]->(:Column) edges."""
        rels = [
            HasColumn(
                table_id=generate_table_id(
                    row["catalog_name"], row["schema_name"], row["table_name"]
                ),
                column_id=generate_column_id(
                    row["catalog_name"],
                    row["schema_name"],
                    row["table_name"],
                    row["column_name"],
                ),
            )
            for row in column_info
        ]
        self.has_column_relationships = rels
        return rels
