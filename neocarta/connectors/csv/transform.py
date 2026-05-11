"""CSV Transformer for converting DataFrames into data model objects."""

import pandas as pd

from ...data_model.rdbms.core import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from ...data_model.rdbms.expanded import (
    BusinessTerm,
    Category,
    Glossary,
    HasBusinessTerm,
    HasCategory,
    HasValue,
    Query,
    TaggedWith,
    UsesColumn,
    UsesTable,
    Value,
)
from ..models import NodesCache, RelationshipsCache


def _available_properties(
    df: pd.DataFrame,
    exclude: list[str],
    column_mapping: dict[str, str] | None = None,
    always_include: list[str] | None = None,
) -> list[str]:
    """
    Derive the list of model property names to write based on CSV columns present.

    Controls which properties are written to Neo4j, preventing None from
    overwriting existing values for columns absent in the CSV.

    Columns are excluded from the result in three ways:
    - The literal ``"id"`` column is always excluded.
    - Any column whose name ends with ``"_id"`` is automatically excluded (these
      are structural identity/foreign-key columns computed during extraction and
      should not be written as node properties).
    - Columns listed in ``exclude`` are excluded explicitly (used for non-ID
      structural columns such as ``database_name`` or ``schema_name`` that belong
      to a parent entity rather than the current node).

    Parameters
    ----------
    df : pd.DataFrame
        The source DataFrame, which may contain computed ``*_id`` columns added
        during extraction in addition to the original CSV columns.
    exclude : list[str]
        CSV column names to exclude explicitly. Typically used for parent-scope
        name columns (e.g. ``"database_name"`` in a schema DataFrame) that are
        not properties of the current node type.
    column_mapping : dict[str, str], optional
        Maps CSV column names to model property names (e.g. ``{"data_type": "type"}``).
        Applied after exclusion; unmapped columns retain their original name.
    always_include : list[str], optional
        Model property names that must always appear in the result, appended if
        not already present. Useful for required properties whose source column is
        handled via ``column_mapping`` (e.g. ``"name"`` mapped from ``"schema_name"``).
    """
    all_excluded = {"id"} | set(exclude)
    csv_cols = [c for c in df.columns if c not in all_excluded and not c.endswith("_id")]

    properties = [column_mapping.get(c, c) for c in csv_cols] if column_mapping else list(csv_cols)

    if always_include:
        for prop in always_include:
            if prop not in properties:
                properties.append(prop)

    return properties


