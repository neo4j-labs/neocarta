"""S1.6 (#297) mapping-mechanism spike — the half of it that is still a prototype.

The spike proved a candidate connector→normalized→graph mechanism against the committed #291
goldens. S1.7 (#298) then **promoted its record half into production**: the binder, the
declaration types, the hatches and every per-connector declaration now live under
``neocarta/etl/metadata_normalizer/`` and ``neocarta/connectors/<source>/mapping.py``, and are
re-exported here so this package's remaining tests keep driving exactly one implementation
(GUIDE §4, one owner per piece of state).

What is still a prototype is :mod:`transform` — normalized records → graph models. That half
belongs to **S3**, which will rebuild it against the canonical ontology objects and the generic
KeySpec ID builder (#305) rather than today's ``data_model`` classes and ``generate_*_id``
functions. It stays under ``tests/support/`` because that keeps it uncollected and outside
``coverage source``, so a throwaway cannot move a production measurement.

See ``docs/refactor/mapping-mechanism.md`` for the verdict, and
``tests/unit/etl/mapping_spike/`` for the Layer A parity proof this prototype still serves.
"""

from neocarta.connectors.bigquery.schema.mapping import BIGQUERY_SCHEMA
from neocarta.connectors.csv.mapping import CSV, CSV_EXCLUDED_FAMILIES
from neocarta.connectors.jdbc.schema.mapping import JDBC_SCHEMA
from neocarta.etl.metadata_normalizer import bind_all, observed_columns

from .transform import transformer_for

__all__ = [
    "BIGQUERY_SCHEMA",
    "CSV",
    "CSV_EXCLUDED_FAMILIES",
    "JDBC_SCHEMA",
    "bind_all",
    "observed_columns",
    "transformer_for",
]
