"""Unit tests for metric -> backing table/column edge derivation in OSI ingest."""

from neocarta.connectors.osi.ingest.transform import OsiIngestTransformer
from neocarta.connectors.utils.generate_id import (
    create_query_id,
    generate_column_id,
    generate_metric_id,
    generate_query_column_id,
    generate_table_id,
)


def _run(spec: dict) -> OsiIngestTransformer:
    t = OsiIngestTransformer()
    t.transform(spec)
    return t


def _sm(datasets: list, metrics: list, name: str = "m") -> dict:
    return {
        "version": "0.1.1",
        "semantic_model": [{"name": name, "datasets": datasets, "metrics": metrics}],
    }


def _dataset(name: str, source: str, field_names: list[str]) -> dict:
    return {"name": name, "source": source, "fields": [{"name": f} for f in field_names]}


def _metric(name: str, *expressions: str, dialect: str = "ANSI_SQL") -> dict:
    return {
        "name": name,
        "expression": {"dialects": [{"dialect": dialect, "expression": e} for e in expressions]},
    }


def _table_edges(t: OsiIngestTransformer) -> set[tuple[str, str]]:
    return {(r.metric_id, r.table_id) for r in t.metric_uses_table_rels}


def _column_edges(t: OsiIngestTransformer) -> set[tuple[str, str]]:
    return {(r.metric_id, r.column_id) for r in t.metric_uses_column_rels}


def test_qualified_declared_columns_link_table_and_column():
    """A multi-table metric links each referenced table and declared column."""
    spec = _sm(
        datasets=[
            _dataset("store_sales", "tpcds.public.store_sales", ["ss_ext_sales_price"]),
            _dataset("customer", "tpcds.public.customer", ["c_customer_sk"]),
        ],
        metrics=[
            _metric(
                "clv",
                "SUM(store_sales.ss_ext_sales_price) / COUNT(DISTINCT customer.c_customer_sk)",
            )
        ],
    )
    t = _run(spec)
    metric_id = generate_metric_id("m", "clv")
    assert _table_edges(t) == {
        (metric_id, generate_table_id("tpcds", "public", "store_sales")),
        (metric_id, generate_table_id("tpcds", "public", "customer")),
    }
    assert _column_edges(t) == {
        (metric_id, generate_column_id("tpcds", "public", "store_sales", "ss_ext_sales_price")),
        (metric_id, generate_column_id("tpcds", "public", "customer", "c_customer_sk")),
    }


def test_qualified_undeclared_column_emits_table_only():
    """A reference to a column not declared as a dataset field yields USES_TABLE but no USES_COLUMN."""
    spec = _sm(
        datasets=[_dataset("orders", "warehouse.public.orders", ["order_id"])],
        metrics=[_metric("rev", "SUM(orders.amount)")],
    )
    t = _run(spec)
    metric_id = generate_metric_id("m", "rev")
    assert _table_edges(t) == {(metric_id, generate_table_id("warehouse", "public", "orders"))}
    assert t.metric_uses_column_rels == []


def test_unqualified_column_resolves_when_unique():
    """An unqualified column resolves to the single dataset that declares it."""
    spec = _sm(
        datasets=[_dataset("orders", "warehouse.public.orders", ["amount"])],
        metrics=[_metric("rev", "SUM(amount)")],
    )
    t = _run(spec)
    metric_id = generate_metric_id("m", "rev")
    assert _table_edges(t) == {(metric_id, generate_table_id("warehouse", "public", "orders"))}
    assert _column_edges(t) == {
        (metric_id, generate_column_id("warehouse", "public", "orders", "amount"))
    }


def test_unqualified_column_ambiguous_is_skipped():
    """An unqualified column declared by more than one dataset is skipped (no edges)."""
    spec = _sm(
        datasets=[
            _dataset("orders", "warehouse.public.orders", ["amount"]),
            _dataset("refunds", "warehouse.public.refunds", ["amount"]),
        ],
        metrics=[_metric("rev", "SUM(amount)")],
    )
    t = _run(spec)
    assert t.metric_uses_table_rels == []
    assert t.metric_uses_column_rels == []


def test_unknown_dataset_qualifier_is_skipped():
    """A qualifier that is not a dataset in the model produces no edges."""
    spec = _sm(
        datasets=[_dataset("orders", "warehouse.public.orders", ["amount"])],
        metrics=[_metric("rev", "SUM(nonexistent.amount)")],
    )
    t = _run(spec)
    assert t.metric_uses_table_rels == []
    assert t.metric_uses_column_rels == []


def test_qualified_reference_resolves_case_insensitively():
    """A qualifier whose case differs from the declared dataset name still resolves."""
    spec = _sm(
        datasets=[_dataset("orders", "warehouse.public.orders", ["amount"])],
        metrics=[_metric("rev", "SUM(Orders.amount)")],
    )
    t = _run(spec)
    metric_id = generate_metric_id("m", "rev")
    assert _table_edges(t) == {(metric_id, generate_table_id("warehouse", "public", "orders"))}
    assert _column_edges(t) == {
        (metric_id, generate_column_id("warehouse", "public", "orders", "amount"))
    }


def test_query_backed_dataset_links_by_id():
    """A metric over a query-backed dataset links the :Query owner id (label-agnostic)."""
    source = "SELECT customer_id, region FROM customers WHERE active = true"
    spec = _sm(
        datasets=[{"name": "active_customers", "source": source, "fields": [{"name": "region"}]}],
        metrics=[_metric("region_rev", "SUM(active_customers.region)")],
    )
    t = _run(spec)
    metric_id = generate_metric_id("m", "region_rev")
    query_id = create_query_id(source)
    assert _table_edges(t) == {(metric_id, query_id)}
    assert _column_edges(t) == {(metric_id, generate_query_column_id(query_id, "region"))}


def test_unparseable_metric_expression_is_skipped_without_failing_ingest():
    """An unparseable expression is skipped; other metrics still link."""
    spec = _sm(
        datasets=[_dataset("orders", "warehouse.public.orders", ["amount"])],
        metrics=[
            _metric("broken", "SUM(amount"),  # missing close paren -> unparseable
            _metric("ok", "SUM(orders.amount)"),
        ],
    )
    t = _run(spec)  # must not raise
    metric_ok = generate_metric_id("m", "ok")
    assert _table_edges(t) == {(metric_ok, generate_table_id("warehouse", "public", "orders"))}


def test_backing_edges_dedupe_across_dialects():
    """The same reference across multiple dialect expressions collapses to one edge."""
    spec = _sm(
        datasets=[_dataset("orders", "warehouse.public.orders", ["amount"])],
        metrics=[
            {
                "name": "rev",
                "expression": {
                    "dialects": [
                        {"dialect": "ANSI_SQL", "expression": "SUM(orders.amount)"},
                        {"dialect": "BigQuery", "expression": "SUM(orders.amount)"},
                    ]
                },
            }
        ],
    )
    t = _run(spec)
    assert len(t.metric_uses_table_rels) == 1
    assert len(t.metric_uses_column_rels) == 1


def test_minimal_spec_metric_links_orders_table_only(minimal_spec):
    """The shared fixture's `SUM(orders.amount)` links the orders table (amount is undeclared)."""
    t = _run(minimal_spec)
    metric_id = generate_metric_id("sales_model", "total_revenue")
    orders_id = generate_table_id("warehouse", "public", "orders")
    assert (metric_id, orders_id) in _table_edges(t)
    assert t.metric_uses_column_rels == []
