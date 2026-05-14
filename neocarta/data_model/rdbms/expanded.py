"""Expanded RDBMS data model nodes and relationships (glossary, queries, values)."""

from typing import Any

from pandas import isna
from pydantic import BaseModel, Field, field_validator


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
    status: str | None = Field(
        default=None,
        description="Governance lifecycle status (e.g. Accepted, Draft, Deprecated)",
    )
    collibra_id: str | None = Field(
        default=None, description="UUID from Collibra for cross-reference"
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
    status: str | None = Field(
        default=None,
        description="Governance lifecycle status (e.g. Accepted, Draft, Deprecated)",
    )
    collibra_id: str | None = Field(
        default=None, description="UUID from Collibra for cross-reference"
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
    status: str | None = Field(
        default=None,
        description="Governance lifecycle status (e.g. Accepted, Draft, Deprecated)",
    )
    collibra_id: str | None = Field(
        default=None, description="UUID from Collibra for cross-reference"
    )


class TaggedWith(BaseModel):
    """
    A relationship between a Column or Table and a Business Term.
    (:Column)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Table)-[:TAGGED_WITH]->(:BusinessTerm)
    """  # noqa: D415

    entity_id: str = Field(..., description="The unique identifier for the column or table")
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
    """A Query node representing a query in a query log."""

    id: str = Field(..., description="The unique identifier for the query")
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


class CatalogAsset(BaseModel):
    """A generic catalog asset node for Collibra asset types not mapped to a specific node type."""

    id: str = Field(..., description="The unique identifier for the catalog asset")
    name: str = Field(..., description="The name of the catalog asset")
    description: str | None = Field(default=None, description="The description of the asset")
    status: str | None = Field(
        default=None,
        description="Governance lifecycle status (e.g. Accepted, Draft, Deprecated)",
    )
    collibra_id: str | None = Field(
        default=None, description="UUID from Collibra for cross-reference"
    )
    asset_type: str = Field(..., description="Original Collibra asset type name")
    domain_id: str = Field(..., description="Parent domain node id (Schema or Glossary)")


class HasAsset(BaseModel):
    """
    A relationship from a domain (Schema or Glossary) to a generic catalog asset.
    (Schema|Glossary)-[:HAS_ASSET]->(CatalogAsset).
    """

    parent_id: str = Field(..., description="Schema or Glossary node id")
    asset_id: str = Field(..., description="CatalogAsset node id")


class FlowsInto(BaseModel):
    """
    Technical lineage relationship between two table or column nodes.
    (Table|Column)-[:FLOWS_INTO]->(Table|Column).
    """

    source_id: str = Field(..., description="Source node id")
    target_id: str = Field(..., description="Target node id")
    lineage_type: str | None = Field(
        default=None, description="Lineage granularity: 'TABLE' or 'COLUMN'"
    )
