"""OSI definition-gathering MCP tools (metric expressions).

Aspects are intentionally not a standalone tool: they ride along on the context payloads
(``DomainContext`` — including its tables/columns/metrics/joins — ``MetricContext``, and the
table/column search hits), so an agent already receives them with the entity it asked for.
"""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.utils.generate_id import generate_metric_id
from ..cypher import get_metric_expression_cypher
from ..models import ExpressionContext


def register(server: FastMCP, neo4j_driver: AsyncDriver, neo4j_database: str) -> None:
    """Register the OSI definition tools (get_metric_expression)."""

    @server.tool()
    async def get_metric_expression(
        metric_name: str,
        domain_name: str | None = None,
        dialect: str | None = None,
    ) -> list[ExpressionContext]:
        """
        Return the runnable SQL expression(s) that define a metric.

        This is the direct feed for query generation: a metric carries a vetted,
        dialect-specific definition (e.g. ``SUM(CASE WHEN status = 'active' THEN arr_usd
        ELSE 0 END)``). Optionally filter to a single SQL ``dialect``.

        Parameters
        ----------
        metric_name: str
            The name of the metric.
        domain_name: str | None
            The domain that owns the metric. When supplied the metric is resolved exactly;
            when omitted, expressions for every metric with this name (across domains) are
            returned.
        dialect: str | None
            When set, restrict results to expressions of that SQL dialect (e.g. "ANSI_SQL").
        """
        metric_id = generate_metric_id(domain_name, metric_name) if domain_name else None
        cypher = get_metric_expression_cypher()
        return await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={
                "metricId": metric_id,
                "metricName": metric_name,
                "dialect": dialect,
            },
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
