"""OSI catalog MCP tools (domain/metric listing). Registered when OSI nodes are present."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.utils.generate_id import generate_osi_semantic_model_id
from ..cypher import list_domains_cypher, list_metrics_by_domain_cypher
from ..models import ListDomainRecord, ListMetricRecord


def register(server: FastMCP, neo4j_driver: AsyncDriver, neo4j_database: str) -> None:
    """Register the OSI catalog tools (list_domains, list_metrics_by_domain)."""

    @server.tool()
    async def list_domains() -> list[ListDomainRecord]:
        """
        List every OSI semantic model (domain) with its size counts.

        Returns each domain alongside the number of metrics, datasets (tables), columns,
        and joins it owns. The counts let you judge how large a get_domain_context payload
        would be before requesting it. This is the OSI analogue of list_schemas — the
        "what semantic models exist here?" reference. It is an independent exploration
        entry point, not a required first step for metric search.
        """
        cypher = list_domains_cypher()
        return await neo4j_driver.execute_query(
            query_=cypher,
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )

    @server.tool()
    async def list_metrics_by_domain(domain_name: str) -> list[ListMetricRecord]:
        """
        List the metrics a domain (semantic model) owns.

        Returns each metric's name and one-line description for the given domain — the OSI
        analogue of list_tables_by_schema. Use when you already know the domain and want to
        browse its metrics. Call list_domains first to obtain valid domain names.

        Parameters
        ----------
        domain_name: str
            The name of the domain to list metrics for. Use list_domains to get valid
            domain names.
        """
        cypher = list_metrics_by_domain_cypher()
        return await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"domainId": generate_osi_semantic_model_id(domain_name)},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
