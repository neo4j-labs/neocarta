"""Query data model nodes and relationships (cached SQL and parsed usage)."""

from pydantic import BaseModel, Field


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


class Defines(BaseModel):
    """
    A relationship between a query and a CTE it defines.
    (Query)-[:DEFINES]->(CTE).
    """

    query_id: str = Field(..., description="The unique identifier for the query")
    cte_id: str = Field(..., description="The unique identifier for the CTE")
