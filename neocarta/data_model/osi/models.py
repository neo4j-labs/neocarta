"""OSI (Open Semantic Interchange) semantic-model data model nodes and relationships.

These models extend the relational structural core with semantic-model
concepts. OSI subtypes (:class:`OsiTable`, :class:`OsiColumn`) inherit from
the RDBMS structural models and are stored as multi-labelled nodes in Neo4j.
"""

from typing import Literal

from pydantic import BaseModel, Field

from ..schema.rdbms.models import Column, Table


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
    Each extension includes a vendor name and arbitrary JSON data.
    """

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

    source_label: Literal["Schema", "Table", "Column", "Query", "Metric", "Join", "Domain"] = Field(
        ..., description="The label of the source entity"
    )
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

    source_label: Literal["Column", "Metric"] = Field(
        ..., description="The label of the source entity"
    )
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
    :class:`~neocarta.data_model.schema.rdbms.models.HasTable` (Schema → Table).
    An OSI semantic model owns datasets (tables) directly; databases and schemas
    are parsed from each dataset's ``source`` for hierarchical context but are
    not themselves children of the semantic model.
    """

    domain_id: str = Field(..., description="The unique identifier for the domain")
    table_id: str = Field(..., description="The unique identifier for the table")


class HasQuery(BaseModel):
    """
    A relationship between a Domain (semantic model) and a Query it owns.
    (Domain)-[:HAS_QUERY]->(Query).

    OSI datasets whose ``source`` is a SQL query (rather than a fully-qualified
    table reference) are stored as :class:`~neocarta.data_model.query.models.Query`
    nodes attached to the semantic model via this relationship.
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


class MetricUsesTable(BaseModel):
    """
    A relationship between a Metric and a table its expression references.
    (:Metric)-[:USES_TABLE]->(:Table).

    Derived at ingest by parsing the metric's dialect expressions. The target is
    matched by id at load time and — like :class:`HasSourceTable` — may resolve to
    a query-backed dataset's ``:Query`` node, so it is not constrained to ``:Table``.
    """

    metric_id: str = Field(..., description="The unique identifier for the metric")
    table_id: str = Field(
        ...,
        description="The unique identifier for the backing table (or query-backed dataset) node",
    )


class MetricUsesColumn(BaseModel):
    """
    A relationship between a Metric and a column its expression references.
    (:Metric)-[:USES_COLUMN]->(:Column).

    Derived at ingest by parsing the metric's dialect expressions.
    """

    metric_id: str = Field(..., description="The unique identifier for the metric")
    column_id: str = Field(..., description="The unique identifier for the backing column")
