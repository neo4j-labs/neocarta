"""Transform JDBC schema metadata into graph nodes and relationships.

Mirrors the BigQuery schema transformer: it consumes the extractor's pandas
DataFrame caches and builds ``data_model`` objects, routing every id through
``neocarta.connectors.utils.generate_id`` (never inline f-strings).
"""

import pandas as pd

from ....data_model.rdbms import (
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


class JdbcSchemaTransformer:
    """Transformer for JDBC schema metadata.

    Builds ``Database`` / ``Schema`` / ``Table`` / ``Column`` nodes and
    ``HAS_SCHEMA`` / ``HAS_TABLE`` / ``HAS_COLUMN`` / ``REFERENCES``
    relationships. SchemaCrawler does not sample data, so no ``Value`` nodes
    are produced.
    """

    def __init__(self) -> None:
        """Initialize the JDBC schema transformer."""
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

    def transform_to_database_nodes(
        self, database_info: pd.DataFrame, cache: bool = True
    ) -> list[Database]:
        """
        Transform JDBC database information into database nodes.

        Parameters
        ----------
        database_info: pd.DataFrame
            A Pandas DataFrame with column `database_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[Database]
            The database nodes.
        """
        database_nodes = [
            Database(
                id=generate_database_id(row.database_name),
                name=row.database_name,
                description=None,
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
        Transform JDBC schema information into schema nodes.

        Parameters
        ----------
        schema_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name`, `schema_name`, and `description`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[Schema]
            The schema nodes.
        """
        schema_nodes = [
            Schema(
                id=generate_schema_id(row.database_name, row.schema_name),
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
        Transform JDBC table information into table nodes.

        Parameters
        ----------
        table_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name`, `schema_name`, `table_name`,
            and `description`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[Table]
            The table nodes.
        """
        table_nodes = [
            Table(
                id=generate_table_id(row.database_name, row.schema_name, row.table_name),
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
        Transform JDBC column information into column nodes.

        Parameters
        ----------
        column_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name`, `schema_name`, `table_name`,
            `column_name`, `type`, `nullable`, `description`, `is_primary_key`, and
            `is_foreign_key`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[Column]
            The column nodes.
        """
        column_nodes = [
            Column(
                id=generate_column_id(
                    row.database_name,
                    row.schema_name,
                    row.table_name,
                    row.column_name,
                ),
                name=row.column_name,
                description=row.description,
                type=row.type,
                nullable=row.nullable,
                is_primary_key=row.is_primary_key,
                is_foreign_key=row.is_foreign_key,
            )
            for _, row in column_info.iterrows()
        ]

        if cache:
            self._node_cache["column_nodes"] = column_nodes

        return column_nodes

    def transform_to_has_schema_relationships(
        self, schema_info: pd.DataFrame, cache: bool = True
    ) -> list[HasSchema]:
        """
        Transform JDBC schema information into has schema relationships.

        Parameters
        ----------
        schema_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name` and `schema_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasSchema]
            The has schema relationships.
        """
        has_schema_relationships = [
            HasSchema(
                database_id=generate_database_id(row.database_name),
                schema_id=generate_schema_id(row.database_name, row.schema_name),
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
        Transform JDBC table information into has table relationships.

        Parameters
        ----------
        table_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name`, `schema_name`, and `table_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasTable]
            The has table relationships.
        """
        has_table_relationships = [
            HasTable(
                schema_id=generate_schema_id(row.database_name, row.schema_name),
                table_id=generate_table_id(row.database_name, row.schema_name, row.table_name),
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
        Transform JDBC column information into has column relationships.

        Parameters
        ----------
        column_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name`, `schema_name`, `table_name`,
            and `column_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[HasColumn]
            The has column relationships.
        """
        has_column_relationships = [
            HasColumn(
                table_id=generate_table_id(row.database_name, row.schema_name, row.table_name),
                column_id=generate_column_id(
                    row.database_name,
                    row.schema_name,
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
        Transform JDBC foreign-key information into references relationships.

        Parameters
        ----------
        column_references_info: pd.DataFrame
            A Pandas DataFrame with columns `database_name`, `source_schema_name`,
            `source_table_name`, `source_column_name`, `target_schema_name`,
            `target_table_name`, and `target_column_name`.
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[References]
            The references relationships.
        """
        references_relationships = []
        for _, row in column_references_info.iterrows():
            source_column_id = generate_column_id(
                row.database_name,
                row.source_schema_name,
                row.source_table_name,
                row.source_column_name,
            )
            target_column_id = generate_column_id(
                row.database_name,
                row.target_schema_name,
                row.target_table_name,
                row.target_column_name,
            )
            # Skip bogus self-FKs (a column referencing itself is never a real
            # foreign key); mirrors the BigQuery transformer's guard.
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
