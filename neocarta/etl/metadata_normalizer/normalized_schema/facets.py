"""The optional facets that hang off the normalized structural core.

Five facets — **values**, **references**, **lineage**, **glossary** and
**governance** — each **independently omittable**, so a connector emits only what
its source actually exposes and a connector emitting only the structural core
validates unchanged. Omittability is structural: every facet table on
:class:`~.models.NormalizedStructuralSchema` defaults to an empty list (GUIDE
D10), so there is nothing to switch off.

Like the core (see ``models.py``), every facet row is **natural-key-addressed**
and **identity-agnostic** (GUIDE D6): it carries the full source name path of the
thing it describes and never a graph ID, an embedding, or — new here — a graph
*label*. The graph model's polymorphic ``TAGGED_WITH`` uses a
``source_label`` + ``source_id`` pair; a facet row instead addresses its asset by
an unbroken prefix of the natural-key path and lets the **grain follow from the
depth** of that path. Naming a label would couple the connector to the ontology,
which is precisely what this contract exists to decouple (GUIDE §6).

The core's derivability rule applies here too — an edge between a key path and one
of its own prefixes is not a table:

- ``HAS_VALUE`` — a value's key path extends its column's.
- ``HAS_CATEGORY`` / ``HAS_BUSINESS_TERM`` — term ⊃ category ⊃ glossary.
- ``HAS_VALUE_OPTION`` — a tag value's key path extends its tag key's.
- ``HAS_DEFINITION`` — derivable *non-locally*, as the natural-key join of an
  assignment against the tag-value table on ``(tag_namespace, tag_key,
  tag_value)``. That set membership **is** the graph's semantics: an applied value
  with no matching definition is a free-form value. A fabricated ``is_governed``
  flag could only disagree with the authoritative join (GUIDE D10).

Only the cross-hierarchy attachments are tables: a business term applied to a
catalog object (:class:`BusinessTermAssignmentRecord`) and a data-flow observation
between two catalog objects (:class:`LineageRecord`).

The **references** facet is the one S1.1 already landed *in the core*
(:class:`~.models.ForeignKeyRecord`), because a foreign key is a declared
structural constraint and a core-only connector emits it — ``datasets/musicbrainz``
ships ``column_references_info.csv`` and no facet file at all. Its
``foreign_keys`` table is already ``default_factory=list``, so the facet is
already independently omittable and needs no new record.

Scope stays the RDBMS hierarchy (GUIDE D11, and S1.1's own scope line). Attach
points in the other paradigms — an OSI ``Metric``, a query-owned column whose key
is rooted on a query hash — are not deeper segments of this path and are
deliberately not forced into it; they arrive as additive sibling records.
"""

from pydantic import AliasChoices, BaseModel, Field, field_validator

from ....data_model._validators import (
    coerce_key_segment_or_none,
    coerce_str_or_none,
    coerce_str_required,
)
from ._vocabulary import (
    DATABASE_NAME_SYNONYMS,
    GLOSSARY_DISPLAY_NAME_SYNONYMS,
    SCHEMA_NAME_SYNONYMS,
    TABLE_NAME_SYNONYMS,
    TAG_NAMESPACE_SYNONYMS,
    TAG_VALUE_SYNONYMS,
    VALUE_SYNONYMS,
)


class ValueRecord(BaseModel):
    """A row of the normalized Value table (one sampled distinct value of a column).

    The natural key is the column's key path plus the value itself, which is
    exactly what the downstream ID builder consumes — so ``HAS_VALUE`` is
    derivable and is not a table.

    The table carries the value and nothing else: no producer exposes a count,
    frequency, distinct count, null rate, inferred type or sampling timestamp, so
    source-derived-only means no statistics.

    The sampled-values frames carry only ``column_name`` / ``unique_value`` (plus
    the private ``column_id`` / ``value_id``); the container path lives on the
    extractor call, which already passes it to the id builder. The connector
    projects it — dropping the two pre-computed ids is correct, not lossy (GUIDE
    D5).
    """

    database_name: str = Field(
        ...,
        validation_alias=AliasChoices(*DATABASE_NAME_SYNONYMS),
        description="The natural-key name of the parent database.",
    )
    schema_name: str = Field(
        ...,
        validation_alias=AliasChoices(*SCHEMA_NAME_SYNONYMS),
        description="The natural-key name of the parent schema.",
    )
    table_name: str = Field(
        ...,
        validation_alias=AliasChoices(*TABLE_NAME_SYNONYMS),
        description="The natural-key name of the parent table.",
    )
    column_name: str = Field(..., description="The natural-key name of the parent column.")
    value: str = Field(
        ...,
        validation_alias=AliasChoices(*VALUE_SYNONYMS),
        description=(
            "One sampled distinct value of the column, as a string. Required and never "
            "fabricated: the value is a key segment, so coercing a missing cell to an "
            "empty string would mint identity the source never had (GUIDE D10)."
        ),
    )

    _cast = field_validator("value", mode="before")(coerce_str_required)


