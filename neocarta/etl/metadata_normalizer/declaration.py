"""The per-connector mapping declaration — the mechanism ratified by S1.6 (#297).

A connector's hand-written ``transform.py`` is replaced by a **declaration** of which cached
collection feeds which normalized table, plus a small, *named* set of escape hatches for the
things a declaration genuinely cannot express. The spike measured 52 declaration lines against
the 1 467 they replace across three connectors
([mapping-mechanism.md](../../../docs/refactor/mapping-mechanism.md) §5).

What is **not** here is as important as what is. There is no field-renaming vocabulary, because
``normalized_schema/_vocabulary.py`` already owns it — a raw BigQuery, Unity Catalog or Dataplex
row validates into ``ColumnRecord`` with zero renames. And there is no record→graph mapping,
because that half is source-agnostic and belongs to the central transform (**S3**). Those two
omissions are what keep a declaration to a couple of dozen lines.

Every hatch is a named field so its use is **countable**: the S1.6 gate metric is "declaration
LOC plus how many hatches", and an unnamed hatch would make that unmeasurable. :func:`hatch_usage`
counts exactly these four, and a fifth appearing is a documented trigger to escalate rather than
a feature.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, get_args

from pydantic import BaseModel

from neocarta.errors import ConfigError

from .normalized_schema import NormalizedStructuralSchema

#: Normalized table name → the record type the contract says that table holds.
#:
#: Read off :class:`NormalizedStructuralSchema` rather than restated here, so the bundle stays the
#: single owner of which tables exist and what each holds (GUIDE §4). A table added to the contract
#: becomes declarable with no change to this module.
TABLE_RECORD_TYPES: Mapping[str, type[BaseModel]] = MappingProxyType(
    {
        name: get_args(info.annotation)[0]
        for name, info in NormalizedStructuralSchema.model_fields.items()
    }
)


@dataclass(frozen=True)
class SourceTable:
    """Binds one cached source collection onto one normalized record type.

    Attributes:
        record: The normalized record class rows validate into (e.g. ``ColumnRecord``).
        source: The extractor accessor / cache key holding the rows, or a tuple of them when a
            connector feeds one normalized table from several collections. CSV needs the tuple
            form: it pre-splits term assignments into ``column_tagged_with_info`` and
            ``table_tagged_with_info``, which the contract models as the **one**
            ``business_term_assignments`` table whose grain is its key-path depth. The two
            concatenate into one table and the transform re-splits them by depth, which
            round-trips exactly because the table-grain frame carries no ``column_name``.
        constants: **Literal injection.** Source-level facts no row carries, merged into each
            row *before* validation so the record's own validators still apply — e.g.
            ``platform="GCP"`` reaches ``coerce_upper`` exactly as a real column would. A value
            the row already carries wins: a source that reports its own platform is more
            specific than the declaration.
        project: **The ``pre_fold`` hatch.** A source-specific row transform that may raise, for
            values the contract deliberately refuses to guess at (Dataplex's slug parsing, a
            container path that must be recovered). Runs after ``constants``.
        row_filter: **The source-level ``row_filter`` hatch.** Keeps a row only if this returns
            true. Predicates over *derived* ids are not expressible here and do not belong here
            — see :attr:`ConnectorMapping.drop_self_references`.
    """

    record: type[BaseModel]
    source: str | tuple[str, ...]
    constants: Mapping[str, Any] = field(default_factory=dict)
    project: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    row_filter: Callable[[Mapping[str, Any]], bool] | None = None

    @property
    def sources(self) -> tuple[str, ...]:
        """The declared source names as a tuple, so one and many read the same downstream."""
        return (self.source,) if isinstance(self.source, str) else self.source


@dataclass(frozen=True)
class ScopeContext:
    """Everything a ``property_scope`` hatch may consult, for one family.

    Attributes:
        family: The accessor name being scoped, e.g. ``"column_nodes"``.
        nodes: Every model already built for that family — what a whole-collection reduction
            needs (``any(node.description is not None …)``).
        source_columns: The field names the family's source rows actually carried — what a
            column-presence filter needs. Empty when the family has no source table of its own
            (a derived containment edge).
    """

    family: str
    nodes: list[Any]
    source_columns: tuple[str, ...]


@dataclass(frozen=True)
class ConnectorMapping:
    """A whole connector's mapping, replacing its hand-written ``transform.py``.

    Attributes:
        tables: Normalized table name (``"databases"``, ``"columns"``, ``"foreign_keys"``,
            ``"values"``, …) → its binding. A table left out is simply not emitted, which is how
            the sparse-by-design contract (**D10**) is expressed: a connector populates only
            what it produces.
        drop_self_references: Whether to drop a foreign key whose endpoints resolve to the same
            column id. Declarative rather than a callable, and **per-connector rather than
            universal**, because the divergence is real: BigQuery and JDBC both drop (an
            ``INFORMATION_SCHEMA`` join artefact) while the shared RDBMS base and CSV do not.
            Making it unconditional would silently change connectors outside the proof set.
            Consumed by the central transform (**S3**), which is where a *derived* id exists.
        property_scope: **The ``property_scope`` hatch** — which properties reach Neo4j per
            family. A ratified **D10** obligation
            ([merge-contract.md](../../../docs/refactor/merge-contract.md) assigns layer-1 scope
            to "the connector / normalizer"), and the single most divergent decision in the
            codebase: three semantics across four owners. ``None`` means "fall back to the
            loader's defaults", which is what BigQuery does.

            The callable takes a :class:`ScopeContext` because the two real implementations need
            *different* inputs — JDBC reduces over the built **nodes**, CSV filters the source
            **column names** — and a hatch serving only one of them would force the other
            connector to keep a hand-written transform. That both shapes have to be supported is
            itself the finding: property scope is the least declarative thing a connector does.
    """

    tables: Mapping[str, SourceTable]
    drop_self_references: bool = False
    property_scope: Callable[[ScopeContext], list[str]] | None = None

    def __post_init__(self) -> None:
        """Reject a declaration the contract cannot hold, at import time.

        Both failure modes are silent otherwise, and both would surface far from their cause: a
        misspelled table name binds rows into a table nothing reads, and a record type that does
        not match the table produces rows the bundle rejects only once someone projects it. A
        declaration is module-level, so raising here fails the import that declares it and the
        traceback points at the offending line.

        Raises:
            ConfigError: If a declared table is not one of the contract's tables, or its
                ``record`` is not the type that table holds.
        """
        for name, table in self.tables.items():
            expected = TABLE_RECORD_TYPES.get(name)
            if expected is None:
                known = ", ".join(sorted(TABLE_RECORD_TYPES))
                message = f"unknown normalized table {name!r}; the contract's tables are: {known}"
                raise ConfigError(message)
            if not issubclass(table.record, expected):
                message = (
                    f"normalized table {name!r} holds {expected.__name__}, but the declaration "
                    f"binds {table.record.__name__}"
                )
                raise ConfigError(message)


def hatch_usage(mapping: ConnectorMapping) -> dict[str, int]:
    """Count each escape hatch's uses in one declaration — the S1.6 gate metric input.

    The ⚠ go/no-go trigger needs "is this simpler?" to be a measurement rather than an
    impression (GUIDE §9), and an uncounted hatch is how a mechanism quietly becomes as complex
    as what it replaced.

    Args:
        mapping: The connector declaration to measure.

    Returns:
        Hatch name → number of uses. Hatches with no uses are omitted.
    """
    counts = {
        "pre_fold": sum(1 for table in mapping.tables.values() if table.project is not None),
        "row_filter": sum(1 for table in mapping.tables.values() if table.row_filter is not None),
        "drop_self_references": int(mapping.drop_self_references),
        "property_scope": int(mapping.property_scope is not None),
    }
    return {name: count for name, count in counts.items() if count}
