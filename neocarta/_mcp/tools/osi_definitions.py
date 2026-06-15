"""OSI definition-gathering MCP tools (metric expressions, entity aspects)."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.utils.generate_id import (
    generate_join_id,
    generate_metric_id,
    generate_osi_semantic_model_id,
)
from ..cypher import get_aspects_cypher, get_metric_expression_cypher
from ..models import AspectContext, ExpressionContext

#: Entity types get_aspects accepts and how each is addressed.
_VALID_ENTITY_TYPES = ("domain", "metric", "join", "table", "column")

#: Entity types whose aspects are scoped to (and require) a domain.
_DOMAIN_SCOPED_ENTITY_TYPES = ("metric", "join", "table", "column")


def register(server: FastMCP, neo4j_driver: AsyncDriver, neo4j_database: str) -> None:
    """Register the OSI definition tools (get_metric_expression, get_aspects)."""

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

    @server.tool()
    async def get_aspects(
        entity_type: str,
        entity_name: str,
        domain_name: str | None = None,
    ) -> list[AspectContext]:
        """
        Fetch the OSI aspects attached to a domain, table, column, metric, or join.

        Aspects carry agent-facing context: ``ai_context`` (synonyms, instructions,
        examples that guide how an entity should be used) and ``custom_extensions`` (vendor
        metadata). Aspects are also embedded in the metric/domain/column context payloads;
        use this tool when you want them for one entity directly.

        Parameters
        ----------
        entity_type: str
            One of "domain", "metric", "join", "table", "column".
        entity_name: str
            The name of the entity (for "domain" this is the domain name itself).
        domain_name: str | None
            The domain that owns the entity. Required for every entity_type except
            "domain"; it both resolves the entity and scopes the lookup.
        """
        if entity_type not in _VALID_ENTITY_TYPES:
            raise ValueError(
                f"Unsupported entity_type {entity_type!r}; expected one of "
                f"{list(_VALID_ENTITY_TYPES)}"
            )
        if entity_type in _DOMAIN_SCOPED_ENTITY_TYPES and not domain_name:
            raise ValueError(f"domain_name is required when entity_type is {entity_type!r}")

        parameters: dict[str, str | None]
        if entity_type == "domain":
            parameters = {"entityId": generate_osi_semantic_model_id(entity_name)}
        elif entity_type == "metric":
            parameters = {"entityId": generate_metric_id(domain_name, entity_name)}
        elif entity_type == "join":
            parameters = {"entityId": generate_join_id(domain_name, entity_name)}
        else:  # table / column — addressed by name within the domain subgraph
            parameters = {
                "entityName": entity_name,
                "domainId": generate_osi_semantic_model_id(domain_name),
            }

        cypher = get_aspects_cypher(entity_type)
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_=parameters,
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        return [AspectContext.model_validate(r["result"]) for r in results]
