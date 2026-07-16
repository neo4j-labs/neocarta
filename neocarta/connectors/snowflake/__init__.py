"""Snowflake connectors.

Provides source connectors over Snowflake, read through the official pure-Python
``snowflake-connector-python`` (DB-API 2.0) — no Spark or JDBC runtime:

- :class:`SnowflakeSchemaConnector` — structural schema metadata
  (:Database/:Schema/:Table/:Column/:Value and their HAS_*/REFERENCES edges) read
  from a database's ``<database>.INFORMATION_SCHEMA.*`` views (with ``SHOW ...
  KEYS`` for primary/foreign keys, which INFORMATION_SCHEMA does not expose).
- :class:`SnowflakeLogsConnector` — query history (:Query/:CTE and their
  USES_TABLE/USES_COLUMN/DEFINES edges, plus the RDBMS scaffolding they touch)
  parsed from ``SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY``.
"""

from .logs import SnowflakeLogsConnector
from .schema import SnowflakeSchemaConnector

__all__ = ["SnowflakeLogsConnector", "SnowflakeSchemaConnector"]
