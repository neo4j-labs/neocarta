"""S1.6 (#297) mapping-mechanism spike prototype — **not** production code.

The candidate connector→normalized→graph mechanism, built here so it can be proven against
the committed #291 goldens without pre-empting the tickets that own the real components.
Housing it under ``tests/support/`` is a GUIDE §4 *"one owner per piece of state"* call:
#298/S3 owns ``metadata_normalizer`` and ``etl/transform``, so a second implementation in
``neocarta/`` would be a second owner. ``tests/support/`` is also uncollected and outside
``coverage source`` (``pyproject.toml``), so the prototype cannot move production coverage.

The three pieces, and the split that matters:

- :mod:`binder` — source rows → normalized records. Thin, because
  ``normalized_schema/_vocabulary.py`` already does the renaming and coercion.
- :mod:`connectors` — the **per-connector** declarations. What a connector author writes.
- :mod:`transform` — normalized records → graph models. **Source-agnostic**: one
  implementation replacing the same shape hand-written eleven times.

See ``docs/refactor/mapping-mechanism.md`` for the verdict this prototype establishes, and
``tests/unit/etl/mapping_spike/`` for the parity proof.
"""

from __future__ import annotations

from .binder import bind, bind_all, bind_table, observed_columns
from .connectors import BIGQUERY_SCHEMA, CSV, CSV_EXCLUDED_FAMILIES, JDBC_SCHEMA
from .declaration import ConnectorMapping, ScopeContext, SourceTable, hatch_usage
from .transform import transformer_for

__all__ = [
    "BIGQUERY_SCHEMA",
    "CSV",
    "CSV_EXCLUDED_FAMILIES",
    "JDBC_SCHEMA",
    "ConnectorMapping",
    "ScopeContext",
    "SourceTable",
    "bind",
    "bind_all",
    "bind_table",
    "hatch_usage",
    "observed_columns",
    "transformer_for",
]
