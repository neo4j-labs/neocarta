"""Transform query log data into graph nodes and relationships."""

import pandas as pd

from ...data_model.rdbms import (
    CTE,
    Column,
    Database,
    Defines,
    HasColumn,
    HasSchema,
    HasTable,
    Query,
    References,
    Schema,
    Table,
    UsesColumn,
    UsesTable,
)
from ..models import NodesCache, RelationshipsCache
from ..utils.generate_id import generate_database_id


class QueryLogTransformer:
    """Transformer class for query log files."""

    def __init__(self) -> None:
        """Initialize the query log transformer."""
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
    def query_nodes(self) -> list[Query]:
        """
        Get the query nodes.
        (:Query).
        """
        return self._node_cache.get("query_nodes", [])

    @property
    def cte_nodes(self) -> list[CTE]:
        """
        Get the CTE nodes.
        (:CTE).
        """
        return self._node_cache.get("cte_nodes", [])

    @property
    def defines_relationships(self) -> list[Defines]:
        """
        Get the defines relationships.
        (:Query)-[:DEFINES]->(:CTE).
        """
        return self._relationships_cache.get("defines_relationships", [])

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
    def uses_table_relationships(self) -> list[UsesTable]:
        """
        Get the uses table relationships.
        (:Query)-[:USES_TABLE]->(:Table).
        """
        return self._relationships_cache.get("uses_table_relationships", [])

    @property
    def uses_column_relationships(self) -> list[UsesColumn]:
        """
        Get the uses column relationships.
        (:Query)-[:USES_COLUMN]->(:Column).
        """
        return self._relationships_cache.get("uses_column_relationships", [])

    def transform_to_database_nodes(
        self, database_info: pd.DataFrame, cache: bool = True
    ) -> list[Database]:
        """Transform query log database information into database nodes."""
        database_nodes = [
            Database(
                id=generate_database_id(row.project_id),
                name=row.project_name,
                platform=row.platform,
                service=row.service,
            )
            for _, row in database_info.iterrows()
        ]

        if cache:
            self._node_cache["database_nodes"] = database_nodes

        return database_nodes

    def transform_to_schema_nodes(
        self, schema_info: pd.DataFrame, cache: bool = True
    ) -> list[Schema]:
        """Transform query log schema information into schema nodes."""
        schema_nodes = [
            Schema(id=row.dataset_id, name=row.dataset_name) for _, row in schema_info.iterrows()
        ]

        if cache:
            self._node_cache["schema_nodes"] = schema_nodes

        return schema_nodes

    def transform_to_table_nodes(self, table_info: pd.DataFrame, cache: bool = True) -> list[Table]:
        """Transform query log table information into table nodes."""
        table_nodes = [
            Table(id=row.table_id, name=row.table_name) for _, row in table_info.iterrows()
        ]

        if cache:
            self._node_cache["table_nodes"] = table_nodes

        return table_nodes

    def transform_to_column_nodes(
        self, column_info: pd.DataFrame, cache: bool = True
    ) -> list[Column]:
        """Transform query log column information into column nodes."""
        column_nodes = [
            Column(id=row.column_id, name=row.column_name) for _, row in column_info.iterrows()
        ]

        if cache:
            self._node_cache["column_nodes"] = column_nodes

        return column_nodes

    def transform_to_query_nodes(self, query_info: pd.DataFrame, cache: bool = True) -> list[Query]:
        """Transform query log query information into query nodes."""
        query_nodes = [
            Query(id=row.query_id, content=row.query) for _, row in query_info.iterrows()
        ]

        if cache:
            self._node_cache["query_nodes"] = query_nodes

        return query_nodes

    def transform_to_has_schema_relationships(
        self, schema_info: pd.DataFrame, cache: bool = True
    ) -> list[HasSchema]:
        """Transform query log schema information into has schema relationships."""
        has_schema_relationships = [
            HasSchema(database_id=generate_database_id(row.project_id), schema_id=row.dataset_id)
            for _, row in schema_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_schema_relationships"] = has_schema_relationships

        return has_schema_relationships

    def transform_to_has_table_relationships(
        self, table_info: pd.DataFrame, cache: bool = True
    ) -> list[HasTable]:
        """Transform query log table information into has table relationships."""
        has_table_relationships = [
            HasTable(schema_id=row.dataset_id, table_id=row.table_id)
            for _, row in table_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_table_relationships"] = has_table_relationships

        return has_table_relationships

    def transform_to_has_column_relationships(
        self, column_info: pd.DataFrame, cache: bool = True
    ) -> list[HasColumn]:
        """Transform query log column information into has column relationships."""
        has_column_relationships = [
            HasColumn(table_id=row.table_id, column_id=row.column_id)
            for _, row in column_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_column_relationships"] = has_column_relationships

        return has_column_relationships

    def transform_to_references_relationships(
        self, column_references_info: pd.DataFrame, cache: bool = True
    ) -> list[References]:
        """Transform query log column references information into references relationships."""
        references_relationships = [
            References(
                source_column_id=row.left_column_id,
                target_column_id=row.right_column_id,
                criteria=row.criteria,
            )
            for _, row in column_references_info.iterrows()
        ]

        if cache:
            self._relationships_cache["references_relationships"] = references_relationships

        return references_relationships

    def transform_to_uses_table_relationships(
        self, query_table_info: pd.DataFrame, cache: bool = True
    ) -> list[UsesTable]:
        """Transform query log table information into uses table relationships."""
        uses_table_relationships = [
            UsesTable(query_id=row.query_id, table_id=row.table_id)
            for _, row in query_table_info.iterrows()
        ]

        if cache:
            self._relationships_cache["uses_table_relationships"] = uses_table_relationships

        return uses_table_relationships

    def transform_to_cte_nodes(self, cte_info: pd.DataFrame, cache: bool = True) -> list[CTE]:
        """Transform CTE info into CTE nodes."""
        if cte_info is None or cte_info.empty:
            cte_nodes: list[CTE] = []
        else:
            cte_nodes = [
                CTE(
                    id=row.cte_id,
                    name=row.cte_name,
                    definition=row.definition,
                    query_id=row.query_id,
                )
                for _, row in cte_info.iterrows()
            ]

        if cache:
            self._node_cache["cte_nodes"] = cte_nodes

        return cte_nodes

    def transform_to_defines_relationships(
        self, cte_info: pd.DataFrame, cache: bool = True
    ) -> list[Defines]:
        """Transform CTE info into (:Query)-[:DEFINES]->(:CTE) relationships."""
        if cte_info is None or cte_info.empty:
            defines_relationships: list[Defines] = []
        else:
            defines_relationships = [
                Defines(query_id=row.query_id, cte_id=row.cte_id) for _, row in cte_info.iterrows()
            ]

        if cache:
            self._relationships_cache["defines_relationships"] = defines_relationships

        return defines_relationships

    def transform_to_uses_column_relationships(
        self, query_column_info: pd.DataFrame, cache: bool = True
    ) -> list[UsesColumn]:
        """Transform query log column information into uses column relationships."""
        uses_column_relationships = [
            UsesColumn(query_id=row.query_id, column_id=row.column_id)
            for _, row in query_column_info.iterrows()
        ]

        if cache:
            self._relationships_cache["uses_column_relationships"] = uses_column_relationships

        return uses_column_relationships
