"""Normalized records → graph models. One implementation, every connector.

This is the source-agnostic half of the S1.6 candidate mechanism, and the reason a
per-connector declaration can be tiny: **nothing here varies by source.** Whatever a
connector's rows looked like, once they are normalized records this file is the only
record→graph mapping in play, replacing the same ten-method shape hand-written in eleven
``transform.py`` files.

Three things it does that a declaration cannot:

1. **Derives the containment edges.** ``HAS_SCHEMA`` / ``HAS_TABLE`` / ``HAS_COLUMN`` /
   ``HAS_VALUE`` are not normalized tables — they are *"fully derivable from the natural-key
   hierarchy each row carries"* (``normalized_schema/models.py``). Each child row yields
   exactly one edge to its parent, in child-row order, which is precisely what today's
   transforms produce from the same frames.
2. **Resolves identity.** ``resolve_id(record.explicit_id, generate_*_id(natural key))``, so
   the rare **D6** override wins and every other row keeps today's generated id. A parent
   endpoint prefers the parent's *resolved* id and falls back to generating one, so an
   override on a parent propagates into its children's edges rather than being silently
   dropped — the two are identical whenever no override is present.
3. **Applies the label fallback.** Where a record carries both a human label and an identity
   segment (``Table``, and the three glossary records), the node name is ``display_name or
   <identity segment>`` — so a source that supplies a distinct label wins and one that does not
   keeps using its key. Property scope comes from the declaration.

It emits **today's legacy ``data_model`` classes through identically-named property
accessors**, which is what makes the S1.6 parity proof possible at all: the #291 Layer A
harness is duck-typed, so the existing goldens can be reused *unchanged* as the oracle. The
generic KeySpec-driven builder and the canonical ontology objects are #298/#305/S3 — not this.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from neocarta.connectors.utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_column_id,
    generate_database_id,
    generate_glossary_id,
    generate_schema_id,
    generate_table_id,
    generate_value_id,
)
from neocarta.data_model.glossary import (
    BusinessTerm,
    Category,
    Glossary,
    HasBusinessTerm,
    HasCategory,
    TaggedWith,
)
from neocarta.data_model.instance import HasValue, Value
from neocarta.data_model.schema.rdbms import (
    Column,
    Database,
    HasColumn,
    HasSchema,
    HasTable,
    References,
    Schema,
    Table,
)
from neocarta.etl.metadata_normalizer import ScopeContext
from neocarta.etl.transform import resolve_id

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel

    from neocarta.etl.metadata_normalizer import ConnectorMapping

#: Normalized table → the families declaring it produces, and each family's docstring. A
#: containment edge belongs to its **child** table: it is one-per-child-row, and a
#: ``property_scope`` hatch asking about it means the child's source columns.
#:
#: This map is what makes the sparse contract (**D10**) structural rather than incidental. A
#: connector that does not declare ``values`` does not merely emit zero value nodes — it does
#: not expose a ``value_nodes`` accessor at all, exactly as ``JdbcSchemaTransformer`` does not.
#: Without that, the Layer A harness would serialize empty families and no sparse connector
#: could ever match its golden.
_TABLE_FAMILIES: dict[str, tuple[tuple[str, str], ...]] = {
    "databases": (("database_nodes", "The ``:Database`` nodes."),),
    "schemas": (
        ("schema_nodes", "The ``:Schema`` nodes."),
        ("has_schema_relationships", "The ``(:Database)-[:HAS_SCHEMA]->(:Schema)`` edges."),
    ),
    "tables": (
        ("table_nodes", "The ``:Table`` nodes."),
        ("has_table_relationships", "The ``(:Schema)-[:HAS_TABLE]->(:Table)`` edges."),
    ),
    "columns": (
        ("column_nodes", "The ``:Column`` nodes."),
        ("has_column_relationships", "The ``(:Table)-[:HAS_COLUMN]->(:Column)`` edges."),
    ),
    "values": (
        ("value_nodes", "The ``:Value`` nodes."),
        ("has_value_relationships", "The ``(:Column)-[:HAS_VALUE]->(:Value)`` edges."),
    ),
    "foreign_keys": (
        ("references_relationships", "The ``(:Column)-[:REFERENCES]->(:Column)`` edges."),
    ),
    "glossaries": (("glossary_nodes", "The ``:Glossary`` nodes."),),
    "categories": (
        ("category_nodes", "The ``:Category`` nodes."),
        ("has_category_relationships", "The ``(:Glossary)-[:HAS_CATEGORY]->(:Category)`` edges."),
    ),
    "business_terms": (
        ("business_term_nodes", "The ``:BusinessTerm`` nodes."),
        (
            "has_business_term_relationships",
            "The ``(:Category)-[:HAS_BUSINESS_TERM]->(:BusinessTerm)`` edges.",
        ),
    ),
    "business_term_assignments": (
        (
            "column_tagged_with_relationships",
            "The ``(:Column)-[:TAGGED_WITH]->(:BusinessTerm)`` edges.",
        ),
        (
            "table_tagged_with_relationships",
            "The ``(:Table)-[:TAGGED_WITH]->(:BusinessTerm)`` edges.",
        ),
    ),
}

#: Grain → its id generator. Paired with ``_parent_id`` so a grain and its generator cannot be
#: mismatched at a call site.
_GRAIN_ID = {
    "database": generate_database_id,
    "schema": generate_schema_id,
    "table": generate_table_id,
    "column": generate_column_id,
    "glossary": generate_glossary_id,
    "category": generate_category_id,
    "business_term": generate_business_term_id,
}

#: Accessor name → the normalized table it is built from (the inverse of the map above).
_FAMILY_SOURCE = {
    family: table for table, families in _TABLE_FAMILIES.items() for family, _ in families
}


class NormalizedTransformer:
    """Turn one connector's normalized records into graph nodes and relationships.

    Do not instantiate directly — use :func:`transformer_for`, which subclasses this with
    exactly the family accessors the connector's declaration can produce. The accessors are
    deliberately **not** on this base: a fixed set would give every connector every family, and
    a sparse connector would then serialize empty ones and never match its Layer A golden.
    """

    def __init__(self, mapping: ConnectorMapping) -> None:
        """Build a transformer for one connector's declaration.

        Args:
            mapping: The connector's mapping declaration, consulted only for the two
                whole-connector decisions (``drop_self_references``, ``property_scope``).
        """
        self._mapping = mapping
        self._out: dict[str, list[Any]] = {family: [] for family in _FAMILY_SOURCE}
        self._source_columns: dict[str, tuple[str, ...]] = {}
        # Resolved id by natural key, per grain, so a child's parent endpoint can honour a
        # parent's D6 override instead of regenerating an id that ignores it.
        self._ids: defaultdict[str, dict[tuple[str, ...], str]] = defaultdict(dict)

    def get_properties(self, family: str) -> list[str]:
        """Return the written-property allowlist for one family.

        The ``property_scope`` hatch, surfaced under the same name today's ``CSVTransformer``
        uses so the Layer A harness picks it up identically. An empty list means "no
        allowlist" — the loader's own defaults apply, which is what BigQuery relies on.

        Args:
            family: The accessor name, e.g. ``"column_nodes"``.

        Returns:
            The property names to write, or an empty list for the loader default.
        """
        if self._mapping.property_scope is None:
            return []
        return self._mapping.property_scope(
            ScopeContext(
                family=family,
                nodes=self._out[family],
                source_columns=self._source_columns.get(_FAMILY_SOURCE[family], ()),
            )
        )

    # --- The transform ----------------------------------------------------------------

    def transform(
        self,
        records: Mapping[str, list[BaseModel]],
        source_columns: Mapping[str, tuple[str, ...]] | None = None,
    ) -> NormalizedTransformer:
        """Build every family from one connector's bound normalized records.

        Args:
            records: Normalized table name → its records, as returned by
                ``binder.bind_all``. A table that is absent is simply not emitted (the
                sparse contract, **D10**).
            source_columns: Normalized table name → the field names its source rows carried.
                Only a ``property_scope`` hatch of the column-presence kind reads this.

        Returns:
            Self, so a caller can chain into ``serialize_transform``.
        """
        # Assign, don't accumulate. Today's transformers overwrite their caches
        # (``self._node_cache[...] = nodes``), so calling one twice is a no-op rather than a
        # silent doubling. Matching that matters because a connector's ``transform()`` is
        # re-callable after a failed load, and duplicated rows would reach the writer.
        self._out = {family: [] for family in _FAMILY_SOURCE}
        self._ids = defaultdict(dict)
        self._source_columns = dict(source_columns or {})
        self._transform_databases(records.get("databases", []))
        self._transform_schemas(records.get("schemas", []))
        self._transform_tables(records.get("tables", []))
        self._transform_columns(records.get("columns", []))
        self._transform_values(records.get("values", []))
        self._transform_foreign_keys(records.get("foreign_keys", []))
        self._transform_glossaries(records.get("glossaries", []))
        self._transform_categories(records.get("categories", []))
        self._transform_business_terms(records.get("business_terms", []))
        self._transform_term_assignments(records.get("business_term_assignments", []))
        return self

    def _parent_id(self, grain: str, key: tuple[str, ...]) -> str:
        """Resolve an endpoint id for one grain from its natural key.

        Prefers the id that grain's own row resolved to, so a **D6** override on a parent
        reaches its children's edges; falls back to generating one when the parent was not
        emitted, which is what every connector does today and is identical whenever no override
        is present.

        The generator is looked up from the grain rather than passed in, so the two cannot
        disagree — a caller supplying the wrong generator for a grain would produce a plausible
        but wrong id silently.
        """
        # Membership, not truthiness: `explicit-id-override.md` ratifies that absence is `None`
        # and never a falsy value, so an `or` here would regenerate over a legitimately empty id
        # instead of surfacing it.
        stored = self._ids[grain]
        return stored[key] if key in stored else _GRAIN_ID[grain](*key)

    def _transform_databases(self, records: list[Any]) -> None:
        for record in records:
            key = (record.database_name,)
            node_id = resolve_id(record.explicit_id, generate_database_id(*key))
            self._ids["database"][key] = node_id
            self._out["database_nodes"].append(
                Database(
                    id=node_id,
                    name=record.database_name,
                    description=record.description,
                    platform=record.platform,
                    service=record.service,
                )
            )

    def _transform_schemas(self, records: list[Any]) -> None:
        for record in records:
            parent = (record.database_name,)
            key = (record.database_name, record.schema_name)
            node_id = resolve_id(record.explicit_id, generate_schema_id(*key))
            self._ids["schema"][key] = node_id
            self._out["schema_nodes"].append(
                Schema(id=node_id, name=record.schema_name, description=record.description)
            )
            self._out["has_schema_relationships"].append(
                HasSchema(
                    database_id=self._parent_id("database", parent),
                    schema_id=node_id,
                )
            )

    def _transform_tables(self, records: list[Any]) -> None:
        for record in records:
            parent = (record.database_name, record.schema_name)
            key = (*parent, record.table_name)
            node_id = resolve_id(record.explicit_id, generate_table_id(*key))
            self._ids["table"][key] = node_id
            self._out["table_nodes"].append(
                Table(
                    id=node_id,
                    # The identity segment is the fallback label; a source that provides a
                    # distinct human label (Dataplex) wins.
                    name=record.display_name or record.table_name,
                    description=record.description,
                )
            )
            self._out["has_table_relationships"].append(
                HasTable(
                    schema_id=self._parent_id("schema", parent),
                    table_id=node_id,
                )
            )

    def _transform_columns(self, records: list[Any]) -> None:
        for record in records:
            parent = (record.database_name, record.schema_name, record.table_name)
            key = (*parent, record.column_name)
            node_id = resolve_id(record.explicit_id, generate_column_id(*key))
            self._ids["column"][key] = node_id
            self._out["column_nodes"].append(
                Column(
                    id=node_id,
                    name=record.column_name,
                    description=record.description,
                    type=record.data_type,
                    nullable=record.nullable,
                    is_primary_key=record.is_primary_key,
                    is_foreign_key=record.is_foreign_key,
                )
            )
            self._out["has_column_relationships"].append(
                HasColumn(
                    table_id=self._parent_id("table", parent),
                    column_id=node_id,
                )
            )

    def _transform_values(self, records: list[Any]) -> None:
        for record in records:
            parent = (
                record.database_name,
                record.schema_name,
                record.table_name,
                record.column_name,
            )
            node_id = resolve_id(record.explicit_id, generate_value_id(*parent, record.value))
            self._out["value_nodes"].append(Value(id=node_id, value=record.value))
            self._out["has_value_relationships"].append(
                HasValue(
                    column_id=self._parent_id("column", parent),
                    value_id=node_id,
                )
            )

    def _transform_foreign_keys(self, records: list[Any]) -> None:
        for record in records:
            source_key = (
                record.source_database_name,
                record.source_schema_name,
                record.source_table_name,
                record.source_column_name,
            )
            target_key = (
                record.target_database_name,
                record.target_schema_name,
                record.target_table_name,
                record.target_column_name,
            )
            source_id = self._parent_id("column", source_key)
            target_id = self._parent_id("column", target_key)
            # The `drop_self_references` hatch. A column referencing itself is an
            # INFORMATION_SCHEMA join artefact rather than a real foreign key — but only some
            # sources produce it, so this stays declared per connector rather than universal.
            if self._mapping.drop_self_references and source_id == target_id:
                continue
            self._out["references_relationships"].append(
                References(
                    source_column_id=source_id,
                    target_column_id=target_id,
                    criteria=record.criteria,
                )
            )

    # --- Glossary facet ----------------------------------------------------------------

    def _transform_glossaries(self, records: list[Any]) -> None:
        for record in records:
            key = (record.glossary_name,)
            node_id = resolve_id(record.explicit_id, generate_glossary_id(*key))
            self._ids["glossary"][key] = node_id
            self._out["glossary_nodes"].append(
                Glossary(
                    id=node_id,
                    name=record.display_name or record.glossary_name,
                    description=record.description,
                    resource_path=record.resource_path,
                )
            )

    def _transform_categories(self, records: list[Any]) -> None:
        for record in records:
            parent = (record.glossary_name,)
            key = (*parent, record.category_name)
            node_id = resolve_id(record.explicit_id, generate_category_id(*key))
            self._ids["category"][key] = node_id
            self._out["category_nodes"].append(
                Category(
                    id=node_id,
                    name=record.display_name or record.category_name,
                    description=record.description,
                    resource_path=record.resource_path,
                )
            )
            self._out["has_category_relationships"].append(
                HasCategory(
                    glossary_id=self._parent_id("glossary", parent),
                    category_id=node_id,
                )
            )

    def _transform_business_terms(self, records: list[Any]) -> None:
        for record in records:
            parent = (record.glossary_name, record.category_name)
            key = (*parent, record.term_name)
            node_id = resolve_id(record.explicit_id, generate_business_term_id(*key))
            self._ids["business_term"][key] = node_id
            self._out["business_term_nodes"].append(
                BusinessTerm(
                    id=node_id,
                    name=record.display_name or record.term_name,
                    description=record.description,
                    resource_path=record.resource_path,
                )
            )
            self._out["has_business_term_relationships"].append(
                HasBusinessTerm(
                    category_id=self._parent_id("category", parent),
                    business_term_id=node_id,
                )
            )

    def _transform_term_assignments(self, records: list[Any]) -> None:
        """Split term assignments by key-path depth into one family per endpoint label.

        The ``role_split`` hatch, and the reason it has to exist: the loader picks the
        endpoint label at its **call site**, one method per label, so a transform must hand it
        a separate collection per grain. The normalized record carries no ``source_label``
        discriminator on purpose — *"the tagged asset's grain is its key-path depth"*
        (``normalized_schema/facets.py``) — so the grain is read off the path here rather than
        trusted from a second source of truth that could contradict it.
        """
        for record in records:
            term_key = (record.glossary_name, record.category_name, record.term_name)
            term_id = self._parent_id("business_term", term_key)
            table_key = (record.database_name, record.schema_name, record.table_name)
            if record.column_name is None:
                source_id = self._parent_id("table", table_key)
                family, label = "table_tagged_with_relationships", "Table"
            else:
                column_key = (*table_key, record.column_name)
                source_id = self._parent_id("column", column_key)
                family, label = "column_tagged_with_relationships", "Column"
            self._out[family].append(
                TaggedWith(source_label=label, source_id=source_id, business_term_id=term_id)
            )


def _family_accessor(family: str, doc: str) -> property:
    """Build one read-only family accessor.

    A ``property`` specifically, because that is what the #291 Layer A harness discovers
    (``_model_families`` requires ``isinstance(getattr(cls, name, None), property)``).

    Args:
        family: The accessor name.
        doc: The accessor's docstring.

    Returns:
        The property object.
    """

    def getter(self: NormalizedTransformer) -> list[Any]:
        return self._out[family]

    getter.__doc__ = doc
    return property(getter)


def transformer_for(mapping: ConnectorMapping) -> NormalizedTransformer:
    """Build a transformer exposing exactly the families this declaration can produce.

    The accessors are generated per declaration rather than fixed on the base class so a
    connector advertises only what it emits — JDBC gets eight families and no ``value_nodes``,
    because SchemaCrawler samples no data and its declaration therefore has no ``values``
    table. That is the sparse contract (**D10**) made structural, and it is required for
    parity: a fixed 17-accessor class would serialize empty families into every connector's
    Layer A output and no sparse connector could match its committed golden.

    Args:
        mapping: The connector's declaration.

    Returns:
        A fresh transformer instance, not yet driven.
    """
    accessors = {
        family: _family_accessor(family, doc)
        for table in mapping.tables
        for family, doc in _TABLE_FAMILIES[table]
    }
    cls = type(NormalizedTransformer.__name__, (NormalizedTransformer,), accessors)
    return cls(mapping)