class GlossaryRecord(BaseModel):
    """A row of the normalized Glossary table (a business glossary).

    Uses the identity/display split S1.1 established for tables
    (``table_name`` vs ``display_name``), which is what lets one record serve every
    producer. CSV keys by name and carries an optional ``name`` column as the
    label. Dataplex is the **inverse**: identity is the slug in its ``glossary_id``
    column while its ``glossary_name`` column holds the label, so the connector
    projects ``glossary_name=<slug>`` and ``display_name=<raw glossary_name>``.
    Those ``*_id`` columns are deliberately not aliased here — ``AliasChoices``
    resolves to the first alias *present*, so an alias would silently bind the
    label as identity.
    """

    glossary_name: str = Field(
        ..., description="The natural-key name (identity segment) of the glossary."
    )
    display_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(*GLOSSARY_DISPLAY_NAME_SYNONYMS),
        description=(
            "A human label distinct from the identity segment, when the source provides "
            "one. Downstream label = display_name or glossary_name."
        ),
    )
    description: str | None = Field(
        default=None,
        description="The description of the glossary.",
    )
    resource_path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("resource_path", "glossary_resource_path"),
        description=(
            "The source's own full resource path (e.g. the Dataplex resource name), when "
            "it has one. A locator, not an identity: the key is glossary_name."
        ),
    )

    _normalize = field_validator("display_name", "description", "resource_path", mode="before")(
        coerce_str_or_none
    )


class CategoryRecord(BaseModel):
    """A row of the normalized Category table (a category of a glossary).

    ``HAS_CATEGORY`` is derivable — this key path extends the glossary's — so it is
    not a table.

    Exactly one level deep, matching the graph model, which has no parent field.
    Dataplex can nest categories, but its connector keeps only the innermost slug,
    so the parent link is already lost upstream and a parent segment here would
    have nothing to carry. Adding one later is additive (GUIDE §4).
    """

    glossary_name: str = Field(..., description="The natural-key name of the parent glossary.")
    category_name: str = Field(
        ..., description="The natural-key name (identity segment) of the category."
    )
    display_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(*GLOSSARY_DISPLAY_NAME_SYNONYMS),
        description="A human label distinct from the identity segment, when the source has one.",
    )
    description: str | None = Field(
        default=None,
        description="The description of the category.",
    )
    resource_path: str | None = Field(
        default=None,
        description="The source's own full resource path for the category, when it has one.",
    )

    _normalize = field_validator("display_name", "description", "resource_path", mode="before")(
        coerce_str_or_none
    )


class BusinessTermRecord(BaseModel):
    """A row of the normalized BusinessTerm table (a term in a glossary category).

    ``HAS_BUSINESS_TERM`` is derivable — this key path extends the category's — so
    it is not a table. There is no ``embedding`` field: embeddings come from
    enrichment, never from a connector (GUIDE D6).

    ``display_name`` is load-bearing beyond presentation. The OSI loader merges
    business terms **by name** so its synonym-derived terms collapse onto the
    catalog terms Dataplex and CSV produce (the base glossary loader merges on id).
    Carrying the label as a first-class field means ``display_name or term_name``
    reproduces that merge key, where an identity-only record would fork duplicates.
    """

    glossary_name: str = Field(..., description="The natural-key name of the parent glossary.")
    category_name: str = Field(..., description="The natural-key name of the parent category.")
    term_name: str = Field(
        ..., description="The natural-key name (identity segment) of the business term."
    )
    display_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices(*GLOSSARY_DISPLAY_NAME_SYNONYMS),
        description=(
            "A human label distinct from the identity segment. Downstream label = "
            "display_name or term_name — the key business terms are deduped on."
        ),
    )
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "term_description"),
        description="The description of the business term.",
    )
    resource_path: str | None = Field(
        default=None,
        description="The source's own full resource path for the term, when it has one.",
    )

    _normalize = field_validator("display_name", "description", "resource_path", mode="before")(
        coerce_str_or_none
    )


