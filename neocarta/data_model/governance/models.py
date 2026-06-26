"""Governance-tag data model nodes and relationships (vendor-neutral tag layer).

A *governance tag* is a controlled-vocabulary label that data platforms attach to
objects for policy, classification, or ownership — Databricks Unity Catalog
governed tags, Snowflake object tags, and GCP resource Tags all fit this shape.
Unlike a business glossary (``Glossary``/``Category``/``BusinessTerm``), a tag's
values are not business *terms*: ``sensitivity={pii, non_pii}`` describes a
control, not vocabulary. This component models tags in their own right.

The model has two layers:

- **Definition / metadata** — :class:`GovernanceTagKey` ─[:HAS_VALUE_OPTION]→
  :class:`GovernanceTagValue`. Tells an agent which tags exist, what they mean,
  and (when governed) which values are allowed. This layer is the
  agent-searchable surface (full-text / vector over the key's description).
- **Instance / assignment** — ``(:Column|:Table|:Schema)`` ─[:TAGGED_WITH]→
  :class:`GovernanceTag`, optionally ─[:HAS_DEFINITION]→ :class:`GovernanceTagValue`.
  Tells where tags are applied. Comparing instances against definitions enables
  tag validation; a ``GovernanceTag`` with no ``HAS_DEFINITION`` edge is a
  free-form (undefined) value.

The definition layer is optional: free-form tags (Snowflake tags with no allowed
values, BigQuery labels) have instances but no definition, so the instance layer
stands alone.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .._validators import coerce_str_or_none


class GovernanceTagKey(BaseModel):
    """A GovernanceTagKey node — the definition of a governance tag's key.

    The agent-searchable surface for the governance layer: its ``name`` and
    ``description`` back the full-text / vector lookups an agent uses to discover
    relevant tags.
    """

    id: str = Field(..., description="The unique identifier for the governance tag key")
    name: str = Field(..., description="The tag key (e.g. 'sensitivity', 'cost_center')")
    description: str | None = Field(
        default=None, description="What the tag means / how it should be applied"
    )
    embedding: list[float] | None = Field(
        default=None, description="The embedding of the governance tag key description"
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class GovernanceTagValue(BaseModel):
    """A GovernanceTagValue node — one allowed value of a governance tag key.

    ``description`` is optional because tag *values* carry their own descriptions
    on some platforms (GCP resource Tag values) but are bare on others
    (Databricks governed tags, Snowflake object tags).
    """

    id: str = Field(..., description="The unique identifier for the governance tag value")
    name: str = Field(..., description="The allowed value (e.g. 'pii', 'finance')")
    description: str | None = Field(
        default=None,
        description="The description of the value, when the platform supplies one (e.g. GCP)",
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class GovernanceTag(BaseModel):
    """A GovernanceTag node — one applied (key, value) tag assignment.

    Instance-layer node: one per tagged object, so the node is *non-unique* across
    the graph (many objects may carry ``sensitivity=pii``). The ``key`` and
    ``value`` are denormalised onto the node so "find every object tagged
    ``sensitivity=pii``" is a single hop from the instance layer. When the applied
    value is governed, the node links to its :class:`GovernanceTagValue` definition
    via ``HAS_DEFINITION``; a missing link marks a free-form / undefined value.
    """

    id: str = Field(..., description="The unique identifier for the governance tag assignment")
    key: str = Field(..., description="The applied tag key")
    value: str = Field(..., description="The applied tag value")

    # key/value are required and intentionally NOT coerced: the id is built from the
    # same (key, value), so coercing a missing cell to "" here would diverge from the
    # id (which would hash the raw "none"/"nan"). The instance-layer producer must
    # supply clean values (or drop rows with missing tag parts) before constructing
    # the node — keeping model and id in sync through one upstream normalization path.


class HasValueOption(BaseModel):
    """
    A relationship between a GovernanceTagKey and one of its allowed values.
    (GovernanceTagKey)-[:HAS_VALUE_OPTION]->(GovernanceTagValue).
    """

    governance_tag_key_id: str = Field(
        ..., description="The unique identifier for the governance tag key"
    )
    governance_tag_value_id: str = Field(
        ..., description="The unique identifier for the governance tag value"
    )


class HasDefinition(BaseModel):
    """
    A relationship from an applied tag to the value definition it satisfies.
    (GovernanceTag)-[:HAS_DEFINITION]->(GovernanceTagValue).

    Present only when the applied value is governed (matches an allowed value);
    its absence marks a free-form / undefined value.
    """

    governance_tag_id: str = Field(
        ..., description="The unique identifier for the governance tag assignment"
    )
    governance_tag_value_id: str = Field(
        ..., description="The unique identifier for the governance tag value definition"
    )


class TaggedWithGovernanceTag(BaseModel):
    """
    A relationship between a tagged entity and a GovernanceTag.
    (:Column)-[:TAGGED_WITH]->(:GovernanceTag)
    (:Table)-[:TAGGED_WITH]->(:GovernanceTag)
    (:Schema)-[:TAGGED_WITH]->(:GovernanceTag)

    Distinct from the glossary ``TaggedWith`` (which points at ``:BusinessTerm``);
    both share the ``TAGGED_WITH`` type but target different node labels.
    """  # noqa: D415

    source_label: Literal["Column", "Table", "Schema"] = Field(
        ..., description="The label of the source entity"
    )
    source_id: str = Field(..., description="The unique identifier for the source entity")
    governance_tag_id: str = Field(
        ..., description="The unique identifier for the governance tag assignment"
    )
