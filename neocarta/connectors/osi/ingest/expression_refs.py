"""Parse OSI metric/column expression fragments to discover their column references.

OSI metric expressions are *fragments* (e.g. ``SUM(subscriptions.arr_usd)``), not full
statements, and they qualify columns by the OSI **dataset name** rather than a catalog
``database.schema.table``. This module only does the parsing — it returns the
``(qualifier, column_name)`` pairs found in an expression and leaves resolution of those
qualifiers against the semantic model's datasets to the caller
(:class:`~neocarta.connectors.osi.ingest.transform.OsiIngestTransformer`).
"""

import logging

import sqlglot
from sqlglot.expressions import Column

logger = logging.getLogger(__name__)

#: OSI ``dialect`` name (case-insensitive) → sqlglot ``read`` dialect. ANSI / unknown
#: dialects map to ``None`` so sqlglot uses its permissive default parser. Extend as new
#: OSI dialects appear; an unmapped dialect degrades to ``None`` rather than failing.
_OSI_TO_SQLGLOT_DIALECT: dict[str, str | None] = {
    "ansi_sql": None,
    "ansi": None,
    "sql": None,
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "postgres": "postgres",
    "postgresql": "postgres",
    "redshift": "redshift",
    "databricks": "databricks",
    "spark": "spark",
    "sparksql": "spark",
    "duckdb": "duckdb",
    "mysql": "mysql",
    "tsql": "tsql",
    "sqlserver": "tsql",
    "trino": "trino",
    "presto": "presto",
}


def osi_dialect_to_sqlglot(dialect: str | None) -> str | None:
    """
    Map an OSI ``dialect`` name to the sqlglot ``read`` dialect.

    Parameters
    ----------
    dialect : str | None
        The OSI dialect name (e.g. ``"ANSI_SQL"``, ``"BigQuery"``).

    Returns:
    -------
    str | None
        The sqlglot dialect string, or ``None`` for ANSI / unknown dialects (sqlglot's
        permissive default).
    """
    if not dialect:
        return None
    return _OSI_TO_SQLGLOT_DIALECT.get(dialect.strip().lower())


def extract_column_references(
    expression: str, dialect: str | None
) -> list[tuple[str | None, str]] | None:
    """
    Parse an OSI expression fragment and return the column references it makes.

    The fragment is wrapped as ``SELECT <expression>`` so sqlglot can parse it, then every
    :class:`~sqlglot.expressions.Column` node is collected. Star projections (``*``) are
    skipped. Results are de-duplicated preserving first-seen order.

    Parameters
    ----------
    expression : str
        The metric/column expression text (a fragment, not a full statement).
    dialect : str | None
        The OSI dialect the expression is written in; mapped via
        :func:`osi_dialect_to_sqlglot`.

    Returns:
    -------
    list[tuple[str | None, str]] | None
        ``(qualifier, column_name)`` pairs, where ``qualifier`` is the table token written
        in the expression (an OSI dataset name) or ``None`` when the column is unqualified.
        Returns ``None`` when the expression cannot be parsed (the caller should skip it).
        Returns ``[]`` for an empty expression or one with no column references.
    """
    if not expression or not expression.strip():
        return []

    read = osi_dialect_to_sqlglot(dialect)
    try:
        tree = sqlglot.parse_one(f"SELECT {expression}", read=read)
    except Exception as e:
        # Log only the exception *type* — a parse error message can echo the offending
        # expression (potential schema/PII leakage), which we never log.
        logger.warning(
            "Could not parse OSI metric expression (%s); skipping its reference extraction",
            type(e).__name__,
        )
        return None

    refs: list[tuple[str | None, str]] = []
    seen: set[tuple[str | None, str]] = set()
    for column in tree.find_all(Column):
        name = column.name
        # Skip star projections (`t.*`): sqlglot models these as a Column named "*".
        if not name or name == "*":
            continue
        # OSI qualifiers are single-token dataset names. A multi-part reference
        # (``catalog``/``db``.``table``.``col``) is out of spec; using only ``column.table``
        # would silently drop the leading segment(s) and could mis-resolve to an unrelated
        # dataset, so skip it rather than guess.
        if column.args.get("db") or column.args.get("catalog"):
            logger.debug("Skipping out-of-spec multi-part qualified column reference")
            continue
        qualifier = column.table or None
        key = (qualifier, name)
        if key in seen:
            continue
        seen.add(key)
        refs.append(key)
    return refs
