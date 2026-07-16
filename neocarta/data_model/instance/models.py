"""Instance-level data model nodes and relationships (actual data values)."""

from pydantic import BaseModel, Field, field_validator

from .._validators import coerce_str


class Value(BaseModel):
    """A Value node representing a unique value drawn from the source data.

    The node is source-agnostic: it carries a single value cast to a string.
    The originating entity (e.g. a Column) is recorded by the :class:`HasValue`
    relationship rather than on the node itself.
    """

    id: str = Field(..., description="The unique identifier for the value")
    value: str = Field(..., description="The value cast to a string")

    _cast = field_validator("value", mode="before")(coerce_str)


class HasValue(BaseModel):
    """
    A relationship between a column and a value.
    (Column)-[:HAS_VALUE]->(Value).
    """

    column_id: str = Field(..., description="The unique identifier for the column")
    value_id: str = Field(..., description="The unique identifier for the value")
