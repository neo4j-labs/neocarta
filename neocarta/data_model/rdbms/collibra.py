"""Collibra subtype nodes — core RDBMS models extended with Collibra-specific metadata.

Each class is a Pydantic subclass of a core node model (``Table``, ``Column``,
``Glossary``, …) that adds the Collibra cross-reference UUID (``collibra_id``)
and, for governed assets, the governance ``status``. They are stored in Neo4j
with a secondary label alongside the core label (e.g. ``(:Table:CollibraTable)``),
exactly like the OSI subtypes in :mod:`neocarta.data_model.rdbms.expanded`.

Carrying ``collibra_id`` on every Collibra-sourced node lets the loader match
relationship endpoints by source UUID — including edges that span the schema and
glossary sub-connectors (e.g. ``(:Column)-[:TAGGED_WITH]->(:BusinessTerm)``) —
without recomputing deterministic ids across connectors.
"""

from pydantic import BaseModel, Field

from .core import Column, Database, Schema, Table
from .expanded import BusinessTerm, Category, Glossary


class CollibraDatabase(Database):
    """A Database sourced from a Collibra Community (``(:Database:CollibraDatabase)``)."""

    collibra_id: str | None = Field(
        default=None, description="UUID of the originating Collibra community"
    )


class CollibraSchema(Schema):
    """A Schema sourced from a Collibra physical Domain (``(:Schema:CollibraSchema)``)."""

    collibra_id: str | None = Field(
        default=None, description="UUID of the originating Collibra domain"
    )


class CollibraTable(Table):
    """A Table sourced from a Collibra Table-like asset (``(:Table:CollibraTable)``)."""

    collibra_id: str | None = Field(default=None, description="UUID of the Collibra asset")
    status: str | None = Field(
        default=None,
        description="Collibra governance status (e.g. Candidate, Accepted, Deprecated)",
    )
    collibra_asset_type: str | None = Field(
        default=None, description="Display name of the original Collibra asset type"
    )


class CollibraColumn(Column):
    """A Column sourced from a Collibra Column-like asset (``(:Column:CollibraColumn)``)."""

    collibra_id: str | None = Field(default=None, description="UUID of the Collibra asset")
    status: str | None = Field(
        default=None,
        description="Collibra governance status (e.g. Candidate, Accepted, Deprecated)",
    )
    collibra_asset_type: str | None = Field(
        default=None, description="Display name of the original Collibra asset type"
    )


class CollibraGlossary(Glossary):
    """A Glossary sourced from a Collibra glossary Domain (``(:Glossary:CollibraGlossary)``)."""

    collibra_id: str | None = Field(
        default=None, description="UUID of the originating Collibra domain"
    )


class CollibraCategory(Category):
    """A Category sourced from a Collibra Data Category asset (``(:Category:CollibraCategory)``)."""

    collibra_id: str | None = Field(default=None, description="UUID of the Collibra asset")
    status: str | None = Field(
        default=None,
        description="Collibra governance status (e.g. Candidate, Accepted, Deprecated)",
    )


class CollibraBusinessTerm(BusinessTerm):
    """A Business Term sourced from a Collibra Business Term asset.

    Stored as ``(:BusinessTerm:CollibraBusinessTerm)``.
    """

    collibra_id: str | None = Field(default=None, description="UUID of the Collibra asset")
    status: str | None = Field(
        default=None,
        description="Collibra governance status (e.g. Candidate, Accepted, Deprecated)",
    )


class CollibraTaggedWith(BaseModel):
    """
    A ``TAGGED_WITH`` edge from a tagged catalog asset to a Business Term.

    ``(:Table|:Column)-[:TAGGED_WITH]->(:BusinessTerm)``.

    The tagged source asset is identified by its Collibra UUID rather than a
    neocarta node id: the source node (a ``CollibraTable``/``CollibraColumn``)
    is produced by the schema sub-connector, while this edge is produced by the
    glossary sub-connector, so the loader matches the source by ``collibra_id``
    (backed by the per-label ``collibra_id`` range index) instead of recomputing
    the source's deterministic id across connectors.
    """

    source_collibra_id: str = Field(..., description="UUID of the tagged Collibra asset")
    business_term_id: str = Field(..., description="neocarta id of the target Business Term node")
