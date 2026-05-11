"""Transform Dataplex metadata into graph nodes and relationships."""

import pandas as pd

from ...data_model.rdbms import (
    BusinessTerm,
    Category,
    Column,
    Database,
    Glossary,
    HasBusinessTerm,
    HasCategory,
    HasColumn,
    HasSchema,
    HasTable,
    Schema,
    Table,
    TaggedWith,
)
from ..models import NodesCache, RelationshipsCache
from ..utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_column_id,
    generate_database_id,
    generate_glossary_id,
    generate_schema_id,
    generate_table_id,
)
from .utils import parse_business_term_slug, parse_category_slug


class DataplexTransformer:
    """
    Transformer class for Dataplex
    Transforms metadata from Dataplex into data model nodes and relationships.
    """

    def __init__(self) -> None:
        """Initialize empty node and relationship caches."""
        self._nodes_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()

    @property
    def database_nodes(self) -> list[Database]:
        """
        Get the database nodes.
        (:Database).
        """
        return self._nodes_cache.get("database_nodes", [])

    @property
    def schema_nodes(self) -> list[Schema]:
        """
        Get the schema nodes.
        (:Schema).
        """
        return self._nodes_cache.get("schema_nodes", [])

    @property
    def table_nodes(self) -> list[Table]:
        """
        Get the table nodes.
        (:Table).
        """
        return self._nodes_cache.get("table_nodes", [])

    @property
    def column_nodes(self) -> list[Column]:
        """
        Get the column nodes.
        (:Column).
        """
        return self._nodes_cache.get("column_nodes", [])

    @property
    def glossary_nodes(self) -> list[Glossary]:
        """
        Get the glossary nodes.
        (:Glossary).
        """
        return self._nodes_cache.get("glossary_nodes", [])

    @property
    def category_nodes(self) -> list[Category]:
        """
        Get the category nodes.
        (:Category).
        """
        return self._nodes_cache.get("category_nodes", [])

    @property
    def business_term_nodes(self) -> list[BusinessTerm]:
        """
        Get the business term nodes.
        (:BusinessTerm).
        """
        return self._nodes_cache.get("business_term_nodes", [])

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
    def has_category_relationships(self) -> list[HasCategory]:
        """
        Get the has category relationships.
        (:Glossary)-[:HAS_CATEGORY]->(:Category).
        """
        return self._relationships_cache.get("has_category_relationships", [])

    @property
    def column_tagged_with_relationships(self) -> list[TaggedWith]:
        """
        Get tagged with relationships for columns.
        (:Column)-[:TAGGED_WITH]->(:BusinessTerm)
        """  # noqa: D415
        return self._relationships_cache.get("column_tagged_with_relationships", [])

    @property
    def table_tagged_with_relationships(self) -> list[TaggedWith]:
        """
        Get tagged with relationships for tables.
        (:Table)-[:TAGGED_WITH]->(:BusinessTerm)
        """  # noqa: D415
        return self._relationships_cache.get("table_tagged_with_relationships", [])

    @property
    def has_business_term_relationships(self) -> list[HasBusinessTerm]:
        """
        Get the has business term relationships.
        (:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm).
        """
        return self._relationships_cache.get("has_business_term_relationships", [])

    def transform_to_database_nodes(
        self, database_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[Database]:
        """
        Transform Dataplex database metadata into Database nodes.

        Parameters
        ----------
        database_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex database metadata.
            Has columns `project_id`, `service`, and `platform`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the database nodes in the instance.

        Returns:
        -------
        list[Database]
            The database nodes.
        """
        nodes = [
            Database(
                id=generate_database_id(row.project_id),
                name=row.project_id,
                description=None,
                service=row.service,
                platform=row.platform,
            )
            for _, row in database_metadata_info.iterrows()
        ]

        if cache:
            self._nodes_cache["database_nodes"] = nodes

        return nodes

    def transform_to_schema_nodes(
        self, schema_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[Schema]:
        """
        Transform Dataplex schema metadata into Schema nodes.

        Parameters
        ----------
        schema_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex schema metadata.
            Has columns `project_id` and `dataset_id`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the schema nodes in the instance.

        Returns:
        -------
        list[Schema]
            The schema nodes.
        """
        nodes = [
            Schema(
                id=generate_schema_id(row.project_id, row.dataset_id),
                name=row.dataset_id,
                description=None,  # no description in extraction step
            )
            for _, row in schema_metadata_info.iterrows()
        ]

        if cache:
            self._nodes_cache["schema_nodes"] = nodes

        return nodes

    def transform_to_table_nodes(
        self, table_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[Table]:
        """
        Transform Dataplex table metadata into Table nodes.

        Parameters
        ----------
        table_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex table metadata.
            Has columns `project_id`, `dataset_id`, `table_id`, `table_display_name`,
            and `table_description`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the table nodes in the instance.

        Returns:
        -------
        list[Table]
            The table nodes.
        """
        nodes = [
            Table(
                id=generate_table_id(row.project_id, row.dataset_id, row.table_id),
                name=row.table_display_name,
                description=row.table_description or None,
            )
            for _, row in table_metadata_info.iterrows()
        ]

        if cache:
            self._nodes_cache["table_nodes"] = nodes

        return nodes

    def transform_to_column_nodes(
        self, column_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[Column]:
        """
        Transform Dataplex BigQuery metadata into column nodes.

        Parameters
        ----------
        column_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex column metadata.
            Has columns `project_id`, `dataset_id`, `table_id`, `column_name`,
            `column_data_type`, `column_mode`, and `column_description`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the column nodes in the instance.

        Returns:
        -------
        list[Column]
            The column nodes.
        """
        nodes = [
            Column(
                id=generate_column_id(
                    row.project_id, row.dataset_id, row.table_id, row.column_name
                ),
                name=row.column_name,
                description=row.column_description,
                type=row.column_data_type,
                nullable=row.column_mode == "NULLABLE",
                is_primary_key=False,  # no primary key in extraction step
                is_foreign_key=False,  # no foreign key in extraction step
            )
            for _, row in column_metadata_info.iterrows()
        ]

        if cache:
            self._nodes_cache["column_nodes"] = nodes

        return nodes

    def transform_to_glossary_nodes(
        self, glossary_info: pd.DataFrame, cache: bool = True
    ) -> list[Glossary]:
        """
        Transform Dataplex glossary information into glossary nodes.

        Parameters
        ----------
        glossary_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex glossary information.
            Has columns `glossary_id` and `glossary_name`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the glossary nodes in the instance.

        Returns:
        -------
        list[Glossary]
            The glossary nodes.
        """
        nodes = [
            Glossary(
                id=generate_glossary_id(row.glossary_id),
                name=row.glossary_name,
                description=None,  # no description in extraction step
                resource_path=row.glossary_resource_path,
            )
            for _, row in glossary_info.iterrows()
        ]

        if cache:
            self._nodes_cache["glossary_nodes"] = nodes

        return nodes

    def transform_to_category_nodes(
        self, category_info: pd.DataFrame, cache: bool = True
    ) -> list[Category]:
        """
        Transform Dataplex glossary category information into Category nodes.

        Parameters
        ----------
        category_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex glossary information.
            Has columns `glossary_id` and `category_id`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the category nodes in the instance.

        Returns:
        -------
        list[Category]
            The category nodes.
        """
        nodes = [
            Category(
                id=generate_category_id(row.glossary_id, parse_category_slug(row.category_id)),
                name=parse_category_slug(row.category_id),
                description=None,  # no description in extraction step
                resource_path=row.category_id,
            )
            for _, row in category_info.iterrows()
        ]

        if cache:
            self._nodes_cache["category_nodes"] = nodes

        return nodes

    def transform_to_business_term_nodes(
        self, business_term_info: pd.DataFrame, cache: bool = True
    ) -> list[BusinessTerm]:
        """
        Transform Dataplex glossary business term information into BusinessTerm nodes.

        Parameters
        ----------
        business_term_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex glossary information.
            Has columns `term_id`, `term_name`, and `term_description`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the business term nodes in the instance.

        Returns:
        -------
        list[BusinessTerm]
            The business term nodes.
        """
        nodes = [
            BusinessTerm(
                id=generate_business_term_id(
                    row.glossary_id,
                    parse_category_slug(row.category_id),
                    parse_business_term_slug(row.term_id),
                ),
                name=row.term_name,
                description=row.term_description,
                resource_path=row.term_id,
            )
            for _, row in business_term_info.iterrows()
        ]

        if cache:
            self._nodes_cache["business_term_nodes"] = nodes

        return nodes

    def transform_to_has_schema_relationships(
        self, schema_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[HasSchema]:
        """
        Transform Dataplex schema metadata into has schema relationships.

        Parameters
        ----------
        schema_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex schema metadata.
            Has columns `project_id` and `dataset_id`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the has schema relationships in the instance.

        Returns:
        -------
        list[HasSchema]
            The has schema relationships.
        """
        relationships = [
            HasSchema(
                database_id=generate_database_id(row.project_id),
                schema_id=generate_schema_id(row.project_id, row.dataset_id),
            )
            for _, row in schema_metadata_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_schema_relationships"] = relationships

        return relationships

    def transform_to_has_table_relationships(
        self, table_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[HasTable]:
        """
        Transform Dataplex table metadata into has table relationships.

        Parameters
        ----------
        table_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex table metadata.
            Has columns `project_id`, `dataset_id`, and `table_id`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the has table relationships in the instance.

        Returns:
        -------
        list[HasTable]
            The has table relationships.
        """
        relationships = [
            HasTable(
                schema_id=generate_schema_id(row.project_id, row.dataset_id),
                table_id=generate_table_id(row.project_id, row.dataset_id, row.table_id),
            )
            for _, row in table_metadata_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_table_relationships"] = relationships

        return relationships

    def transform_to_has_column_relationships(
        self, column_metadata_info: pd.DataFrame, cache: bool = True
    ) -> list[HasColumn]:
        """
        Transform Dataplex column metadata into has column relationships.

        Parameters
        ----------
        column_metadata_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex column metadata.
            Has columns `project_id`, `dataset_id`, `table_id`, and `column_name`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the has column relationships in the instance.

        Returns:
        -------
        list[HasColumn]
            The has column relationships.
        """
        relationships = [
            HasColumn(
                table_id=generate_table_id(row.project_id, row.dataset_id, row.table_id),
                column_id=generate_column_id(
                    row.project_id, row.dataset_id, row.table_id, row.column_name
                ),
            )
            for _, row in column_metadata_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_column_relationships"] = relationships

        return relationships

    def transform_to_has_category_relationships(
        self, category_info: pd.DataFrame, cache: bool = True
    ) -> list[HasCategory]:
        """
        Transform Dataplex category information into has category relationships.
        (:Glossary)-[:HAS_CATEGORY]->(:Category).

        Parameters
        ----------
        category_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex glossary information.
            Has columns `glossary_id` and `category_id`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the has category relationships in the instance.

        Returns:
        -------
        list[HasCategory]
            The has category relationships.
        """
        relationships = [
            HasCategory(
                glossary_id=generate_glossary_id(row.glossary_id),
                category_id=generate_category_id(
                    row.glossary_id, parse_category_slug(row.category_id)
                ),
            )
            for _, row in category_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_category_relationships"] = relationships

        return relationships

    def transform_to_has_business_term_relationships(
        self, business_term_info: pd.DataFrame, cache: bool = True
    ) -> list[HasBusinessTerm]:
        """
        Transform Dataplex business term information into has business term relationships.
        (:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm).

        Parameters
        ----------
        business_term_info: pd.DataFrame
            A Pandas DataFrame containing Dataplex business term information.
            Has columns `glossary_id` and `term_id`.
        cache: bool = True
            Whether to cache the transform. If True, will cache the has business term relationships in the instance.

        Returns:
        -------
        list[HasBusinessTerm]
            The has business term relationships.
        """
        relationships = [
            HasBusinessTerm(
                category_id=generate_category_id(
                    row.glossary_id, parse_category_slug(row.category_id)
                ),
                business_term_id=generate_business_term_id(
                    row.glossary_id,
                    parse_category_slug(row.category_id),
                    parse_business_term_slug(row.term_id),
                ),
            )
            for _, row in business_term_info.iterrows()
        ]

        if cache:
            self._relationships_cache["has_business_term_relationships"] = relationships

        return relationships

    def transform_to_column_tagged_with_relationships(
        self, column_term_info: pd.DataFrame, cache: bool = True
    ) -> list[TaggedWith]:
        """
        Transform column entry links into TAGGED_WITH relationships.
        (:Column)-[:TAGGED_WITH]->(:BusinessTerm).

        Parameters
        ----------
        column_term_info: pd.DataFrame
            A Pandas DataFrame with columns `entity_id` (Column node id) and `term_id` (BusinessTerm node id).
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[TaggedWith]
        """
        relationships = [
            TaggedWith(entity_id=row.entity_id, business_term_id=row.business_term_id)
            for _, row in column_term_info.iterrows()
        ]

        if cache:
            self._relationships_cache["column_tagged_with_relationships"] = relationships

        return relationships

    def transform_to_table_tagged_with_relationships(
        self, table_term_info: pd.DataFrame, cache: bool = True
    ) -> list[TaggedWith]:
        """
        Transform table entry links into TAGGED_WITH relationships.
        (:Table)-[:TAGGED_WITH]->(:BusinessTerm).

        Parameters
        ----------
        table_term_info: pd.DataFrame
            A Pandas DataFrame with columns `entity_id` (Table node id) and `business_term_id` (BusinessTerm node id).
        cache: bool = True
            Whether to cache the transform.

        Returns:
        -------
        list[TaggedWith]
        """
        relationships = [
            TaggedWith(entity_id=row.entity_id, business_term_id=row.business_term_id)
            for _, row in table_term_info.iterrows()
        ]

        if cache:
            self._relationships_cache["table_tagged_with_relationships"] = relationships

        return relationships
