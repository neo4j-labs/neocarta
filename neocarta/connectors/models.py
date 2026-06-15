"""global models for connectors."""

from typing import TypedDict

from ..data_model.glossary import (
    BusinessTerm,
    Category,
    Glossary,
    HasBusinessTerm,
    HasCategory,
)
from ..data_model.instance import HasValue, Value
from ..data_model.query import Query, UsesColumn, UsesTable
from ..data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)


class NodesCache(TypedDict):
    """Cache dictionary used to store transformed metadata nodes."""

    # Core nodes
    database_nodes: list[Database] | None
    schema_nodes: list[Schema] | None
    table_nodes: list[Table] | None
    column_nodes: list[Column] | None
    # Value nodes
    value_nodes: list[Value] | None

    # Glossary nodes
    glossary_nodes: list[Glossary] | None
    category_nodes: list[Category] | None
    business_term_nodes: list[BusinessTerm] | None

    # Query nodes
    query_nodes: list[Query] | None


class RelationshipsCache(TypedDict):
    """Cache dictionary used to store transformed metadata relationships."""

    # Core relationships
    has_schema_relationships: list[HasSchema] | None
    has_table_relationships: list[HasTable] | None
    has_column_relationships: list[HasColumn] | None
    references_relationships: list[References] | None

    # Value relationships
    has_value_relationships: list[HasValue] | None

    # Glossary relationships
    has_category_relationships: list[HasCategory] | None
    has_business_term_relationships: list[HasBusinessTerm] | None

    # Query relationships
    uses_table_relationships: list[UsesTable] | None
    uses_column_relationships: list[UsesColumn] | None
