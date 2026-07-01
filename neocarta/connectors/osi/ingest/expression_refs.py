"""Parse OSI metric expressions to discover the tables/columns they reference.

OSI metric expressions are SQL scalar/aggregate expressions (e.g. ``SUM(orders.sales)``)
that qualify columns by an OSI **dataset name** (or, for multi-part references, a
``database.schema.table`` source path). This module only does the SQL parsing: it returns
the *table* and *column* references found in an expression and leaves resolution of those
names against the semantic model's datasets to the caller
(:class:`~neocarta.connectors.osi.ingest.transform.OsiIngestTransformer`).
"""

import logging
import re
from typing import NamedTuple

import sqlglot
from sqlglot.expressions import CTE, Column, Subquery, Table

logger = logging.getLogger(__name__)

#: OSI ``dialect`` enum values that are SQL, mapped (case-insensitive) to the sqlglot
#: ``read`` dialect. ``ANSI_SQL`` maps to ``None`` (sqlglot's permissive default). The OSI
#: enum is: ANSI_SQL, SNOWFLAKE, MDX, TABLEAU, DATABRICKS, MAQL
#: (open-semantic-interchange/OSI core-spec/spec.yaml). Only the SQL dialects appear here.
_OSI_TO_SQLGLOT_DIALECT: dict[str, str | None] = {
    "ansi_sql": None,
    "snowflake": "snowflake",
    "databricks": "databricks",
}

#: OSI dialects that are NOT SQL — sqlglot cannot parse them, so expressions in these
#: dialects yield no backing references and are skipped.
_NON_SQL_OSI_DIALECTS = frozenset({"mdx", "tableau", "maql"})

#: An expression that already forms a statement (starts with SELECT or WITH) is parsed
#: as-is; a bare scalar expression is wrapped in ``SELECT`` so sqlglot can parse it.
_STATEMENT_START_RE = re.compile(r"^\s*(?:select|with)\b", re.IGNORECASE)


class MetricExpressionRefs(NamedTuple):
    """References extracted from a metric expression.

    Attributes:
    ----------
    tables : set[str]
        Table/dataset references (alias-resolved real names, single-token dataset names or
        multi-part ``db.schema.table`` source paths). Includes qualifiers of star (``t.*``)
        references and ``FROM`` tables, so a table is captured even when no concrete column
        of it is referenced.
    columns : set[tuple[str | None, str]]
        ``(qualifier, column_name)`` pairs; ``qualifier`` is the alias-resolved table
        reference or ``None`` when the column is unqualified.
    """

    tables: set[str]
    columns: set[tuple[str | None, str]]


def osi_dialect_to_sqlglot(dialect: str | None) -> str | None:
    """
    Map an OSI SQL dialect name to the sqlglot ``read`` dialect.

    Parameters
    ----------
    dialect : str | None
        The OSI dialect name (e.g. ``"ANSI_SQL"``, ``"SNOWFLAKE"``, ``"DATABRICKS"``).

    Returns:
    -------
    str | None
        The sqlglot dialect string, or ``None`` for ``ANSI_SQL`` / unspecified / any dialect
        not in the SQL map (parsed with sqlglot's permissive default).
    """
    if not dialect:
        return None
    return _OSI_TO_SQLGLOT_DIALECT.get(dialect.strip().lower())


def extract_references(expression: str, dialect: str | None) -> MetricExpressionRefs | None:
    """
    Parse an OSI metric expression and return the tables/columns it references.

    The expression is parsed as-is when it already begins with ``SELECT``/``WITH``, otherwise
    it is wrapped in ``SELECT`` so sqlglot can parse a bare scalar expression. Table aliases
    from ``FROM`` clauses are resolved to their real names, CTE-local names are ignored, and
    star (``t.*``) qualifiers still contribute their table.

    Parameters
    ----------
    expression : str
        The metric expression text.
    dialect : str | None
        The OSI dialect the expression is written in.

    Returns:
    -------
    MetricExpressionRefs | None
        The referenced tables and columns. Returns ``None`` when the expression is in a
        non-SQL OSI dialect (MDX/Tableau/MAQL) or cannot be parsed (the caller skips it).
        Returns empty sets for an empty expression.
    """
    if not expression or not expression.strip():
        return MetricExpressionRefs(tables=set(), columns=set())

    if dialect and dialect.strip().lower() in _NON_SQL_OSI_DIALECTS:
        logger.debug("Skipping non-SQL OSI dialect %r for reference extraction", dialect)
        return None

    read = osi_dialect_to_sqlglot(dialect)
    statement = expression if _STATEMENT_START_RE.match(expression) else f"SELECT {expression}"
    try:
        tree = sqlglot.parse_one(statement, read=read)
    except Exception as e:  # sqlglot raises a variety of parse errors
        # Log only the exception *type* — a parse error message can echo the offending
        # expression (potential schema/PII leakage), which we never log.
        logger.warning(
            "Could not parse OSI metric expression (%s); skipping its reference extraction",
            type(e).__name__,
        )
        return None

    # Query-local names (CTE aliases and derived-table/subquery aliases) are query-scoped,
    # not datasets — never treat them as tables, and skip columns qualified by them.
    local_names = {cte.alias for cte in tree.find_all(CTE) if cte.alias}
    local_names |= {sq.alias for sq in tree.find_all(Subquery) if sq.alias}

    # Resolve FROM-clause aliases to their real table names. An alias bound to more than one
    # distinct table (the same alias reused across sibling/nested scopes) is ambiguous, so it
    # is treated as query-local: its columns are skipped rather than mis-attributed to a
    # single arbitrary table. The real tables themselves are still captured below.
    tables: set[str] = set()
    alias_to_name: dict[str, str] = {}
    ambiguous_aliases: set[str] = set()
    for table in tree.find_all(Table):
        name = ".".join(part for part in (table.catalog, table.db, table.name) if part)
        if not name or name in local_names:
            continue
        tables.add(name)
        alias = table.alias
        if alias:
            bound = alias_to_name.get(alias)
            if bound is not None and bound != name:
                ambiguous_aliases.add(alias)
            else:
                alias_to_name[alias] = name
    for alias in ambiguous_aliases:
        alias_to_name.pop(alias, None)
    local_names |= ambiguous_aliases

    # An unqualified column only denotes a dataset column in a bare expression (no FROM). In a
    # full statement it resolves against the query's own FROM sources, not the model's
    # datasets, so unqualified columns are ignored once any FROM table is present.
    has_from_tables = tree.find(Table) is not None

    columns: set[tuple[str | None, str]] = set()
    for column in tree.find_all(Column):
        # Reconstruct the full multi-part qualifier as written (catalog.db.table), then
        # resolve a single-token alias to its real table name.
        raw_qualifier = ".".join(part for part in (column.catalog, column.db, column.table) if part)
        if raw_qualifier in local_names:
            continue
        qualifier = alias_to_name.get(raw_qualifier, raw_qualifier) if raw_qualifier else None
        if qualifier is None:
            if not has_from_tables:
                name = column.name
                if name and name != "*":
                    columns.add((None, name))
            continue
        # Capture the table even for a star reference (`t.*`), which has no real column.
        tables.add(qualifier)
        name = column.name
        if name and name != "*":
            columns.add((qualifier, name))

    return MetricExpressionRefs(tables=tables, columns=columns)
