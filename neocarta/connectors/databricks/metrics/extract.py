"""Databricks Unity Catalog metric-view extractor.

Discovers **metric views** (Business Semantics) in a catalog's schema over a
Databricks SQL warehouse using the injected ``databricks.sql`` (DB-API 2.0)
connection — no Spark, no JDBC — and reads each one's YAML definition. Mirrors
the schema extractor's transport (caller-owned connection, identifier
backtick-quoting, ``information_schema``) but produces parsed metric-view
mappings rather than tabular schema frames.

Read path (verified against a live workspace):

- **Discovery** — metric views are a distinct relational object: they appear in
  ``<catalog>.information_schema.tables`` with ``table_type = 'METRIC_VIEW'``.
  (They do *not* appear in ``information_schema.views``, so the regular-view
  definition column cannot be used.)
- **Definition** — ``DESCRIBE TABLE EXTENDED <view> AS JSON`` returns a single
  ``json_metadata`` payload whose ``view_text`` field is the metric view's raw
  YAML definition. (``SHOW CREATE TABLE`` also returns the YAML, embedded in a
  ``CREATE VIEW … AS $$…$$`` statement, as a fallback.) The YAML is parsed with
  ``yaml.safe_load``; Databricks normalizes the spec's ``fields`` keyword to
  ``dimensions`` on storage, which the transformer accepts.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import yaml

from ...._logging import log_stage
from ....errors import ConfigError
from .._errors import wrap_databricks_errors
from .models import MetricViewInfo

if TYPE_CHECKING:
    import pandas as pd
    from databricks.sql.client import Connection

# The Unity Catalog ``information_schema.tables.table_type`` value for metric views.
_METRIC_VIEW_TABLE_TYPE = "METRIC_VIEW"


def _quote_identifier(identifier: str) -> str:
    """Backtick-quote a SQL identifier, rejecting embedded backticks.

    Identifiers (catalog / schema / view names) cannot be passed as bound
    parameters, so they are interpolated into the query — backtick-quoted after
    rejecting any name that itself contains a backtick (which could break out of
    the quoting). Value literals use bound parameters instead.

    Parameters
    ----------
    identifier : str
        The identifier to quote.

    Returns:
    -------
    str
        The backtick-quoted identifier.

    Raises:
    ------
    ConfigError
        If ``identifier`` contains a backtick.
    """
    if "`" in identifier:
        raise ConfigError(
            f"Invalid Databricks identifier {identifier!r}: backticks are not allowed.",
            suggestion="Pass a catalog/schema name without backtick characters.",
        )
    return f"`{identifier}`"


def _parse_view_text(json_metadata: Any) -> dict[str, Any] | None:
    """Extract and parse a metric view's YAML body from a ``DESCRIBE … AS JSON`` payload.

    ``DESCRIBE TABLE EXTENDED <view> AS JSON`` returns a single JSON string whose
    ``view_text`` field is the metric view's YAML definition. Returns the parsed
    YAML mapping, or ``None`` if the payload is missing / unparseable / not a
    mapping.
    """
    if not isinstance(json_metadata, str) or not json_metadata.strip():
        return None
    try:
        meta = json.loads(json_metadata)
    except (TypeError, ValueError):
        return None
    view_text = meta.get("view_text") if isinstance(meta, dict) else None
    if not isinstance(view_text, str) or not view_text.strip():
        return None
    try:
        parsed = yaml.safe_load(view_text)
    except yaml.YAMLError:
        return None
    return parsed if isinstance(parsed, dict) else None


class DatabricksMetricsExtractor:
    """Extractor for Databricks Unity Catalog metric-view definitions.

    Operates on an injected ``databricks.sql`` connection — it neither builds nor
    closes the connection (the caller owns it, mirroring the schema extractor and
    the BigQuery ``bigquery.Client``). Internal cached state is *not* part of the
    public API; callers read results through the :attr:`metric_views` property.

    Parameters
    ----------
    connection : databricks.sql.client.Connection
        An open ``databricks.sql`` connection to a SQL warehouse.
    catalog : str
        The Unity Catalog catalog to read (each catalog has its own
        ``information_schema``).
    """

    def __init__(self, connection: Connection, catalog: str) -> None:
        """Initialize the extractor with an injected connection and target catalog."""
        if connection is None:
            raise ConfigError(
                "connection is required for the Databricks metrics extractor.",
                suggestion="Pass connection=databricks.sql.connect(...).",
            )
        if not catalog:
            raise ConfigError(
                "catalog is required for the Databricks metrics extractor.",
                suggestion="Pass catalog=... (the Unity Catalog catalog name).",
            )
        self.connection = connection
        self.catalog = catalog
        self._metric_views: list[MetricViewInfo] = []

    @property
    def metric_views(self) -> list[MetricViewInfo]:
        """The metric views discovered by the most recent :meth:`extract_metric_views`."""
        return self._metric_views

    def _qualify(self) -> str:
        """Return the backtick-quoted ``<catalog>.information_schema`` prefix."""
        return f"{_quote_identifier(self.catalog)}.information_schema"

    def _run_query(self, sql: str, params: dict[str, Any] | None = None) -> pd.DataFrame:
        """Execute a read query on a fresh cursor and return a pandas DataFrame.

        One cursor per query, always closed (even when ``execute`` raises). Value
        literals are passed as bound ``params`` (pyformat ``%(name)s``); SQL text
        and parameters are never logged.
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(sql, params)
            return cursor.fetchall_arrow().to_pandas()
        finally:
            cursor.close()

    def _list_metric_views(self, schema: str) -> pd.DataFrame:
        """List the metric views in ``schema`` (name + object comment).

        Metric views are identified by ``table_type = 'METRIC_VIEW'`` in
        ``information_schema.tables`` — they are not regular views, so they do not
        appear in ``information_schema.views``.
        """
        return self._run_query(
            f"""
SELECT
    table_name AS table_name,
    comment AS table_comment
FROM {self._qualify()}.tables
WHERE table_catalog = %(catalog)s
    AND table_schema = %(schema)s
    AND table_type = %(table_type)s
ORDER BY table_name
""",
            {
                "catalog": self.catalog,
                "schema": schema,
                "table_type": _METRIC_VIEW_TABLE_TYPE,
            },
        )

    def _read_metric_view_yaml(self, schema: str, table_name: str) -> dict[str, Any] | None:
        """Read and parse one metric view's YAML definition via ``DESCRIBE … AS JSON``."""
        fq = (
            f"{_quote_identifier(self.catalog)}."
            f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"
        )
        df = self._run_query(f"DESCRIBE TABLE EXTENDED {fq} AS JSON")
        if df.empty:
            return None
        return _parse_view_text(df.iloc[0, 0])

    @wrap_databricks_errors
    @log_stage
    def extract_metric_views(self, schema: str, cache: bool = True) -> list[MetricViewInfo]:
        """Discover metric views in ``schema`` and parse each one's YAML definition.

        Parameters
        ----------
        schema : str
            The Unity Catalog schema to scan within the connector's catalog.
        cache : bool, default True
            Whether to cache the result on the extractor.

        Returns:
        -------
        list[MetricViewInfo]
            One entry per discovered metric view whose definition parsed cleanly.
        """
        listing = self._list_metric_views(schema)

        metric_views: list[MetricViewInfo] = []
        for row in listing.itertuples(index=False):
            definition = self._read_metric_view_yaml(schema, row.table_name)
            if definition is None:
                continue
            comment = row.table_comment if isinstance(row.table_comment, str) else None
            metric_views.append(
                MetricViewInfo(
                    full_name=f"{self.catalog}.{schema}.{row.table_name}",
                    catalog=self.catalog,
                    schema=schema,
                    name=row.table_name,
                    comment=comment,
                    definition=definition,
                )
            )

        if cache:
            self._metric_views = metric_views
        return metric_views
