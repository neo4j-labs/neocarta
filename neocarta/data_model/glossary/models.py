"""Glossary data model nodes and relationships (business terminology layer)."""

from typing import Literal

from pydantic import BaseModel, Field


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


class TaggedWith(BaseModel):
    """
    A relationship between an entity and a Business Term.
    (:Column)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Table)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Schema)-[:TAGGED_WITH]->(:BusinessTerm)
    (:Metric)-[:TAGGED_WITH]->(:BusinessTerm)
    """  # noqa: D415

    source_label: Literal["Column", "Table", "Schema", "Metric"] = Field(
        ..., description="The label of the source entity"
    )
    source_id: str = Field(..., description="The unique identifier for the source entity")
    business_term_id: str = Field(..., description="The unique identifier for the business term")
