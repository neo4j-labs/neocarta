"""Unit tests for the Databricks metric-view transformer (MV YAML -> OSI models)."""

import json

import yaml

from neocarta.connectors.utils.generate_id import (
    generate_column_id,
    generate_metric_id,
    generate_osi_semantic_model_id,
    generate_table_id,
)

from .conftest import CATALOG, FULL_NAME, SCHEMA, VIEW


def test_metric_view_becomes_semantic_model_and_table(metrics_transformer, sample_metric_views):
    """The metric view maps to one OsiSemanticModel and one OsiTable (source preserved)."""
    metrics_transformer.transform(sample_metric_views)

    assert len(metrics_transformer.osi_semantic_model_nodes) == 1
    sm = metrics_transformer.osi_semantic_model_nodes[0]
    assert sm.id == generate_osi_semantic_model_id(FULL_NAME)
    assert sm.name == FULL_NAME
    # YAML top-level `comment` wins over the Unity Catalog object comment.
    assert sm.description == "Order metrics"
    assert sm.osi_version == "1.1"

    assert len(metrics_transformer.table_nodes) == 1
    table = metrics_transformer.table_nodes[0]
    assert table.id == generate_table_id(CATALOG, SCHEMA, VIEW)
    assert table.source == FULL_NAME

    assert metrics_transformer.domain_has_table_rels[0].domain_id == sm.id
    assert metrics_transformer.domain_has_table_rels[0].table_id == table.id


def test_measures_become_metrics(metrics_transformer, sample_metric_views):
    """Each measure becomes a Metric under the semantic model (one per measure)."""
    metrics_transformer.transform(sample_metric_views)

    names = sorted(m.name for m in metrics_transformer.metric_nodes)
    assert names == ["order_count", "total_revenue"]

    revenue = next(m for m in metrics_transformer.metric_nodes if m.name == "total_revenue")
    assert revenue.id == generate_metric_id(FULL_NAME, "total_revenue")
    assert revenue.description == "Gross revenue from all orders"

    assert len(metrics_transformer.has_metric_rels) == 2
    sm_id = metrics_transformer.osi_semantic_model_nodes[0].id
    assert all(r.domain_id == sm_id for r in metrics_transformer.has_metric_rels)


def test_dimensions_become_osi_columns(metrics_transformer, sample_metric_views):
    """Each field/dimension becomes an OsiColumn under the table (HAS_COLUMN)."""
    metrics_transformer.transform(sample_metric_views)

    assert len(metrics_transformer.column_nodes) == 1
    col = metrics_transformer.column_nodes[0]
    assert col.id == generate_column_id(CATALOG, SCHEMA, VIEW, "order_status")
    assert col.name == "order_status"
    assert col.label == "Order Status"
    # Metric-view fields declare no key / time-dimension metadata: left unset.
    assert col.is_time_dimension is None
    assert col.is_primary_key is None
    assert col.is_foreign_key is None

    assert len(metrics_transformer.has_column_rels) == 1
    assert metrics_transformer.has_column_rels[0].table_id == generate_table_id(
        CATALOG, SCHEMA, VIEW
    )


def test_expressions_carry_databricks_dialect(metrics_transformer, sample_metric_views):
    """measure / field expr become Expression nodes with dialect 'databricks'."""
    metrics_transformer.transform(sample_metric_views)

    # order_status.expr + total_revenue.expr + order_count.expr = 3.
    assert len(metrics_transformer.expression_nodes) == 3
    assert all(e.dialect == "databricks" for e in metrics_transformer.expression_nodes)
    expressions = {e.expression for e in metrics_transformer.expression_nodes}
    assert "SUM(o_totalprice)" in expressions
    assert "o_orderstatus" in expressions

    labels = {r.source_label for r in metrics_transformer.has_expression_rels}
    assert labels == {"Column", "Metric"}


def test_synonyms_and_display_name_become_ai_context(metrics_transformer, sample_metric_views):
    """synonyms / display_name become OsiAiContext aspects with JSON payloads."""
    metrics_transformer.transform(sample_metric_views)

    # Two aspects are produced: order_status and total_revenue each carry synonyms
    # and a display name, while order_count carries neither.
    assert len(metrics_transformer.ai_context_nodes) == 2
    payloads = [json.loads(a.data) for a in metrics_transformer.ai_context_nodes]
    assert any(p.get("display_name") == "Total Revenue" for p in payloads)
    assert any("revenue" in (p.get("synonyms") or []) for p in payloads)

    labels = {r.source_label for r in metrics_transformer.has_aspect_rels}
    assert labels == {"Column", "Metric"}


def test_synonyms_become_business_terms_and_tags(metrics_transformer, sample_metric_views):
    """Each synonym is upserted as a BusinessTerm with a TAGGED_WITH edge."""
    metrics_transformer.transform(sample_metric_views)

    names = sorted(bt.name for bt in metrics_transformer.business_term_nodes)
    assert names == ["fulfillment status", "revenue", "status", "total sales"]

    assert len(metrics_transformer.tagged_with_rels) == 4
    tagged_labels = {r.source_label for r in metrics_transformer.tagged_with_rels}
    assert tagged_labels == {"Column", "Metric"}


def test_dimensions_keyword_is_accepted(metrics_transformer):
    """``dimensions`` works as a synonym for ``fields``."""
    definition = yaml.safe_load(
        "version: '1.1'\nsource: main.sales.orders\n"
        "dimensions:\n  - name: region\n    expr: r_region\n"
        "measures:\n  - name: cnt\n    expr: COUNT(1)\n"
    )
    metrics_transformer.transform(
        [
            {
                "full_name": "main.sales.region_metrics",
                "catalog": "main",
                "schema": "sales",
                "name": "region_metrics",
                "comment": None,
                "definition": definition,
            }
        ]
    )
    assert [c.name for c in metrics_transformer.column_nodes] == ["region"]


def test_empty_input_produces_nothing(metrics_transformer):
    """Transforming no metric views populates no caches."""
    metrics_transformer.transform([])
    assert metrics_transformer.osi_semantic_model_nodes == []
    assert metrics_transformer.metric_nodes == []
