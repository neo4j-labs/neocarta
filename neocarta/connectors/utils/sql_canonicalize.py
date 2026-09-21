"""Canonicalize SQL so surface-variant queries hash to the same id.

Collapses: alias choice, identifier quoting/casing, keyword/function casing,
whitespace, commutative AND/OR operand order, and CTE names. Does NOT collapse
semantically-equivalent-but-structurally-different SQL (e.g. EXTRACT(YEAR...)
vs BETWEEN date range); those remain distinct queries by design.

Alias renaming is scope-aware: physical FROM/JOIN sources are numbered t1, t2,
... in document order by node identity, and each column is rewritten by the
scope it resolves in. Reusing one alias name for different tables across nested
subqueries therefore does not collide, and single-level correlated predicates
keep their two sources distinct. CTE names are query-global, renamed q1, q2,
... in definition order.

The canonical string is for hashing and link-parsing only. It is never
executed. Store the verbatim SQL separately for display.

Known limitation: correlation across more than one nesting level (a column
referencing a grandparent scope) is not handled, because sqlglot's qualify
mis-resolves such references onto the nearest table before this pass runs.
Such queries are rare in analytical SQL; the failure mode is a missed dedup
(two Query nodes for one query), never a wrong answer. See the xfail test in
tests/unit/connectors/utils/test_sql_canonicalize.py.
"""

import sqlglot
from sqlglot import exp
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import traverse_scope


def _nearest_select(node: exp.Expression) -> exp.Select | None:
    """Return the innermost SELECT that encloses `node`, or None."""
    parent = node.parent
    while parent is not None:
        if isinstance(parent, exp.Select):
            return parent
        parent = parent.parent
    return None


def canonicalize_sql(sql: str, dialect: str = "bigquery") -> str:
    """Return a deterministic canonical form of `sql`.

    Args:
        sql: The SQL text to canonicalize.
        dialect: sqlglot dialect name.

    Returns:
        Canonical single-line SQL string.
    """
    tree = sqlglot.parse_one(sql, read=dialect)
    try:
        tree = qualify(tree, dialect=dialect)
    except Exception:
        # Ambiguous unqualified columns without a schema: fall back to
        # non-validating qualification rather than failing capture.
        tree = qualify(tree, dialect=dialect, validate_qualify_columns=False)

    # CTE names are query-global (visible to every referencing scope), so number
    # them q1, q2, ... in definition order. Captured before any renaming so the
    # reference rewrite below can look up the original names.
    cte_new: dict[str, str] = {}
    for i, cte in enumerate(tree.find_all(exp.CTE), start=1):
        if cte.alias:
            cte_new[cte.alias] = f"q{i}"

    # Physical FROM/JOIN sources (real tables, CTE references, derived tables),
    # in document order, each keyed by node identity so two different sources
    # that happen to share an alias name never collide.
    sources = [
        n
        for n in tree.find_all(exp.Table, exp.Subquery)
        if isinstance(n.parent, (exp.From, exp.Join))
    ]
    new_of = {id(n): f"t{i}" for i, n in enumerate(sources, start=1)}

    # Per-scope map from the alias a column uses to that source's new name,
    # captured before aliases are mutated.
    scope_maps: list[tuple[object, dict[str, str]]] = []
    for scope in traverse_scope(tree):
        local: dict[str, str] = {}
        for n in sources:
            if _nearest_select(n) is not scope.expression:
                continue  # belongs to a nested scope; handled on its own pass
            key = (n.alias or n.name) if isinstance(n, exp.Table) else n.alias
            if key:
                local[key] = new_of[id(n)]
        scope_maps.append((scope, local))

    # Rewrite each column by the scope it resolves in. A (single-level)
    # correlated column surfaces in the outer scope's column set, so it maps to
    # the outer source's name rather than an inner one.
    done: set[int] = set()
    for scope, local in scope_maps:
        for col in scope.columns:
            if id(col) in done:
                continue
            if col.table in local:
                col.set("table", exp.to_identifier(local[col.table]))
                done.add(id(col))

    # Rewrite the source alias tokens, and CTE reference names on the way.
    for n in sources:
        if isinstance(n, exp.Table) and n.name in cte_new and not n.db:  # CTE reference
            n.set("this", exp.to_identifier(cte_new[n.name]))
        n.set("alias", exp.TableAlias(this=exp.to_identifier(new_of[id(n)])))

    # Rewrite CTE definition names (after references, so lookups use originals).
    for cte in tree.find_all(exp.CTE):
        if cte.alias in cte_new:
            cte.set("alias", exp.TableAlias(this=exp.to_identifier(cte_new[cte.alias])))

    # Sort operands of commutative boolean chains.
    for cls, builder in ((exp.And, exp.and_), (exp.Or, exp.or_)):
        for node in list(tree.find_all(cls)):
            if isinstance(node.parent, cls):
                continue  # only rewrite the root of each chain
            parts = sorted(node.flatten(), key=lambda e: e.sql())
            node.replace(builder(*parts, copy=False))

    return tree.sql(dialect=dialect, normalize=True, normalize_functions="upper", pretty=False)