class BusinessTermAssignmentRecord(BaseModel):
    """A row of the normalized business-term assignment table (the TAGGED_WITH edge).

    A cross-hierarchy attachment — a glossary key path applied to a catalog key
    path — so, like the foreign-key reference, it cannot be derived and is a table.

    The tagged asset's **grain is its key-path depth**: ``column_name`` set means
    the term attaches to that column, absent means it attaches to the table. There
    is no ``source_label`` discriminator — a graph label would couple this contract
    to the ontology (GUIDE §6) and would be a second source of truth able to
    contradict the path. Because ``column_name`` is the only optional segment, the
    path is prefix-closed by construction: a column-grain row always carries its
    table path, and a gapped path is unrepresentable rather than merely rejected.

    ``None`` here means "the path ends at the table", not "the source said
    nothing". That does not collide with GUIDE D10's unknown-vs-false rule because
    this record has no attribute columns at all — every field is a key segment, so
    a non-clobber merge has nothing to clobber.

    Table and column are the only grains any tabular producer emits today. The
    graph model also allows a Schema grain (and, for glossary terms, a Metric
    grain), but only the OSI graph/semantic paradigm produces those (GUIDE D11);
    widening the path later is additive.
    """

    database_name: str = Field(
        ...,
        validation_alias=AliasChoices(*DATABASE_NAME_SYNONYMS),
        description="Database of the tagged asset.",
    )
    schema_name: str = Field(
        ...,
        validation_alias=AliasChoices(*SCHEMA_NAME_SYNONYMS),
        description="Schema of the tagged asset.",
    )
    table_name: str = Field(
        ...,
        validation_alias=AliasChoices(*TABLE_NAME_SYNONYMS),
        description="Table of the tagged asset.",
    )
    column_name: str | None = Field(
        default=None,
        description=(
            "Column of the tagged asset; None means the term attaches to the table (the "
            "key path ends there), not that the source said nothing. A blank value is "
            "folded to None so the grain cannot read one way by truthiness and another "
            "by identity."
        ),
    )
    glossary_name: str = Field(..., description="Glossary of the applied business term.")
    category_name: str = Field(..., description="Category of the applied business term.")
    term_name: str = Field(..., description="The applied business term.")

    _normalize = field_validator("column_name", mode="before")(coerce_key_segment_or_none)


class GovernanceTagKeyRecord(BaseModel):
    """A row of the normalized governance tag-key table (a tag vocabulary's key).

    The **definition layer** — the only governance layer any connector reads today.
    The instance/assignment layer's graph model, loaders and constraints already
    exist but have no producer, so it has no source to normalize and is not
    modelled here; it lands additively with its first producer.

    ``tag_namespace`` is a namespace segment no other facet needs: governed tags
    are account-level, so the same key in two metastores is two different tags. It
    is canonically named rather than borrowing the source's ``source`` column,
    because ``source_*`` already means "the referencing side of an edge" in
    :class:`~.models.ForeignKeyRecord`; the raw column still validates via the
    alias (GUIDE D17).
    """

    tag_namespace: str = Field(
        ...,
        validation_alias=AliasChoices(*TAG_NAMESPACE_SYNONYMS),
        description=(
            "The source system's own account / metastore identifier, which scopes the "
            "tag vocabulary."
        ),
        examples=["aws:us-west-2:abc-123"],
    )
    tag_key: str = Field(
        ...,
        description="The natural-key name of the governance tag key.",
    )
    description: str | None = Field(
        default=None,
        validation_alias=AliasChoices("description", "tag_description"),
        description="What the tag means / how it should be applied.",
    )

    _normalize = field_validator("description", mode="before")(coerce_str_or_none)


