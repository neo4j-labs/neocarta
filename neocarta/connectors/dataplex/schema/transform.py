"""Transform Dataplex BigQuery catalog metadata into schema graph nodes/relationships."""

import pandas as pd

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


class DataplexSchemaTransformer:
    """Transformer producing Database/Schema/Table/Column nodes + HAS_* edges from Dataplex catalog data."""

    def __init__(self) -> None:
        """Initialize empty node and relationship caches."""
        self.database_nodes: list[Database] = []
        self.schema_nodes: list[Schema] = []
        self.table_nodes: list[Table] = []
        self.column_nodes: list[Column] = []
        self.has_schema_relationships: list[HasSchema] = []
        self.has_table_relationships: list[HasTable] = []
        self.has_column_relationships: list[HasColumn] = []

    def transform_to_database_nodes(self, database_info: pd.DataFrame) -> list[Database]:
        """Build :Database nodes from one row per project."""
        nodes = [
            Database(
                id=generate_database_id(row.project_id),
                name=row.project_id,
                description=None,
                service=row.service,
                platform=row.platform,
            )
            for _, row in database_info.iterrows()
        ]
        self.database_nodes = nodes
        return nodes

    def transform_to_schema_nodes(self, schema_info: pd.DataFrame) -> list[Schema]:
        """Build :Schema nodes from one row per (project, dataset)."""
        nodes = [
            Schema(
                id=generate_schema_id(row.project_id, row.dataset_id),
                name=row.dataset_id,
                description=None,
            )
            for _, row in schema_info.iterrows()
        ]
        self.schema_nodes = nodes
        return nodes

    def transform_to_table_nodes(self, table_info: pd.DataFrame) -> list[Table]:
        """Build :Table nodes from one row per (project, dataset, table)."""
        nodes = [
            Table(
                id=generate_table_id(row.project_id, row.dataset_id, row.table_id),
                name=row.table_display_name,
                description=row.table_description or None,
            )
            for _, row in table_info.iterrows()
        ]
        self.table_nodes = nodes
        return nodes

    def transform_to_column_nodes(self, column_info: pd.DataFrame) -> list[Column]:
        """Build :Column nodes from one row per (project, dataset, table, column)."""
        nodes = [
            Column(
                id=generate_column_id(
                    row.project_id, row.dataset_id, row.table_id, row.column_name
                ),
                name=row.column_name,
                description=row.column_description,
                type=row.column_data_type,
                nullable=row.column_mode == "NULLABLE",
                is_primary_key=False,
                is_foreign_key=False,
            )
            for _, row in column_info.iterrows()
        ]
        self.column_nodes = nodes
        return nodes

    def transform_to_has_schema_relationships(self, schema_info: pd.DataFrame) -> list[HasSchema]:
        """Build (:Database)-[:HAS_SCHEMA]->(:Schema) edges."""
        rels = [
            HasSchema(
                database_id=generate_database_id(row.project_id),
                schema_id=generate_schema_id(row.project_id, row.dataset_id),
            )
            for _, row in schema_info.iterrows()
        ]
        self.has_schema_relationships = rels
        return rels

    def transform_to_has_table_relationships(self, table_info: pd.DataFrame) -> list[HasTable]:
        """Build (:Schema)-[:HAS_TABLE]->(:Table) edges."""
        rels = [
            HasTable(
                schema_id=generate_schema_id(row.project_id, row.dataset_id),
                table_id=generate_table_id(row.project_id, row.dataset_id, row.table_id),
            )
            for _, row in table_info.iterrows()
        ]
        self.has_table_relationships = rels
        return rels

    def transform_to_has_column_relationships(self, column_info: pd.DataFrame) -> list[HasColumn]:
        """Build (:Table)-[:HAS_COLUMN]->(:Column) edges."""
        rels = [
            HasColumn(
                table_id=generate_table_id(row.project_id, row.dataset_id, row.table_id),
                column_id=generate_column_id(
                    row.project_id, row.dataset_id, row.table_id, row.column_name
                ),
            )
            for _, row in column_info.iterrows()
        ]
        self.has_column_relationships = rels
        return rels
