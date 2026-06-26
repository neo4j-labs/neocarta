"""Unit tests for the OSI cypher factories (no database required)."""

from neocarta._mcp.cypher import (
    get_context_by_metric_business_term_hybrid_search_cypher,
    get_context_by_metric_full_text_search_cypher,
    get_context_by_metric_hybrid_search_cypher,
    get_context_by_metric_vector_search_cypher,
    get_domain_context_cypher,
    get_metric_expression_cypher,
    list_domains_cypher,
    list_metrics_by_domain_cypher,
)

_METRIC_SEARCH_BUILDERS = [
    get_context_by_metric_vector_search_cypher,
    get_context_by_metric_full_text_search_cypher,
    get_context_by_metric_hybrid_search_cypher,
    get_context_by_metric_business_term_hybrid_search_cypher,
]


def test_metric_search_uses_metric_indexes_and_projection() -> None:
    """Every metric search builder anchors on :Metric and projects the MetricContext shape."""
    for builder in _METRIC_SEARCH_BUILDERS:
        cypher = builder()
        assert "metric_vector_index" in cypher or "metric_full_text_index" in cypher
        assert "HAS_METRIC" in cypher
        assert "metric_score: score" in cypher
        # Domain scoping is always wired through the $domainId parameter.
        assert "$domainId" in cypher
        assert "$maxMetrics" in cypher


def test_business_term_metric_search_bridges_business_terms() -> None:
    """The BT-hybrid metric builder bridges through the businessterm full-text index."""
    cypher = get_context_by_metric_business_term_hybrid_search_cypher()
    assert "businessterm_full_text_index" in cypher
    assert "TAGGED_WITH" in cypher


def test_list_domains_counts_children() -> None:
    cypher = list_domains_cypher()
    for field in ("num_metrics", "num_tables", "num_columns", "num_joins"):
        assert field in cypher


def test_list_metrics_and_domain_context_are_domain_scoped() -> None:
    assert "$domainId" in list_metrics_by_domain_cypher()
    assert "$domainId" in get_domain_context_cypher()


def test_metric_expression_builder_filters_dialect() -> None:
    cypher = get_metric_expression_cypher()
    assert "$dialect" in cypher
    assert "$metricId" in cypher
    assert "$metricName" in cypher


def test_domain_context_embeds_join_aspects() -> None:
    """Join aspects ride along on get_domain_context (no standalone aspect query/tool)."""
    cypher = get_domain_context_cypher()
    assert "HAS_SOURCE_TABLE" in cypher
    # The joins projection collects HAS_ASPECT, so join aspects are reachable.
    assert "HAS_ASPECT" in cypher