class CSVTransformer:
    """
    Transformer for converting extracted CSV DataFrames into data model objects.

    Reads DataFrames from a CSVExtractor's cache and produces typed pydantic
    nodes and relationships, storing them in internal caches.
    Each transform method also computes the relevant properties_list so the
    loader knows which Neo4j properties to write.
    """

    def __init__(self) -> None:
        """Initialize empty node/relationship caches and properties map."""
        self._node_cache: NodesCache = NodesCache()
        self._relationships_cache: RelationshipsCache = RelationshipsCache()
        # Derived from the columns present in each source CSV file.
        # CSV files have a dynamic structure (optional columns may or may not
        # be present), so this cannot be hardcoded at the loader call site the
        # way BigQuery's transformer can.
        self._properties: dict[str, list[str]] = {}

    def get_properties(self, key: str) -> list[str]:
        """
        Return the properties_list for a given node or relationship type.

        Parameters
        ----------
        key : str
            Cache key (e.g. "database_nodes", "column_nodes").
        """
        return self._properties.get(key, [])

    # ------------------------------------------------------------------
    # Node cache properties
    # ------------------------------------------------------------------

    @property
    def database_nodes(self) -> list[Database]:
        """Return cached Database nodes."""
        return self._node_cache.get("database_nodes", [])

    @property
    def schema_nodes(self) -> list[Schema]:
        """Return cached Schema nodes."""
        return self._node_cache.get("schema_nodes", [])

    @property
    def table_nodes(self) -> list[Table]:
        """Return cached Table nodes."""
        return self._node_cache.get("table_nodes", [])

    @property
    def column_nodes(self) -> list[Column]:
        """Return cached Column nodes."""
        return self._node_cache.get("column_nodes", [])

    @property
    def value_nodes(self) -> list[Value]:
        """Return cached Value nodes."""
        return self._node_cache.get("value_nodes", [])

    @property
    def query_nodes(self) -> list[Query]:
        """Return cached Query nodes."""
        return self._node_cache.get("query_nodes", [])

    @property
    def glossary_nodes(self) -> list[Glossary]:
        """Return cached Glossary nodes."""
        return self._node_cache.get("glossary_nodes", [])

    @property
    def category_nodes(self) -> list[Category]:
        """Return cached Category nodes."""
        return self._node_cache.get("category_nodes", [])

    @property
    def business_term_nodes(self) -> list[BusinessTerm]:
        """Return cached BusinessTerm nodes."""
        return self._node_cache.get("business_term_nodes", [])

    # ------------------------------------------------------------------
    # Relationship cache properties
    # ------------------------------------------------------------------

    @property
    def has_schema_relationships(self) -> list[HasSchema]:
        """Return cached HAS_SCHEMA relationships."""
        return self._relationships_cache.get("has_schema_relationships", [])

    @property
    def has_table_relationships(self) -> list[HasTable]:
        """Return cached HAS_TABLE relationships."""
        return self._relationships_cache.get("has_table_relationships", [])

    @property
    def has_column_relationships(self) -> list[HasColumn]:
        """Return cached HAS_COLUMN relationships."""
        return self._relationships_cache.get("has_column_relationships", [])

    @property
    def has_value_relationships(self) -> list[HasValue]:
        """Return cached HAS_VALUE relationships."""
        return self._relationships_cache.get("has_value_relationships", [])

    @property
    def has_category_relationships(self) -> list[HasCategory]:
        """Return cached HAS_CATEGORY relationships."""
        return self._relationships_cache.get("has_category_relationships", [])

    @property
    def has_business_term_relationships(self) -> list[HasBusinessTerm]:
        """Return cached HAS_BUSINESS_TERM relationships."""
        return self._relationships_cache.get("has_business_term_relationships", [])

    @property
    def references_relationships(self) -> list[References]:
        """Return cached REFERENCES relationships."""
        return self._relationships_cache.get("references_relationships", [])

    @property
    def uses_table_relationships(self) -> list[UsesTable]:
        """Return cached USES_TABLE relationships."""
        return self._relationships_cache.get("uses_table_relationships", [])

    @property
    def uses_column_relationships(self) -> list[UsesColumn]:
        """Return cached USES_COLUMN relationships."""
        return self._relationships_cache.get("uses_column_relationships", [])

    @property
    def column_tagged_with_relationships(self) -> list[TaggedWith]:
        """Return cached (:Column)-[:TAGGED_WITH]->(:BusinessTerm) relationships."""
        return self._relationships_cache.get("column_tagged_with_relationships", [])

    @property
    def table_tagged_with_relationships(self) -> list[TaggedWith]:
        """Return cached (:Table)-[:TAGGED_WITH]->(:BusinessTerm) relationships."""
        return self._relationships_cache.get("table_tagged_with_relationships", [])

    # ------------------------------------------------------------------
    # Transform methods — nodes
    # ------------------------------------------------------------------

    def transform_to_database_nodes(self, df: pd.DataFrame) -> list[Database]:
        """Transform database info DataFrame to Database nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Database(
                id=row.database_id,
                name=row.database_name,
                platform=getattr(row, "platform", None),
                service=getattr(row, "service", None),
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["database_nodes"] = nodes
        self._properties["database_nodes"] = _available_properties(
            df, exclude=[], column_mapping={"database_name": "name"}
        )
        return nodes

    def transform_to_schema_nodes(self, df: pd.DataFrame) -> list[Schema]:
        """Transform schema info DataFrame to Schema nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Schema(
                id=row.schema_id,
                name=row.schema_name,
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["schema_nodes"] = nodes
        self._properties["schema_nodes"] = _available_properties(
            df, exclude=["database_name"], column_mapping={"schema_name": "name"}
        )
        return nodes

    def transform_to_table_nodes(self, df: pd.DataFrame) -> list[Table]:
        """Transform table info DataFrame to Table nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Table(
                id=row.table_id,
                name=row.table_name,
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["table_nodes"] = nodes
        self._properties["table_nodes"] = _available_properties(
            df, exclude=["database_name", "schema_name"], column_mapping={"table_name": "name"}
        )
        return nodes

    def transform_to_column_nodes(self, df: pd.DataFrame) -> list[Column]:
        """Transform column info DataFrame to Column nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Column(
                id=row.column_id,
                name=row.column_name,
                description=getattr(row, "description", None),
                type=getattr(row, "data_type", None),
                nullable=getattr(row, "is_nullable", True),
                is_primary_key=getattr(row, "is_primary_key", False),
                is_foreign_key=getattr(row, "is_foreign_key", False),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["column_nodes"] = nodes
        self._properties["column_nodes"] = _available_properties(
            df,
            exclude=["database_name", "schema_name", "table_name"],
            column_mapping={"column_name": "name", "data_type": "type", "is_nullable": "nullable"},
        )
        return nodes

    def transform_to_value_nodes(self, df: pd.DataFrame) -> list[Value]:
        """Transform value info DataFrame to Value nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Value(
                id=row.value_id,
                value=row.value,
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["value_nodes"] = nodes
        self._properties["value_nodes"] = _available_properties(
            df,
            exclude=["database_name", "schema_name", "table_name", "column_name"],
            always_include=["value"],
        )
        return nodes

    def transform_to_query_nodes(self, df: pd.DataFrame) -> list[Query]:
        """Transform query info DataFrame to Query nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Query(
                id=row.query_id,
                content=row.content,
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["query_nodes"] = nodes
        self._properties["query_nodes"] = _available_properties(
            df, exclude=["query_id"], always_include=["content"]
        )
        return nodes

    def transform_to_glossary_nodes(self, df: pd.DataFrame) -> list[Glossary]:
        """Transform glossary info DataFrame to Glossary nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Glossary(
                id=row.glossary_id,
                name=getattr(row, "name", row.glossary_name) or row.glossary_name,
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["glossary_nodes"] = nodes
        self._properties["glossary_nodes"] = _available_properties(
            df, exclude=["glossary_name"], always_include=["name"]
        )
        return nodes

    def transform_to_category_nodes(self, df: pd.DataFrame) -> list[Category]:
        """Transform category info DataFrame to Category nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            Category(
                id=row.category_id,
                name=getattr(row, "name", row.category_name) or row.category_name,
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["category_nodes"] = nodes
        self._properties["category_nodes"] = _available_properties(
            df, exclude=["glossary_name", "category_name"], always_include=["name"]
        )
        return nodes

    def transform_to_business_term_nodes(self, df: pd.DataFrame) -> list[BusinessTerm]:
        """Transform business term info DataFrame to BusinessTerm nodes."""
        if df is None or df.empty:
            return []

        nodes = [
            BusinessTerm(
                id=row.business_term_id,
                name=getattr(row, "name", row.term_name) or row.term_name,
                description=getattr(row, "description", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._node_cache["business_term_nodes"] = nodes
        self._properties["business_term_nodes"] = _available_properties(
            df, exclude=["glossary_name", "category_name", "term_name"], always_include=["name"]
        )
        return nodes

    # ------------------------------------------------------------------
    # Transform methods — relationships
    # ------------------------------------------------------------------

    def transform_to_has_schema_relationships(self, df: pd.DataFrame) -> list[HasSchema]:
        """Transform schema info DataFrame to HAS_SCHEMA relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            HasSchema(
                database_id=row.database_id,
                schema_id=row.schema_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["has_schema_relationships"] = relationships
        return relationships

    def transform_to_has_table_relationships(self, df: pd.DataFrame) -> list[HasTable]:
        """Transform table info DataFrame to HAS_TABLE relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            HasTable(
                schema_id=row.schema_id,
                table_id=row.table_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["has_table_relationships"] = relationships
        return relationships

    def transform_to_has_column_relationships(self, df: pd.DataFrame) -> list[HasColumn]:
        """Transform column info DataFrame to HAS_COLUMN relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            HasColumn(
                table_id=row.table_id,
                column_id=row.column_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["has_column_relationships"] = relationships
        return relationships

    def transform_to_has_value_relationships(self, df: pd.DataFrame) -> list[HasValue]:
        """Transform value info DataFrame to HAS_VALUE relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            HasValue(
                column_id=row.column_id,
                value_id=row.value_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["has_value_relationships"] = relationships
        return relationships

    def transform_to_has_category_relationships(self, df: pd.DataFrame) -> list[HasCategory]:
        """Transform category info DataFrame to HAS_CATEGORY relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            HasCategory(
                glossary_id=row.glossary_id,
                category_id=row.category_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["has_category_relationships"] = relationships
        return relationships

    def transform_to_has_business_term_relationships(
        self, df: pd.DataFrame
    ) -> list[HasBusinessTerm]:
        """Transform business term info DataFrame to HAS_BUSINESS_TERM relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            HasBusinessTerm(
                category_id=row.category_id,
                business_term_id=row.business_term_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["has_business_term_relationships"] = relationships
        return relationships

    def transform_to_references_relationships(self, df: pd.DataFrame) -> list[References]:
        """Transform column references DataFrame to REFERENCES relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            References(
                source_column_id=row.source_column_id,
                target_column_id=row.target_column_id,
                criteria=getattr(row, "criteria", None),
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["references_relationships"] = relationships
        return relationships

    def transform_to_uses_table_relationships(self, df: pd.DataFrame) -> list[UsesTable]:
        """Transform query-table mapping DataFrame to USES_TABLE relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            UsesTable(
                query_id=row.query_id,
                table_id=row.table_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["uses_table_relationships"] = relationships
        return relationships

    def transform_to_uses_column_relationships(self, df: pd.DataFrame) -> list[UsesColumn]:
        """Transform query-column mapping DataFrame to USES_COLUMN relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            UsesColumn(
                query_id=row.query_id,
                column_id=row.column_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["uses_column_relationships"] = relationships
        return relationships

    def transform_to_column_tagged_with_relationships(self, df: pd.DataFrame) -> list[TaggedWith]:
        """Transform column-term mapping DataFrame to (:Column)-[:TAGGED_WITH]->(:BusinessTerm) relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            TaggedWith(
                entity_id=row.column_id,
                business_term_id=row.business_term_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["column_tagged_with_relationships"] = relationships
        return relationships

    def transform_to_table_tagged_with_relationships(self, df: pd.DataFrame) -> list[TaggedWith]:
        """Transform table-term mapping DataFrame to (:Table)-[:TAGGED_WITH]->(:BusinessTerm) relationships."""
        if df is None or df.empty:
            return []

        relationships = [
            TaggedWith(
                entity_id=row.table_id,
                business_term_id=row.business_term_id,
            )
            for row in df.itertuples(index=False)
        ]
        self._relationships_cache["table_tagged_with_relationships"] = relationships
        return relationships