class GovernanceTagValueRecord(BaseModel):
    """A row of the normalized governance tag-value table (one allowed value of a key).

    ``HAS_VALUE_OPTION`` is derivable — this key path extends the tag key's — so it
    is not a table.

    ``tag_value`` is carried **verbatim and uncoerced**, mirroring the stance the
    graph-side governance models take for the same reason: downstream identity
    content-hashes the raw value precisely so that ``High Risk``, ``high-risk`` and
    ``high_risk`` stay distinct, so normalising, stripping or fabricating it here
    would diverge from the id. Unlike a sampled column value — which can arrive
    numeric from a dtype-inferred frame — tag values are strings at the source, so
    no cast is applied either.

    A governed key with **zero** allowed values yields a key row and no value row;
    the connector drops those rows, as the Databricks extractor already does.

    No ``description``: the graph model has one, but the only producer sets it to
    ``None`` unconditionally, so there is nothing to normalize (adding it later is
    additive and parity-neutral).
    """

    tag_namespace: str = Field(
        ...,
        validation_alias=AliasChoices(*TAG_NAMESPACE_SYNONYMS),
        description="The account / metastore identifier that scopes the tag vocabulary.",
    )
    tag_key: str = Field(..., description="The natural-key name of the parent governance tag key.")
    tag_value: str = Field(
        ...,
        validation_alias=AliasChoices(*TAG_VALUE_SYNONYMS),
        description="One allowed value of the tag key, verbatim as the source spells it.",
    )


class LineageRecord(BaseModel):
    """A row of the normalized lineage table (one observed data-flow edge).

    A two-sided, **un-reified** observation: this upstream object feeds that
    downstream object. Role-scoped like :class:`~.models.ForeignKeyRecord`, and
    grain-by-depth like :class:`BusinessTermAssignmentRecord` — a side without its
    ``*_column_name`` segment is the whole table, which is what a
    ``CREATE TABLE AS SELECT`` yields before column-level resolution.

    Reification is deliberately absent. The graph model *declares* a lineage
    vocabulary — ``(:Column)-[:INPUT_TO]->(:Transform)-[:PRODUCES]->(:Column)`` —
    but marks it **not implemented**: there is no ``Transform`` model, no loader,
    and no ``RelationshipType`` member, so this record names an intended target
    rather than an existing one. Even once it exists, minting the ``Transform``
    node and choosing its key is an *identity* decision, and identity is
    ontology-declared downstream of this contract (GUIDE D6) — so a connector can
    emit these rows without knowing whether the ontology reifies them.

    Distinct from query *usage*. ``USES_TABLE`` / ``USES_COLUMN`` / ``DEFINES``
    record that a query read something, not that one object is derived from
    another, and they belong to the query paradigm that is a separate normalized
    surface (GUIDE D11).

    **No connector populates this table today**, so it carries key segments only —
    no statement type, expression or timestamp. Attributes arrive additively with
    the first producer. What would populate it already exists and discards the
    data: the Snowflake log extractor selects ``CREATE_TABLE_AS_SELECT`` /
    ``INSERT`` / ``MERGE`` rows and the shared SQL parser then keeps only the read
    direction.
    """

    source_database_name: str = Field(..., description="Database of the upstream (input) object.")
    source_schema_name: str = Field(..., description="Schema of the upstream (input) object.")
    source_table_name: str = Field(..., description="Table of the upstream (input) object.")
    source_column_name: str | None = Field(
        default=None,
        description=(
            "Column of the upstream object; None means the whole table (the key path ends "
            "there). A blank value is folded to None so the grain is unambiguous."
        ),
    )
    target_database_name: str = Field(
        ..., description="Database of the downstream (output) object."
    )
    target_schema_name: str = Field(..., description="Schema of the downstream (output) object.")
    target_table_name: str = Field(..., description="Table of the downstream (output) object.")
    target_column_name: str | None = Field(
        default=None,
        description=(
            "Column of the downstream object; None means the whole table. A blank value "
            "is folded to None so the grain is unambiguous."
        ),
    )

    _normalize = field_validator("source_column_name", "target_column_name", mode="before")(
        coerce_key_segment_or_none
    )
