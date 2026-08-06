"""The generic metadata normalizer: a connector's private cache → the normalized schema.

The runtime realization of the mechanism S1.6 (#297) ratified, built in S1.7 (#298). See
[`README.md`](README.md) for the component's shape and
[`mapping-mechanism.md`](../../../docs/refactor/mapping-mechanism.md) for why it is this and not
Graph Spec.

- :mod:`declaration` — what a connector author writes: which cached collection feeds which
  normalized table, plus the four named escape hatches.
- :mod:`hatches` — shared implementations of the two hatches most connectors use identically.
- :mod:`binder` — source rows → normalized records, thin because ``normalized_schema`` already
  owns renaming and coercion.
- :mod:`normalizer` — :func:`normalize`, composing the above into the call S3 and S5 consume.
- ``normalized_schema`` — the shared, source-agnostic tabular contract (S1.1-S1.5).

The record→graph half is **not** here: it is source-agnostic and belongs to ``etl/transform``
(**S3**), together with the KeySpec-driven ID builder (#305).
"""

from .binder import bind, bind_all, observed_columns
from .declaration import (
    TABLE_RECORD_TYPES,
    ConnectorMapping,
    ScopeContext,
    SourceTable,
    hatch_usage,
)
from .hatches import container_path_from, static_scope
from .normalizer import NormalizedRecords, normalize

__all__ = [
    "TABLE_RECORD_TYPES",
    "ConnectorMapping",
    "NormalizedRecords",
    "ScopeContext",
    "SourceTable",
    "bind",
    "bind_all",
    "container_path_from",
    "hatch_usage",
    "normalize",
    "observed_columns",
    "static_scope",
]
