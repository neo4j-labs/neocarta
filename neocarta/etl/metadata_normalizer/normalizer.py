"""The component: a connector's private extractor cache → normalized-schema output.

One generic implementation, driven by a per-connector :class:`ConnectorMapping`. It composes the
two pieces the S1.x contract was missing — :mod:`binder` and :mod:`declaration` — into the single
call the pipeline (**S5**) and the central transform (**S3**) consume, and it is the boundary
**D5** names: the extractor cache goes in, the normalized schema comes out, and nothing else of
the connector's internals escapes.

What it deliberately does **not** do is turn records into graph objects. That half is
source-agnostic and belongs to ``etl/transform`` (**S3**), which also owns identity resolution via
the KeySpec builder (#305). This component never mints, reads or resolves an id.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from neocarta.errors import ConfigError

from .binder import bind_all, observed_columns
from .declaration import TABLE_RECORD_TYPES, ConnectorMapping
from .normalized_schema import NormalizedStructuralSchema


@dataclass(frozen=True)
class NormalizedRecords:
    """One connector's normalized-schema output, plus what a ``property_scope`` hatch reads.

    Two representations of the same rows are available and the difference is load-bearing.
    :attr:`records` is **sparse** — only the tables the declaration binds appear — which is how
    **D10** distinguishes *"this connector does not produce that"* from *"it produced nothing this
    run"*. :meth:`as_schema` projects onto the ratified
    :class:`~neocarta.etl.metadata_normalizer.normalized_schema.NormalizedStructuralSchema` bundle,
    whose 13 tables all default to ``[]`` and therefore **cannot** express that difference. So the
    sparse mapping is the state and the bundle is a view of it, not the other way round: keeping
    the bundle as the state would silently widen every connector to the full contract.

    Attributes:
        records: Normalized table name → its records, in declaration order and source order within
            a table. Sparse, per the above.
        source_columns: Normalized table name → the field names its source rows carried. Only a
            column-presence ``property_scope`` hatch reads this; it is captured here because it is
            a fact about the *source*, which stops being reachable once the cache is dropped.
    """

    records: Mapping[str, list[BaseModel]]
    source_columns: Mapping[str, tuple[str, ...]]

    def __post_init__(self) -> None:
        """Reject a table name the contract does not have.

        :meth:`as_schema` projects through ``NormalizedStructuralSchema(**records)``, and pydantic
        ignores unknown keys — so a mis-keyed table would vanish into the bundle with nothing
        raised. ``ConnectorMapping`` guards the declaration path, but **S3** builds this type
        directly (filtering, merging, re-keying), and that is the path the declaration guard
        cannot reach.

        Raises:
            ConfigError: If a key is not one of the contract's tables.
        """
        unknown = sorted(set(self.records) - set(TABLE_RECORD_TYPES))
        if unknown:
            known = ", ".join(sorted(TABLE_RECORD_TYPES))
            message = f"unknown normalized table(s) {unknown}; the contract's tables are: {known}"
            raise ConfigError(message)

    def as_schema(self) -> NormalizedStructuralSchema:
        """Project onto the ratified normalized-schema bundle.

        Returns:
            The contract object a connector's public output is defined as (**D5**, #292/2).
            Undeclared tables come back as empty lists, so read :attr:`records` instead when the
            declared-versus-empty distinction matters.
        """
        return NormalizedStructuralSchema(**dict(self.records))


def normalize(source: Any, mapping: ConnectorMapping) -> NormalizedRecords:
    """Bind one connector's cached extract into normalized records.

    Repeatable by construction: nothing is accumulated between calls, so normalizing the same
    extract twice yields equal output. That matters because a connector's ``transform()`` is
    re-callable after a failed ``load()``, and the spike's prototype originally appended and
    silently doubled every family.

    Args:
        source: The connector's extractor (read by attribute) or its cache as a mapping (read by
            key). Private to the connector (**D5**); it is consumed here and not retained. Each
            declared collection is read twice, so it must be re-readable — see
            :data:`~neocarta.etl.metadata_normalizer._frames.RowSource`.
        mapping: The connector's declaration. Validated when the declaration itself is
            constructed, so an unknown table or a mismatched record type has already been rejected
            by the time it reaches here.

    Returns:
        The connector's normalized-schema output.
    """
    return NormalizedRecords(
        records=bind_all(source, mapping),
        source_columns=observed_columns(source, mapping),
    )
