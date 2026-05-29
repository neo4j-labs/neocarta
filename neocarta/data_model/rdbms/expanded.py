"""Expanded RDBMS data model nodes and relationships (glossary, queries, values, OSI)."""

from typing import Any, Literal

from pandas import isna
from pydantic import BaseModel, Field, field_validator

from .core import Column, Table


class Value(BaseModel):
    """A Column Value node representing a unqiue value in a column."""

    id: str = Field(..., description="The unique identifier for the value")
    value: str = Field(..., description="The value cast to a string")

    @field_validator("value", mode="before")
    def cast_to_string(cls, v: Any) -> str:
        """Cast the value to a string."""
        # return empty string for NaN values
        if v is None or isna(v):
            return ""
        return str(v)


class HasValue(BaseModel):
    """
    A relationship between a column and a value.
    (Column)-[:HAS_VALUE]->(Value).
    """

    column_id: str = Field(..., description="The unique identifier for the column")
    value_id: str = Field(..., description="The unique identifier for the value")


class Glossary(BaseModel):
    """A Glossary node representing a glossary of business terms in a data catalog."""

    id: str = Field(..., description="The unique identifier for the glossary")
    name: str = Field(..., description="The name of the glossary")
    description: str | None = Field(default=None, description="The description of the glossary")
    resource_path: str | None = Field(
        default=None,
        description="The full resource path for the glossary (e.g. the Dataplex resource name)",
    )


class Category(BaseModel):
    """A Category node representing a category in a glossary."""

    id: str = Field(..., description="The unique identifier for the category")
    name: str = Field(..., description="The name of the category")
    description: str | None = Field(default=None, description="The description of the category")
    resource_path: str | None = Field(
        default=None,
        description="The full resource path for the category (e.g. the Dataplex resource name)",
    )


class BusinessTerm(BaseModel):
    """A Business Term node representing a business term in a glossary."""

    id: str = Field(..., description="The unique identifier for the business term")
    name: str = Field(..., description="The name of the business term")
    description: str | None = Field(
        default=None, description="The description of the business term"
    )
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the business term description"
    )
    resource_path: str | None = Field(
        default=None,
        description="The full resource path for the business term (e.g. the Dataplex resource name)",
    )


class TaggedWith(BaseModel):
    """
    A relationship between an entity and a Business Term.
    (:Column)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Table)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Schema)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Metric)-[:TAGGED_WITH]->(:BusinessTerm)
    """  # noqa: D415

    source_label: Literal["Column", "Table", "Schema", "Metric"] = Field(..., description="The label of the source entity")
    source_id: str = Field(
        ..., description="The unique identifier for the source entity"
    )
    business_term_id: str = Field(..., description="The unique identifier for the business term")


class HasCategory(BaseModel):
    """
    A relationship between a Glossary and a Category
    (Glossary)-[:HAS_CATEGORY]->(Category).
    """

    glossary_id: str = Field(..., description="The unique identifier for the glossary")
    category_id: str = Field(..., description="The unique identifier for the category")


class HasBusinessTerm(BaseModel):
    """
    A relationship between a Category and a Business Term
    (Category)-[:HAS_BUSINESS_TERM]->(BusinessTerm).
    """

    category_id: str = Field(..., description="The unique identifier for the category")
    business_term_id: str = Field(..., description="The unique identifier for the business term")


class Query(BaseModel):
    """A Query node representing a query in a query log or an OSI dataset source."""

    id: str = Field(..., description="The unique identifier for the query")
    name: str | None = Field(
        default=None,
        description="Logical name for the query (e.g. the OSI dataset name when sourced from OSI)",
    )
    content: str = Field(..., description="The content of the query")
    description: str | None = Field(default=None, description="The description of the query")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the query description"
    )


class UsesTable(BaseModel):
    """
    A relationship between a query and a table
    (Query)-[:USES_TABLE]->(Table).
    """

    query_id: str = Field(..., description="The unique identifier for the query")
    table_id: str = Field(..., description="The unique identifier for the table")


class UsesColumn(BaseModel):
    """
    A relationship between a query and a column
    (Query)-[:USES_COLUMN]->(Column).
    """

    query_id: str = Field(..., description="The unique identifier for the query")
    column_id: str = Field(..., description="The unique identifier for the column")


