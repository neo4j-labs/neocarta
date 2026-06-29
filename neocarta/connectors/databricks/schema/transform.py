"""Transform Databricks Unity Catalog schema metadata into graph nodes and relationships."""

import pandas as pd

from ....data_model.instance import HasValue, Value
from ....data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from ...models import NodesCache, RelationshipsCache
from ...utils.generate_id import (
    generate_column_id,
    generate_database_id,
    generate_schema_id,
    generate_table_id,
)


class DatabricksSchemaTransformer:
    """
    Transformer for Databricks Unity Catalog schema metadata.
    Transforms ``information_schema`` frames into core data-model nodes and relationships.
    """

    def __init__(self) -> None:
        """Initialize the Databricks transformer."""
        self._node_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()

    @property
    def database_nodes(self) -> list[Database]:
        """
        Get the database nodes.
        (:Database).
        """
        return self._node_cache.get("database_nodes", [])

    @property
    def schema_nodes(self) -> list[Schema]:
        """
        Get the schema nodes.
        (:Schema).
        """
        return self._node_cache.get("schema_nodes", [])

    @property
    def table_nodes(self) -> list[Table]:
        """
        Get the table nodes.
        (:Table).
        """
        return self._node_cache.get("table_nodes", [])

    @property
    def column_nodes(self) -> list[Column]:
        """
        Get the column nodes.
        (:Column).
        """
        return self._node_cache.get("column_nodes", [])

    @property
    def value_nodes(self) -> list[Value]:
        """
        Get the value nodes.
        (:Value).
        """
        return self._node_cache.get("value_nodes", [])

    @property
    def has_schema_relationships(self) -> list[HasSchema]:
        """
        Get the has schema relationships.
        (:Database)-[:HAS_SCHEMA]->(:Schema).
        """
        return self._relationships_cache.get("has_schema_relationships", [])

    @property
    def has_table_relationships(self) -> list[HasTable]:
        """
        Get the has table relationships.
        (:Schema)-[:HAS_TABLE]->(:Table).
        """
        return self._relationships_cache.get("has_table_relationships", [])

    @property
    def has_column_relationships(self) -> list[HasColumn]:
        """
        Get the has column relationships.
        (:Table)-[:HAS_COLUMN]->(:Column).
        """
        return self._relationships_cache.get("has_column_relationships", [])

    @property
    def references_relationships(self) -> list[References]:
        """
        Get the references relationships.
        (:Column)-[:REFERENCES]->(:Column).
        """
        return self._relationships_cache.get("references_relationships", [])

    @property
    def has_value_relationships(self) -> list[HasValue]:
        """
        Get the has value relationships.
        (:Column)-[:HAS_VALUE]->(:Value).
        """
        return self._relationships_cache.get("has_value_relationships", [])

    def transform_to_database_nodes(
        self, database_info: pd.DataFrame, cache: bool = True
    ) -> list[Database]:
        """
        Transform Databricks database (catalog) information into database nodes.

        Parameters
        ----------
        database_info: pd.DataFrame
            A Pandas DataFrame containing the catalog information. Has column `catalog`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the database nodes in the instance.

        Returns:
        -------
        list[Database]
            The database nodes.
        """
        database_nodes = [
            Database(
                id=generate_database_id(row.catalog),
                name=row.catalog,
                description=None,
                platform="DATABRICKS",
                service="UNITY_CATALOG",
            )
            for _, row in database_info.iterrows()
        ]

        if cache:
            self._node_cache["database_nodes"] = database_nodes

        return database_nodes

    def transform_to_schema_nodes(
        self, schema_info: pd.DataFrame, cache: bool = True
    ) -> list[Schema]:
        """
        Transform Databricks schema information into schema nodes.

        Parameters
        ----------
        schema_info: pd.DataFrame
            A Pandas DataFrame containing the schema information.
            Has columns `catalog_name`, `schema_name`, and `description`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the schema nodes in the instance.

        Returns:
        -------
        list[Schema]
            The schema nodes.
        """
        schema_nodes = [
            Schema(
                id=generate_schema_id(row.catalog_name, row.schema_name),
                name=row.schema_name,
                description=row.description,
            )
            for _, row in schema_info.iterrows()
        ]

        if cache:
            self._node_cache["schema_nodes"] = schema_nodes

        return schema_nodes

    def transform_to_table_nodes(self, table_info: pd.DataFrame, cache: bool = True) -> list[Table]:
        """
        Transform Databricks table information into table nodes.

        Parameters
        ----------
        table_info: pd.DataFrame
            A Pandas DataFrame containing the table information.
            Has columns `table_catalog`, `table_schema`, `table_name`, and `description`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the table nodes in the instance.

        Returns:
        -------
        list[Table]
            The table nodes.
        """
        table_nodes = [
            Table(
                id=generate_table_id(row.table_catalog, row.table_schema, row.table_name),
                name=row.table_name,
                description=row.description,
            )
            for _, row in table_info.iterrows()
        ]

        if cache:
            self._node_cache["table_nodes"] = table_nodes

        return table_nodes

    def transform_to_column_nodes(
        self, column_info: pd.DataFrame, cache: bool = True
    ) -> list[Column]:
        """
        Transform Databricks column information into column nodes.

        Parameters
        ----------
        column_info: pd.DataFrame
            A Pandas DataFrame containing the column information. Has columns
            `table_catalog`, `table_schema`, `table_name`, `column_name`, `is_nullable`,
            `data_type`, `description`, `is_primary_key`, and `is_foreign_key`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the column nodes in the instance.

        Returns:
        -------
        list[Column]
            The column nodes.
        """
        column_nodes = [
            Column(
                id=generate_column_id(
                    row.table_catalog,
                    row.table_schema,
                    row.table_name,
                    row.column_name,
                ),
                name=row.column_name,
                description=row.description,
                type=row.data_type,
                nullable=row.is_nullable,
                is_primary_key=row.is_primary_key,
                is_foreign_key=row.is_foreign_key,
            )
            for _, row in column_info.iterrows()
        ]

        if cache:
            self._node_cache["column_nodes"] = column_nodes

        return column_nodes

    def transform_to_value_nodes(self, value_info: pd.DataFrame, cache: bool = True) -> list[Value]:
        """
        Transform Databricks value information into value nodes.

        Parameters
        ----------
        value_info: pd.DataFrame
            A Pandas DataFrame containing the value information. Has columns `value_id`
            and `unique_value`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the value nodes in the instance.

        Returns:
        -------
        list[Value]
            The value nodes.
        """
        value_nodes = [
            Value(
                id=row.value_id,
                value=row.unique_value,
            )
            for _, row in value_info.iterrows()
        ]

        if cache:
            self._node_cache["value_nodes"] = value_nodes

        return value_nodes

    def transform_to_has_schema_relationships(
        self, schema_info: pd.DataFrame, cache: bool = True
    ) -> list[HasSchema]:
        """
        Transform Databricks schema information into has schema relationships.

        Parameters
        ----------
        schema_info: pd.DataFrame
            A Pandas DataFrame containing the schema information.
            Has columns `catalog_name` and `schema_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasSchema]
            The has schema relationships.
        """
        has_schema_relationships = [
            HasSchema(
                database_id=generate_database_id(row.catalog_name),
                schema_id=generate_schema_id(row.catalog_name, row.schema_name),
            )
            for _, row in schema_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_schema_relationships"] = has_schema_relationships

        return has_schema_relationships

    def transform_to_has_table_relationships(
        self, table_info: pd.DataFrame, cache: bool = True
    ) -> list[HasTable]:
        """
        Transform Databricks table information into has table relationships.

        Parameters
        ----------
        table_info: pd.DataFrame
            A Pandas DataFrame containing the table information.
            Has columns `table_catalog`, `table_schema`, and `table_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasTable]
            The has table relationships.
        """
        has_table_relationships = [
            HasTable(
                schema_id=generate_schema_id(row.table_catalog, row.table_schema),
                table_id=generate_table_id(row.table_catalog, row.table_schema, row.table_name),
            )
            for _, row in table_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_table_relationships"] = has_table_relationships

        return has_table_relationships

    def transform_to_has_column_relationships(
        self, column_info: pd.DataFrame, cache: bool = True
    ) -> list[HasColumn]:
        """
        Transform Databricks column information into has column relationships.

        Parameters
        ----------
        column_info: pd.DataFrame
            A Pandas DataFrame containing the column information.
            Has columns `table_catalog`, `table_schema`, `table_name`, and `column_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasColumn]
            The has column relationships.
        """
        has_column_relationships = [
            HasColumn(
                table_id=generate_table_id(row.table_catalog, row.table_schema, row.table_name),
                column_id=generate_column_id(
                    row.table_catalog,
                    row.table_schema,
                    row.table_name,
                    row.column_name,
                ),
            )
            for _, row in column_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_column_relationships"] = has_column_relationships

        return has_column_relationships

    def transform_to_references_relationships(
        self, column_references_info: pd.DataFrame, cache: bool = True
    ) -> list[References]:
        """
        Transform Databricks column references information into references relationships.

        Parameters
        ----------
        column_references_info: pd.DataFrame
            A Pandas DataFrame containing the column references information. Has columns
            `constraint_catalog`, `constraint_schema`, `constraint_type`, `table_name`,
            `column_name`, `referenced_table`, and `referenced_column`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[References]
            The references relationships.
        """
        fk_rows = column_references_info[column_references_info["constraint_type"] == "FOREIGN KEY"]

        references_relationships = []
        for _, row in fk_rows.iterrows():
            source_column_id = generate_column_id(
                row.constraint_catalog,
                row.constraint_schema,
                row.table_name,
                row.column_name,
            )
            target_column_id = generate_column_id(
                row.constraint_catalog,
                row.constraint_schema,
                row.referenced_table,
                row.referenced_column,
            )
            # Skip bogus self-FKs (a column referencing itself) — a quirk of how
            # INFORMATION_SCHEMA constraint joins can collapse when both sides
            # resolve to the same column.
            if source_column_id == target_column_id:
                continue
            references_relationships.append(
                References(
                    source_column_id=source_column_id,
                    target_column_id=target_column_id,
                )
            )

        if cache:
            self._relationships_cache["references_relationships"] = references_relationships

        return references_relationships

    def transform_to_has_value_relationships(
        self, value_info: pd.DataFrame, cache: bool = True
    ) -> list[HasValue]:
        """
        Transform Databricks value information into has value relationships.

        Parameters
        ----------
        value_info: pd.DataFrame
            A Pandas DataFrame containing the value information.
            Must have columns `column_id` and `value_id`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasValue]
            The has value relationships.
        """
        has_value_relationships = [
            HasValue(
                column_id=row.column_id,
                value_id=row.value_id,
            )
            for _, row in value_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_value_relationships"] = has_value_relationships

        return has_value_relationships
