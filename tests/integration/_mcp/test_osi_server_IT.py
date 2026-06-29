"""Integration tests for the OSI MCP tools (domains, metrics, expressions, aspects)."""

import asyncio

from tests.integration._mcp.test_server_IT import _call_tool, _list_registered_tools

DOMAIN_NAME = "acme_corp_model"
EXPECTED_METRIC_NAMES = {
    "total_arr_usd",
    "total_mrr_usd",
    "pipeline_amount_usd",
    "weighted_pipeline_usd",
    "won_revenue_usd",
    "active_headcount",
    "customer_count",
    "avg_csat",
    "total_invoiced_usd",
}


def test_osi_tools_registered(neo4j_connection, osi_loaded_graph):
    """With an OSI model loaded, the reference, domain, definition, and metric tools register."""
    tools = asyncio.run(_list_registered_tools(neo4j_connection))

    assert {
        "list_domains",
        "list_metrics_by_domain",
        "get_domain_context",
        "get_metric_expression",
    }.issubset(tools)
    # Aspects are embedded in the context payloads, not a standalone tool.
    assert "get_aspects" not in tools
    # The OSI load creates Metric + BusinessTerm full-text indexes and the fixture adds a
    # Metric vector index; with BusinessTerm nodes present the metric tool registers at the
    # top business-term-bridged tier (and the lower metric tiers do not).
    assert "get_context_by_metric_business_term_hybrid_search" in tools
    assert tools.isdisjoint(
        {
            "get_context_by_metric_vector_search",
            "get_context_by_metric_full_text_search",
            "get_context_by_metric_hybrid_search",
        }
    )


def test_list_domains_reports_counts(neo4j_connection, osi_loaded_graph):
    """list_domains returns the semantic model with non-zero size counts."""
    data = asyncio.run(_call_tool(neo4j_connection, "list_domains"))

    assert len(data) == 1
    domain = data[0]
    assert domain["domain_name"] == DOMAIN_NAME
    assert domain["num_metrics"] == len(EXPECTED_METRIC_NAMES)
    assert domain["num_tables"] > 20
    assert domain["num_columns"] > domain["num_tables"]
    assert domain["num_joins"] > 0


def test_list_metrics_by_domain(neo4j_connection, osi_loaded_graph):
    """list_metrics_by_domain enumerates the metrics the domain owns."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "list_metrics_by_domain", {"domain_name": DOMAIN_NAME})
    )

    names = {r["metric_name"] for r in data}
    assert names == EXPECTED_METRIC_NAMES
    for record in data:
        assert record["domain_name"] == DOMAIN_NAME


def test_list_metrics_by_domain_unknown_returns_empty(neo4j_connection, osi_loaded_graph):
    """list_metrics_by_domain returns an empty list for an unknown domain."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "list_metrics_by_domain", {"domain_name": "nope"})
    )
    assert data == []


def test_get_domain_context(neo4j_connection, osi_loaded_graph):
    """get_domain_context returns the full context of the semantic model."""
    data = asyncio.run(
        _call_tool(neo4j_connection, "get_domain_context", {"domain_name": DOMAIN_NAME})
    )

    assert data["domain_name"] == DOMAIN_NAME
    assert data["osi_version"] == "0.1.1"
    # Domain-level ai_context instructions are surfaced as an aspect.
    assert any(a["aspect_type"] == "ai_context" for a in data["aspects"])

    assert len(data["metrics"]) == len(EXPECTED_METRIC_NAMES)
    assert {m["metric_name"] for m in data["metrics"]} == EXPECTED_METRIC_NAMES

    # Each metric carries its backing tables/columns derived from its expression (#210).
    arr_metric = next(m for m in data["metrics"] if m["metric_name"] == "total_arr_usd")
    assert "subscriptions" in arr_metric["backing_tables"]
    assert any(c.endswith("arr_usd") for c in arr_metric["backing_columns"])

    assert len(data["tables"]) > 20
    assert len(data["joins"]) > 0

    # Every dataset field carries an ANSI_SQL expression in the sample model.
    a_table = next(t for t in data["tables"] if t["columns"])
    assert all(c["expressions"] for c in a_table["columns"])

    # OSI richness is surfaced: table primary keys and column time dimensions.
    employees = next(t for t in data["tables"] if t["table_name"] == "employees")
    assert employees["primary_key"] == ["employee_id"]
    hire_date = next(c for c in employees["columns"] if c["column_name"] == "hire_date")
    assert hire_date["is_time_dimension"] is True


def test_get_context_by_metric_search(neo4j_connection, osi_loaded_graph):
    """Metric search returns metrics with their domain, expressions, and synonyms."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_context_by_metric_business_term_hybrid_search",
            {"text_content": "annual recurring revenue", "max_metrics": 20},
        )
    )

    assert len(data) > 0
    names = {r["metric_name"] for r in data}
    assert "total_arr_usd" in names

    arr = next(r for r in data if r["metric_name"] == "total_arr_usd")
    assert arr["domain_name"] == DOMAIN_NAME
    assert arr["metric_score"] is not None
    assert arr["metric_score"] > 0.5
    assert any("arr_usd" in e["expression"] for e in arr["expressions"])
    # Backing tables/columns derived from the metric expression (issue #210): the agent
    # learns the metric reads from `subscriptions` and touches its `arr_usd` column.
    assert "subscriptions" in arr["backing_tables"]
    assert any(c.endswith("arr_usd") for c in arr["backing_columns"])
    # Metric ai_context synonyms become tagged BusinessTerms surfaced as synonyms.
    assert "ARR" in arr["synonyms"]
    # Aspects are embedded on the metric payload (no standalone get_aspects tool).
    assert any(a["aspect_type"] == "ai_context" for a in arr["aspects"])


def test_get_context_by_metric_search_domain_filter(neo4j_connection, osi_loaded_graph):
    """A non-matching domain filter on metric search yields no results."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_context_by_metric_business_term_hybrid_search",
            {"text_content": "revenue", "domain_name": "does_not_exist"},
        )
    )
    assert data == []


def test_get_metric_expression(neo4j_connection, osi_loaded_graph):
    """get_metric_expression returns the dialect-specific definition of a metric."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_metric_expression",
            {"metric_name": "total_arr_usd", "domain_name": DOMAIN_NAME},
        )
    )

    assert len(data) == 1
    assert data[0]["dialect"] == "ANSI_SQL"
    assert "arr_usd" in data[0]["expression"]


def test_get_metric_expression_dialect_filter_no_match(neo4j_connection, osi_loaded_graph):
    """An unknown dialect filter returns no expressions."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_metric_expression",
            {"metric_name": "total_arr_usd", "domain_name": DOMAIN_NAME, "dialect": "tsql"},
        )
    )
    assert data == []


def test_table_search_surfaces_osi_aspects_and_expressions(neo4j_connection, osi_loaded_graph):
    """The existing table search returns OSI column expressions and table aspects."""
    data = asyncio.run(
        _call_tool(
            neo4j_connection,
            "get_context_by_table_business_term_hybrid_search",
            {"text_content": "employees", "max_tables": 40},
        )
    )

    employees = next(r for r in data if r["table_name"] == "employees")
    # employees carries an ai_context (synonyms) aspect and a DBT custom_extensions aspect.
    aspect_types = {a["aspect_type"] for a in employees["aspects"]}
    assert "ai_context" in aspect_types
    assert "custom_extensions" in aspect_types
    # Every OSI field carries an ANSI_SQL expression.
    assert all(c["expressions"] for c in employees["columns"])
