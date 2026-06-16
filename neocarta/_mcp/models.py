"""Pydantic models for the MCP server."""

from pydantic import BaseModel, Field


class JoinContext(BaseModel):
    """Model representing context for a join."""

    table_name: str = Field(..., description="The name of the table")
    column_names: list[str] = Field(..., description="The names of the columns a table joins on")


class ExpressionContext(BaseModel):
    """Model representing a dialect-specific OSI expression on a column or metric."""

    dialect: str = Field(..., description="The SQL dialect of the expression (e.g. 'ANSI_SQL')")
    expression: str = Field(..., description="The runnable expression text for the dialect")


class AspectContext(BaseModel):
    """Model representing an OSI Aspect (agent-facing context) attached to an entity."""

    aspect_type: str = Field(
        ...,
        description="The kind of aspect: 'ai_context' (synonyms/instructions/examples) or "
        "'custom_extensions' (vendor metadata)",
    )
    data: str = Field(..., description="The aspect payload as a JSON-encoded string")
    vendor_name: str | None = Field(
        default=None,
        description="The vendor name for a 'custom_extensions' aspect; null for 'ai_context'",
    )


class ColumnContext(BaseModel):
    """Model representing context for a column."""

    column_name: str = Field(..., description="The name of the column")
    column_description: str | None = Field(
        default=None, description="The description of the column"
    )
    data_type: str | None = Field(default=None, description="The data type of the column")
    nullable: bool | None = Field(default=None, description="Whether the column can be null")
    examples: list[str] | None = Field(default=None, description="Example values for the column")
    key_type: str | None = Field(default=None, description="The key type of the column")
    label: str | None = Field(
        default=None, description="The OSI display label for the column. Null on non-OSI graphs."
    )
    is_time_dimension: bool | None = Field(
        default=None,
        description="Whether the column is a time-based dimension (OSI). Null when not declared.",
    )
    references: list[str] = Field(
        default=[],
        description="The referenced columns from another table of the column. Have format of 'table_name.column_name'",
    )
    expressions: list[ExpressionContext] = Field(
        default=[],
        description="OSI dialect-specific expressions defined on the column. Empty on non-OSI graphs.",
    )
    aspects: list[AspectContext] = Field(
        default=[],
        description="OSI aspects (ai_context / custom_extensions) attached to the column. Empty on non-OSI graphs.",
    )


class TableContext(BaseModel):
    """Model representing context for a table."""

    table_name: str = Field(..., description="The name of the table")
    table_description: str | None = Field(default=None, description="The description of the table")
    database_name: str | None = Field(
        default=None,
        description="The name of the database. Null for an OSI query-backed dataset, which has "
        "no database/schema.",
    )
    schema_name: str | None = Field(
        default=None,
        description="The name of the schema. Null for an OSI query-backed dataset.",
    )
    columns: list[ColumnContext] = Field(..., description="The relevant columns of the table")
    joins: list[JoinContext] = Field(
        default=[], description="The relevant join tables of the table"
    )
    num_columns: int | None = Field(default=None, description="The number of columns in the table")
    primary_key: list[str] = Field(
        default=[],
        description="Ordered primary-key column names (OSI datasets). Empty on non-OSI graphs.",
    )
    aspects: list[AspectContext] = Field(
        default=[],
        description="OSI aspects (ai_context / custom_extensions) attached to the table. Empty on non-OSI graphs.",
    )
    table_score: float | None = Field(
        default=None, description="The table embedding similarity score"
    )
    schema_score: float | None = Field(
        default=None, description="The schema embedding similarity score"
    )
    column_avg_score: float | None = Field(
        default=None, description="The average column embedding similarity score"
    )


class ListSchemaRecord(BaseModel):
    """Model representing a record for a schema in the list_schemas tool."""

    schema_name: str = Field(..., description="The name of the schema")
    database_name: str = Field(..., description="The name of the database")


class ListTablesBySchemaRecord(BaseModel):
    """Model representing a record for a table in the list_tables_by_schema tool."""

    schema_name: str = Field(..., description="The name of the schema")
    table_names: list[str] = Field(..., description="The names of the tables in the schema")


class MetricContext(BaseModel):
    """Model representing context for an OSI metric."""

    metric_name: str = Field(..., description="The name of the metric")
    metric_description: str | None = Field(
        default=None, description="The description of the metric"
    )
    domain_name: str = Field(
        ..., description="The name of the domain (semantic model) that owns the metric"
    )
    expressions: list[ExpressionContext] = Field(
        default=[], description="The dialect-specific SQL expressions that define the metric"
    )
    synonyms: list[str] = Field(
        default=[],
        description="Business-term synonyms the metric is tagged with (from TAGGED_WITH BusinessTerm)",
    )
    aspects: list[AspectContext] = Field(
        default=[],
        description="OSI aspects (ai_context / custom_extensions) attached to the metric",
    )
    metric_score: float | None = Field(
        default=None, description="The metric embedding/search similarity score"
    )


class DomainJoinContext(BaseModel):
    """Model representing a join between two datasets within an OSI domain."""

    join_name: str = Field(..., description="The name of the join")
    from_table: str | None = Field(
        default=None, description="The name of the dataset on the 'from' (foreign-key) side"
    )
    to_table: str | None = Field(
        default=None, description="The name of the dataset on the 'to' (primary/unique-key) side"
    )
    from_columns: list[str] = Field(
        default=[], description="Ordered column names on the 'from' side of the join"
    )
    to_columns: list[str] = Field(
        default=[], description="Ordered column names on the 'to' side of the join"
    )


class DomainContext(BaseModel):
    """Model representing the full context of an OSI domain (semantic model)."""

    domain_name: str = Field(..., description="The name of the domain")
    domain_description: str | None = Field(
        default=None, description="The description of the domain"
    )
    osi_version: str | None = Field(
        default=None, description="The OSI spec version the domain conforms to"
    )
    tables: list[TableContext] = Field(
        default=[], description="The datasets (tables) the domain owns, with their columns"
    )
    metrics: list[MetricContext] = Field(
        default=[], description="The metrics the domain owns, with their expressions and synonyms"
    )
    joins: list[DomainJoinContext] = Field(
        default=[], description="The joins between the domain's datasets"
    )
    aspects: list[AspectContext] = Field(
        default=[],
        description="OSI aspects (ai_context / custom_extensions) attached to the domain",
    )


class ListDomainRecord(BaseModel):
    """Model representing a record for a domain in the list_domains tool."""

    domain_name: str = Field(..., description="The name of the domain")
    domain_description: str | None = Field(
        default=None, description="The description of the domain"
    )
    num_metrics: int = Field(..., description="The number of metrics the domain owns")
    num_tables: int = Field(..., description="The number of datasets (tables) the domain owns")
    num_columns: int = Field(..., description="The number of columns across the domain's datasets")
    num_joins: int = Field(..., description="The number of joins between the domain's datasets")


class ListMetricRecord(BaseModel):
    """Model representing a record for a metric in the list_metrics_by_domain tool."""

    metric_name: str = Field(..., description="The name of the metric")
    metric_description: str | None = Field(
        default=None, description="The description of the metric"
    )
    domain_name: str = Field(..., description="The name of the domain that owns the metric")
