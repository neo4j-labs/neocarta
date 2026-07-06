"""Parse OSI metric expressions to discover the tables/columns they reference.

OSI metric expressions are SQL scalar/aggregate expressions (e.g. ``SUM(orders.sales)``)
that qualify columns by an OSI **dataset name** (or, for multi-part references, a
``database.schema.table`` source path). This module only does the SQL parsing: it returns
the *table* and *column* references found in an expression and leaves resolution of those
names against the semantic model's datasets to the caller
(:class:`~neocarta.connectors.osi.ingest.transform.OsiIngestTransformer`).
"""

import logging
from typing import NamedTuple

import sqlglot
from sqlglot.expressions import (
    CTE,
    Column,
    Lateral,
    Paren,
    Select,
    SetOperation,
    Subquery,
    Table,
    Values,
)

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


def _statement_root(node: object) -> Select | SetOperation | None:
    """Unwrap enclosing parens/subqueries to the underlying ``SELECT`` or set operation.

    Returns ``None`` for anything that isn't a statement (e.g. a bare ``SUM(...)`` scalar),
    which signals that the expression must be wrapped in ``SELECT`` before parsing.
    """
    while isinstance(node, (Paren, Subquery)):
        node = node.this
    return node if isinstance(node, (Select, SetOperation)) else None


def _outer_select_ids(node: Select | SetOperation) -> set[int]:
    """Ids of the outer-scope ``SELECT`` nodes.

    A plain statement contributes its own ``SELECT``; a set operation
    (``UNION``/``INTERSECT``/``EXCEPT``) contributes every top-level branch, since all
    branches are equally the metric's own scope. Nested subqueries/CTEs are excluded (their
    ``SELECT`` is not collected here).
    """
    if isinstance(node, Select):
        return {id(node)}
    if isinstance(node, SetOperation):
        return _outer_select_ids(node.left) | _outer_select_ids(node.right)
    return set()


def extract_references(expression: str, dialect: str | None) -> MetricExpressionRefs | None:
    """
    Parse an OSI metric expression and return the tables/columns it references.

    A full statement (``SELECT``/``WITH``/set operation), even when parenthesized, is parsed
    directly; a bare scalar expression is wrapped in ``SELECT`` so sqlglot can parse it. Only
    references in the metric's own (outer) scope are returned — tables/columns inside a nested
    subquery or CTE, and derived-table aliases (subquery/``LATERAL``/``VALUES``), are
    query-local implementation detail, not the metric's dataset dependencies. Outer ``FROM``
    aliases resolve to real names; an unqualified column is attributed to the outer scope's
    single ``FROM`` table (if there is exactly one) or, for a bare scalar expression, left for
    dataset name-matching; star (``t.*``) qualifiers still contribute their table.

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
    # Parse as-is first so a full statement (possibly parenthesized) is used directly; only a
    # bare scalar expression (not a statement) is wrapped in SELECT so sqlglot can parse it.
    try:
        stmt = _statement_root(sqlglot.parse_one(expression, read=read))
    except Exception:
        stmt = None
    if stmt is None:
        try:
            stmt = sqlglot.parse_one(f"SELECT {expression}", read=read)
        except Exception as e:  # sqlglot raises a variety of parse errors
            # Log only the exception *type* — a parse error message can echo the offending
            # expression (potential schema/PII leakage), which we never log.
            logger.warning(
                "Could not parse OSI metric expression (%s); skipping its reference extraction",
                type(e).__name__,
            )
            return None

    # The metric's own (outer) scope: the statement's SELECT, or every branch of a set
    # operation. References whose nearest enclosing SELECT is not one of these live in a nested
    # subquery/CTE and are query-local, not dataset-level dependencies of the metric.
    outer_selects = _outer_select_ids(stmt)
    if not outer_selects:
        return MetricExpressionRefs(tables=set(), columns=set())

    # Query-local names — CTE, subquery, and LATERAL/VALUES derived-table aliases: columns
    # qualified by these reference a query-local result, not a dataset.
    local_names = {node.alias for node in stmt.find_all(CTE) if node.alias}
    local_names |= {node.alias for node in stmt.find_all(Subquery) if node.alias}
    local_names |= {node.alias for node in stmt.find_all(Lateral) if node.alias}
    local_names |= {node.alias for node in stmt.find_all(Values) if node.alias}

    # Real FROM tables in the outer scope(s), with their aliases. (A single scope cannot bind
    # the same alias to two tables, so no collision handling is needed here.)
    tables: set[str] = set()
    alias_to_name: dict[str, str] = {}
    for table in stmt.find_all(Table):
        anc = table.find_ancestor(Select)
        if anc is None or id(anc) not in outer_selects:
            continue
        name = ".".join(part for part in (table.catalog, table.db, table.name) if part)
        if not name or name in local_names:
            continue
        tables.add(name)
        if table.alias:
            alias_to_name[table.alias] = name
    outer_from = set(tables)

    columns: set[tuple[str | None, str]] = set()
    for column in stmt.find_all(Column):
        anc = column.find_ancestor(Select)
        if anc is None or id(anc) not in outer_selects:
            continue
        # Reconstruct the full multi-part qualifier as written (catalog.db.table), then
        # resolve a FROM alias to its real table name.
        raw_qualifier = ".".join(part for part in (column.catalog, column.db, column.table) if part)
        if raw_qualifier in local_names:
            continue
        name = column.name
        if raw_qualifier:
            qualifier = alias_to_name.get(raw_qualifier, raw_qualifier)
            tables.add(qualifier)  # capture the table even for a star (`t.*`) reference
            if name and name != "*":
                columns.add((qualifier, name))
        elif name and name != "*":
            # Unqualified: attribute to the outer scope's single FROM table when there is
            # exactly one; for a bare scalar expression (no FROM) leave it for dataset
            # name-matching; with several FROM tables it is ambiguous, so skip it.
            if len(outer_from) == 1:
                columns.add((next(iter(outer_from)), name))
            elif not outer_from:
                columns.add((None, name))

    return MetricExpressionRefs(tables=tables, columns=columns)
