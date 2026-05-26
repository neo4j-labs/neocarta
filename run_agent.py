"""Entry point for running the Text2SQL agent with MCP server."""

import asyncio
import os

import httpx
from dotenv import load_dotenv
from google.auth import default
from google.auth.transport.requests import Request
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent.agent import create_text2sql_agent

load_dotenv()


# Custom auth class for Google Cloud
class GoogleAuth(httpx.Auth):
    """Custom httpx auth handler that injects Google Cloud bearer tokens."""

    def __init__(self) -> None:
        """Initialize credentials using the application default credentials."""
        self.credentials, _ = default()

    def auth_flow(self, request):  # noqa: ANN001, ANN201
        """Refresh the token and inject it into the request."""
        self.credentials.refresh(Request())
        request.headers["Authorization"] = f"Bearer {self.credentials.token}"
        yield request


# Env vars forwarded to the MCP subprocess. `StdioServerParameters` rejects
# None values, so any var not set in the parent environment is dropped below.
# Provider auth vars (OPENAI_API_KEY, GEMINI_API_KEY, COHERE_API_KEY, ...) are
# passed through if present so LiteLLM in the MCP server can pick them up.
_mcp_env_candidates = {
    "NEO4J_URI": os.getenv("NEO4J_URI"),
    "NEO4J_USERNAME": os.getenv("NEO4J_USERNAME"),
    "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD"),
    "NEO4J_DATABASE": os.getenv("NEO4J_DATABASE"),
    "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    # Provider credentials — set the ones your EMBEDDING_MODEL needs.
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
    # "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY"),  # noqa: ERA001
    # "COHERE_API_KEY": os.getenv("COHERE_API_KEY"),  # noqa: ERA001
    # "AZURE_API_KEY": os.getenv("AZURE_API_KEY"),  # noqa: ERA001
    # "AZURE_API_BASE": os.getenv("AZURE_API_BASE"),  # noqa: ERA001
    # "AZURE_API_VERSION": os.getenv("AZURE_API_VERSION"),  # noqa: ERA001
    # "AWS_ACCESS_KEY_ID": os.getenv("AWS_ACCESS_KEY_ID"),  # noqa: ERA001
    # "AWS_SECRET_ACCESS_KEY": os.getenv("AWS_SECRET_ACCESS_KEY"),  # noqa: ERA001
    # "AWS_REGION_NAME": os.getenv("AWS_REGION_NAME"),  # noqa: ERA001
}
sql_metadata_graph_mcp_params = {
    "transport": "stdio",
    "command": "uv",
    "args": ["run", "neocarta-mcp"],
    "env": {k: v for k, v in _mcp_env_candidates.items() if v is not None},
}

bigquery_mcp_params = {
    "transport": "http",
    "url": "https://bigquery.googleapis.com/mcp",
    "auth": GoogleAuth(),
    "headers": {
        "Content-Type": "application/json",
    },
}

client = MultiServerMCPClient(
    {
        "sql_metadata_graph": sql_metadata_graph_mcp_params,
        "bigquery": bigquery_mcp_params,
    }
)

CONFIG = {"configurable": {"thread_id": "1"}}


# run the agent with MCP server using stdio transport
async def main() -> None:
    """Connect to MCP servers, build the agent, and run an interactive chat loop."""
    # Get tools per server. The neocarta server self-filters its tool set based on
    # the target database's index inventory, so we trust everything it exposes.
    # The BigQuery MCP server exposes more than we want, so we explicitly allowlist
    # only the SQL execution tool.
    neocarta_tools = await client.get_tools(server_name="sql_metadata_graph")
    bigquery_tools = await client.get_tools(server_name="bigquery")
    bigquery_allowed = {"execute_sql"}
    allowed_tools = list(neocarta_tools) + [
        tool for tool in bigquery_tools if tool.name in bigquery_allowed
    ]

    agent = create_text2sql_agent(allowed_tools)

    # conversation loop
    print("\n===================================== Chat =====================================\n")

    while True:
        user_input = input("> ")  # noqa: ASYNC250
        if user_input.lower() in {"exit", "quit", "q"}:
            break

        async for chunk in agent.astream(
            {"messages": [{"role": "user", "content": user_input}]},
            stream_mode="values",
            config=CONFIG,
        ):
            # Each chunk contains the full state at that point
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                print(f"Agent: {latest_message.content}")

            elif hasattr(latest_message, "tool_calls") and latest_message.tool_calls:
                print(f"Calling tools: {[tc['name'] for tc in latest_message.tool_calls]}")
                print(latest_message.tool_calls)


if __name__ == "__main__":
    asyncio.run(main())
