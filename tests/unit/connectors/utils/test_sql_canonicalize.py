"""Tests for neocarta.connectors.utils.sql_canonicalize.canonicalize_sql.

Positive groups assert that surface-variant SQL converges to a single canonical
string; negative cases assert that structurally different SQL stays distinct.
The scope-aware groups cover the alias-collision fix (nested subqueries reusing
an alias name, correlated predicates, derived tables, and CTEs).

Run: uv run pytest tests/unit/connectors/utils/test_sql_canonicalize.py -q
"""

import pytest

from neocarta.connectors.utils.sql_canonicalize import canonicalize_sql


def _assert_converges(sqls: list[str]) -> str:
    """Assert every variant canonicalizes to the same string; return it."""
    canon = [canonicalize_sql(s) for s in sqls]
    assert len(set(canon)) == 1, "variants did not converge:\n" + "\n".join(canon)
    return canon[0]


def test_group_1_single_table_alias_and_predicate_order():
    # No alias vs alias `i` (lowercase keywords) vs alias `inv` with the two
    # WHERE conjuncts flipped.
    variants = [
        "SELECT SUM(total_usd) FROM invoices "
        "WHERE status = 'paid' AND EXTRACT(YEAR FROM paid_at) = 2025",
        "select sum(i.total_usd) from invoices i "
        "where i.status = 'paid' and extract(year from i.paid_at) = 2025",
        "SELECT SUM(inv.total_usd) FROM invoices inv "
        "WHERE EXTRACT(YEAR FROM inv.paid_at) = 2025 AND inv.status = 'paid'",
    ]
    _assert_converges(variants)


def test_group_2_three_table_join_alias_choice():
    # Aliases s/p/pc vs sub/prod/cat over the same join.
    variants = [
        "SELECT s.id, p.name, pc.category_name "
        "FROM subscriptions s "
        "JOIN products p ON s.product_id = p.id "
        "JOIN product_categories pc ON p.category_id = pc.id",
        "SELECT sub.id, prod.name, cat.category_name "
        "FROM subscriptions sub "
        "JOIN products prod ON sub.product_id = prod.id "
        "JOIN product_categories cat ON prod.category_id = cat.id",
    ]
    _assert_converges(variants)


def test_group_3_cte_name_and_inner_alias():
    # CTE named `paid` vs `paid_invoices`, the second with an inner table alias.
    variants = [
        "WITH paid AS ("
        "  SELECT total_usd, paid_at FROM invoices WHERE status = 'paid'"
        ") "
        "SELECT SUM(total_usd) FROM paid WHERE EXTRACT(YEAR FROM paid_at) = 2025",
        "WITH paid_invoices AS ("
        "  SELECT i.total_usd, i.paid_at FROM invoices i WHERE i.status = 'paid'"
        ") "
        "SELECT SUM(total_usd) FROM paid_invoices "
        "WHERE EXTRACT(YEAR FROM paid_at) = 2025",
    ]
    _assert_converges(variants)


def test_nested_subquery_reuses_alias_name():
    # Same query; the uncorrelated subquery aliases `payments` as `p` vs `o`.
    # `o` collides with the outer `orders` alias only if renaming is not
    # scope-aware. Both must converge.
    variants = [
        "SELECT o.id FROM orders o WHERE o.total > (SELECT AVG(p.amt) FROM payments p)",
        "SELECT o.id FROM orders o WHERE o.total > (SELECT AVG(o.amt) FROM payments o)",
    ]
    _assert_converges(variants)


def test_single_level_correlated_subquery():
    # Correlated predicate `pay.oid = ord.id` references both the inner and the
    # outer source. Alias renames must converge AND keep the two sources
    # distinct (no collapse to one alias).
    variants = [
        "SELECT o.id FROM orders o "
        "WHERE o.total > (SELECT AVG(p.amt) FROM payments p WHERE p.oid = o.id)",
        "SELECT ord.id FROM orders ord "
        "WHERE ord.total > (SELECT AVG(pay.amt) FROM payments pay WHERE pay.oid = ord.id)",
    ]
    canonical = _assert_converges(variants)
    # The inner and outer tables must remain distinguishable.
    assert "t1" in canonical
    assert "t2" in canonical


def test_derived_table_alias_choice():
    # Subquery in FROM aliased `d`/inner `a` vs `sub`/inner `z`.
    variants = [
        "SELECT d.x FROM (SELECT a.k AS x FROM foo a) d",
        "SELECT sub.x FROM (SELECT z.k AS x FROM foo z) sub",
    ]
    _assert_converges(variants)


def test_cte_referenced_twice_alias_choice():
    # A CTE self-joined under two aliases; both name and alias choices vary.
    variants = [
        "WITH c AS (SELECT k, v FROM foo) "
        "SELECT c1.k FROM c c1 JOIN c c2 ON c1.k = c2.k",
        "WITH cte AS (SELECT k, v FROM foo) "
        "SELECT a.k FROM cte a JOIN cte b ON a.k = b.k",
    ]
    _assert_converges(variants)


def test_negative_semantic_variants_do_not_converge():
    # Same intent, structurally different predicates: must stay distinct.
    extract_form = (
        "SELECT SUM(total_usd) FROM invoices "
        "WHERE EXTRACT(YEAR FROM paid_at) = 2025"
    )
    between_form = (
        "SELECT SUM(total_usd) FROM invoices "
        "WHERE paid_at BETWEEN '2025-01-01' AND '2025-12-31'"
    )
    assert canonicalize_sql(extract_form) != canonicalize_sql(between_form)


def test_negative_correlated_vs_uncorrelated_do_not_converge():
    # Adding a correlation predicate changes the query; must stay distinct.
    correlated = (
        "SELECT o.id FROM orders o "
        "WHERE o.total > (SELECT AVG(p.amt) FROM payments p WHERE p.oid = o.id)"
    )
    uncorrelated = (
        "SELECT o.id FROM orders o "
        "WHERE o.total > (SELECT AVG(p.amt) FROM payments p)"
    )
    assert canonicalize_sql(correlated) != canonicalize_sql(uncorrelated)


@pytest.mark.xfail(
    reason="sqlglot qualify mis-resolves grandparent correlation onto the "
    "nearest table; see module docstring known limitation.",
    strict=True,
)
def test_multi_level_correlation_known_limitation():
    # A predicate two nesting levels deep references the top-level `orders`
    # alias. qualify mangles it, so the two alias renames do not converge.
    variants = [
        "SELECT o.id FROM orders o WHERE EXISTS ("
        "  SELECT 1 FROM lines l WHERE l.oid = o.id AND EXISTS ("
        "    SELECT 1 FROM taxes t WHERE t.lid = l.id AND t.oid = o.id))",
        "SELECT ord.id FROM orders ord WHERE EXISTS ("
        "  SELECT 1 FROM lines ln WHERE ln.oid = ord.id AND EXISTS ("
        "    SELECT 1 FROM taxes tx WHERE tx.lid = ln.id AND tx.oid = ord.id))",
    ]
    _assert_converges(variants)
