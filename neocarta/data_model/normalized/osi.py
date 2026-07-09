"""Provisional flat OSI container for normalized semantic-model metadata."""

# TODO: This module is provisional. Its sole purpose is to prove that the
# NormalizedMetadata marker base generalizes to a non-relational source. The
# placeholder record shapes are intentionally lean and are expected to be
# reshaped when the full OSI normalization mapping lands. Do not depend on these
# fields, and do not import the OSI graph models here.

from typing import ClassVar

from pydantic import BaseModel, Field

from .base import NormalizedMetadata


class OsiSemanticModelRecord(BaseModel):
    """A flat OSI semantic-model record."""

    name: str = Field(..., description="The name of the semantic model")
    osi_version: str | None = Field(default=None, description="The OSI spec version")
    description: str | None = Field(
        default=None, description="The description of the semantic model"
    )


class OsiTableRecord(BaseModel):
    """A flat OSI table record."""

    name: str = Field(..., description="The name of the table")
    description: str | None = Field(default=None, description="The description of the table")


class OsiColumnRecord(BaseModel):
    """A flat OSI column record."""

    table_name: str = Field(..., description="The name of the parent table")
    name: str = Field(..., description="The name of the column")
    description: str | None = Field(default=None, description="The description of the column")


class OsiMetricRecord(BaseModel):
    """A flat OSI metric record."""

    name: str = Field(..., description="The name of the metric")
    description: str | None = Field(default=None, description="The description of the metric")


class OsiJoinRecord(BaseModel):
    """A flat OSI join record."""

    name: str = Field(..., description="The name of the join")


class OsiExpressionRecord(BaseModel):
    """A flat OSI expression record."""

    dialect: str = Field(..., description="The SQL dialect of the expression")
    expression: str = Field(..., description="The expression text")


class OsiRelationshipRecord(BaseModel):
    """A flat OSI relationship record linking two entities by name."""

    source_name: str = Field(..., description="The name of the source entity")
    target_name: str = Field(..., description="The name of the target entity")


class OsiAspectRecord(BaseModel):
    """A flat OSI aspect (annotation/context) record."""

    data: str | None = Field(default=None, description="The aspect payload")


class Osi(NormalizedMetadata):
    """A provisional flat container of OSI record lists.

    Empty construction yields eight empty lists.
    """

    normalized_kind: ClassVar[str] = "osi"

    semantic_models: list[OsiSemanticModelRecord] = Field(
        default_factory=list, description="The semantic-model records"
    )
    tables: list[OsiTableRecord] = Field(default_factory=list, description="The table records")
    columns: list[OsiColumnRecord] = Field(default_factory=list, description="The column records")
    metrics: list[OsiMetricRecord] = Field(default_factory=list, description="The metric records")
    joins: list[OsiJoinRecord] = Field(default_factory=list, description="The join records")
    expressions: list[OsiExpressionRecord] = Field(
        default_factory=list, description="The expression records"
    )
    relationships: list[OsiRelationshipRecord] = Field(
        default_factory=list, description="The relationship records"
    )
    aspects: list[OsiAspectRecord] = Field(
        default_factory=list, description="The aspect (annotation) records"
    )