class CTE(BaseModel):
    """A CTE (Common Table Expression) node defined inline by a query.

    A CTE is a query-scoped, virtual table — not part of any catalog. We keep
    them in the graph (under their own label) so that downstream consumers
    can distinguish them from real tables while still tracing the SQL that
    produced each one.
    """

    id: str = Field(..., description="The unique identifier for the CTE")
    name: str = Field(..., description="The CTE alias as written in the query")
    definition: str = Field(..., description="The SQL of the CTE body (the inner SELECT)")
    query_id: str = Field(..., description="The id of the query that defines this CTE")


class Defines(BaseModel):
    """
    A relationship between a query and a CTE it defines.
    (Query)-[:DEFINES]->(CTE).
    """

    query_id: str = Field(..., description="The unique identifier for the query")
    cte_id: str = Field(..., description="The unique identifier for the CTE")

class Domain(BaseModel):
    """A Domain node representing a semantic grouping of data assets."""

    id: str = Field(..., description="The unique identifier for the domain")
    name: str = Field(..., description="The name of the domain")
    description: str | None = Field(default=None, description="The description of the domain")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the domain description"
    )


class OsiSemanticModel(Domain):
    """
    An OSI Semantic Model node — a Domain subtype representing a full OSI spec instance.

    Stored as a (:Domain&OsiSemanticModel) node in Neo4j.
    """

    osi_version: str = Field(
        ..., description="The version of the OSI spec this semantic model conforms to"
    )


class OsiTable(Table):
    """
    An OSI Table node — a Table with OSI-specific key metadata.

    Stored as a (:Table&OsiTable) node in Neo4j.
    """

    source: str | None = Field(
        default=None,
        description=(
            "The original OSI ``source`` string for this dataset "
            "(``db.schema.table``); preserved on the node so the OSI YAML "
            "round-trip can re-emit the original casing/structure."
        ),
    )
    primary_key: list[str] | None = Field(
        default=None,
        description="Ordered list of column names that form the primary key",
    )
    unique_keys: list[list[str]] | None = Field(
        default=None,
        description=(
            "List of unique key constraints; each entry is an ordered list of column names"
        ),
    )


class OsiColumn(Column):
    """
    An OSI Column node — a Column with OSI-specific display metadata.

    Stored as a (:Column:OsiColumn) node in Neo4j.
    """

    label: str | None = Field(default=None, description="The OSI display label for the column")
    is_time_dimension: bool | None = Field(
        default=None,
        description=(
            "Whether this column is a time-based dimension. ``None`` when the OSI "
            "field had no ``dimension`` key at all (so no property is written to "
            "the graph); ``True`` / ``False`` only when explicitly declared."
        ),
    )


class Metric(BaseModel):
    """A Metric node representing a measurable quantity in an OSI semantic model."""

    id: str = Field(..., description="The unique identifier for the metric")
    name: str = Field(..., description="The name of the metric")
    description: str | None = Field(default=None, description="The description of the metric")
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the metric description"
    )


class Aspect(BaseModel):
    """
    An Aspect node providing additional context to graph components. 
    This may be comments, annotations, or other metadata.
    """

    id: str = Field(..., description="The unique identifier for the aspect")


class OsiAiContext(Aspect):
    """
    An OSI AI Context aspect carrying agent-facing context as a JSON-encoded string.
    Recommended data attributes are:
    - instructions: instructions for AI on how to use this entity
    - synonyms: Alternative names and terms
    - examples: Sample questions or use cases
    """
    data: str = Field(..., description="The aspect payload as a JSON-encoded string")


class OsiCustomExtensions(Aspect):
    """Custom extensions allow vendors to add platform-specific metadata without breaking core compatibility. 
    Each extension includes a vendor name and arbitrary JSON data."""

    data: str = Field(..., description="The aspect payload as a JSON-encoded string")
    vendor_name: str = Field(..., description="The name of the vendor")


class Expression(BaseModel):
    """An Expression node — a dialect-specific computation expression."""

    id: str = Field(..., description="The unique identifier for the expression")
    dialect: str = Field(
        ..., description="The dialect of the expression (e.g. 'bigquery', 'snowflake')"
    )
    expression: str = Field(..., description="The expression text")


