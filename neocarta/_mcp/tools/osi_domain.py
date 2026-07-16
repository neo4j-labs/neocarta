"""OSI domain-context MCP tool. Registered when OSI nodes are present."""

from fastmcp import FastMCP
from neo4j import AsyncDriver, RoutingControl

from ...connectors.utils.generate_id import generate_osi_semantic_model_id
from ..cypher import get_domain_context_cypher
from ..models import DomainContext


def register(server: FastMCP, neo4j_driver: AsyncDriver, neo4j_database: str) -> None:
    """Register the OSI domain-context tool (get_domain_context)."""

    @server.tool()
    async def get_domain_context(domain_name: str) -> DomainContext:
        """
        Retrieve the full context of one OSI domain (semantic model).

        Returns the domain's description and OSI version, every dataset (table) with its
        columns (each carrying dialect-specific expressions and aspects), every metric with
        its expressions / synonyms / aspects, and the joins between datasets. This is the
        OSI-aware, scoped counterpart to get_full_metadata_schema — bounded to one semantic
        model so it stays a sane payload. Use it when you want everything a domain owns;
        call list_domains first to obtain valid domain names and gauge payload size.

        Parameters
        ----------
        domain_name: str
            The name of the domain to retrieve. Use list_domains to get valid domain names.
        """
        cypher = get_domain_context_cypher()
        results = await neo4j_driver.execute_query(
            query_=cypher,
            parameters_={"domainId": generate_osi_semantic_model_id(domain_name)},
            database_=neo4j_database,
            routing_=RoutingControl.READ,
            result_transformer_=lambda x: x.data(),
        )
        if not results:
            # Unknown domain: echo the requested name with empty collections rather than
            # erroring, mirroring how the listing tools return empty for unknown inputs.
            return DomainContext(domain_name=domain_name)
        return DomainContext.model_validate(results[0]["result"])