class Join(BaseModel):
    """
    A Join node representing a join definition between two tables in an OSI model.

    ``from_columns`` and ``to_columns`` carry the ordered column-name lists from
    the OSI relationship so that composite-key joins round-trip with the original
    pairing intact (``from_columns[i]`` ↔ ``to_columns[i]``). The corresponding
    USED_IN_JOIN edges from each Column to the Join are kept for graph traversal
    but are not used to recover ordering on export.
    """

    id: str = Field(..., description="The unique identifier for the join")
    name: str = Field(..., description="The name of the join")
    from_columns: list[str] | None = Field(
        default=None,
        description="Ordered list of column names on the 'from' (FK) side of the join",
    )
    to_columns: list[str] | None = Field(
        default=None,
        description="Ordered list of column names on the 'to' (PK/UK) side of the join",
    )


class HasAspect(BaseModel):
    """
    A relationship between an OSI entity and an Aspect.
    (:Domain)-[:HAS_ASPECT]->(:Aspect)
    (:Schema)-[:HAS_ASPECT]->(:Aspect)
    (:Table)-[:HAS_ASPECT]->(:Aspect)
    (:Column)-[:HAS_ASPECT]->(:Aspect)
    (:Query)-[:HAS_ASPECT]->(:Aspect)
    (:Metric)-[:HAS_ASPECT]->(:Aspect)
    (:Join)-[:HAS_ASPECT]->(:Aspect)
    """  # noqa: D415
    source_label: Literal[
        "Schema", "Table", "Column", "Query", "Metric", "Join", "Domain"
    ] = Field(..., description="The label of the source entity")
    source_id: str = Field(..., description="The unique identifier for the source entity")
    aspect_id: str = Field(..., description="The unique identifier for the aspect")


class UsedInJoin(BaseModel):
    """
    A relationship between a Column and a Join indicating the column participates in the join.
    (Column)-[:USED_IN_JOIN]->(Join).
    """

    column_id: str = Field(..., description="The unique identifier for the column")
    join_id: str = Field(..., description="The unique identifier for the join")


class HasExpression(BaseModel):
    """
    A relationship between a Column or Metric and an Expression.
    (:Column)-[:HAS_EXPRESSION]->(:Expression)
    (:Metric)-[:HAS_EXPRESSION]->(:Expression)
    """  # noqa: D415

    source_label: Literal["Column", "Metric"] = Field(..., description="The label of the source entity")
    source_id: str = Field(..., description="The unique identifier for the source entity")
    expression_id: str = Field(..., description="The unique identifier for the expression")

class HasMetric(BaseModel):
    """
    A relationship between a Domain and a Metric.
    (Domain)-[:HAS_METRIC]->(Metric).
    """

    domain_id: str = Field(..., description="The unique identifier for the domain")
    metric_id: str = Field(..., description="The unique identifier for the metric")


class DomainHasTable(BaseModel):
    """
    A relationship between a Domain (semantic model) and a Table it owns.
    (Domain)-[:HAS_TABLE]->(Table).

    Shares the ``:HAS_TABLE`` Cypher relationship type with the existing
    :class:`HasTable` (Schema → Table). An OSI semantic model owns datasets
    (tables) directly; databases and schemas are parsed from each dataset's
    ``source`` for hierarchical context but are not themselves children of
    the semantic model.
    """

    domain_id: str = Field(..., description="The unique identifier for the domain")
    table_id: str = Field(..., description="The unique identifier for the table")


class HasQuery(BaseModel):
    """
    A relationship between a Domain (semantic model) and a Query it owns.
    (Domain)-[:HAS_QUERY]->(Query).

    OSI datasets whose ``source`` is a SQL query (rather than a fully-qualified
    table reference) are stored as :class:`Query` nodes attached to the
    semantic model via this relationship.
    """

    domain_id: str = Field(..., description="The unique identifier for the domain")
    query_id: str = Field(..., description="The unique identifier for the query")


class HasSourceTable(BaseModel):
    """
    A relationship between a Join and its source Table.
    (Join)-[:HAS_SOURCE_TABLE]->(Table).
    """

    join_id: str = Field(..., description="The unique identifier for the join")
    table_id: str = Field(..., description="The unique identifier for the source table")


class HasTargetTable(BaseModel):
    """
    A relationship between a Join and its target Table.
    (Join)-[:HAS_TARGET_TABLE]->(Table).
    """

    join_id: str = Field(..., description="The unique identifier for the join")
    table_id: str = Field(..., description="The unique identifier for the target table")
