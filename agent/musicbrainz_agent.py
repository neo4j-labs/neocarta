"""MusicBrainz agent: factory, custom live-API tool, and interactive runner.

This single module bundles everything needed to run the MusicBrainz agent:

* ``musicbrainz_search`` — a LangChain tool wrapping the live MusicBrainz REST
  API (``/ws/2/{entity}?query=...``).
* ``create_musicbrainz_agent`` — a LangGraph agent factory mirroring
  ``agent/agent.py``.
* ``main`` — connects to the Neocarta MCP server (and, when Google credentials
  are available, the BigQuery MCP server), binds the tools, and runs an
  interactive chat loop.

Run it directly::

    uv run agent/musicbrainz_agent.py
"""

import asyncio
import os

import httpx
from dotenv import load_dotenv
from google.auth import default
from google.auth.transport.requests import Request
from langchain.agents import create_agent
from langchain.tools import BaseTool, tool
from langchain_litellm import ChatLiteLLM
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

load_dotenv()

# ---------------------------------------------------------------------------
# Custom live-API tool
# ---------------------------------------------------------------------------

MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
# MusicBrainz requires a descriptive User-Agent identifying the application.
USER_AGENT = "neocarta-musicbrainz-agent/0.1 ( rajvardhan.patil@neo4j.com )"
VALID_ENTITIES = {
    "artist",
    "release",
    "recording",
    "release-group",
    "label",
    "work",
    "area",
    "place",
    "url",
}


@tool
async def musicbrainz_search(query: str, entity: str = "artist", limit: int = 10) -> dict:
    """Search the live MusicBrainz REST API with a Lucene query string.

    Use this after consulting the metadata graph to confirm which MusicBrainz
    entity and fields are relevant. The ``query`` supports Lucene syntax, so
    fields can be targeted directly (e.g. ``artist:Radiohead AND country:GB``,
    ``country:JP AND ended:false``).

    Parameters
    ----------
    query : str
        A Lucene query string passed to the MusicBrainz search API.
    entity : str
        The entity type to search. One of: artist, release, recording,
        release-group, label, work, area, place, url. Defaults to ``"artist"``.
    limit : int
        Maximum number of results to return (1-25). Defaults to ``10``.

    Returns:
    -------
    dict
        The parsed JSON response from MusicBrainz, or an ``{"error": ...}``
        mapping if the entity is invalid or the request fails.
    """
    if entity not in VALID_ENTITIES:
        return {
            "error": f"Unknown entity '{entity}'. Valid entities: {sorted(VALID_ENTITIES)}",
        }

    capped_limit = max(1, min(limit, 25))
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{MUSICBRAINZ_BASE_URL}/{entity}",
                params={"query": query, "fmt": "json", "limit": capped_limit},
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        return {"error": f"MusicBrainz request failed: {e}"}


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a MusicBrainz research assistant. You answer questions
about music by combining a Neo4j metadata graph of the MusicBrainz schema with
the live MusicBrainz REST API.

Workflow:
1. Consult the metadata graph first. Use the schema tools (list_schemas,
   list_tables_by_schema, and the semantic/hybrid context tools) to discover
   which MusicBrainz entities and columns are relevant to the question.
2. Build a well-formed Lucene query and call `musicbrainz_search` with the
   appropriate entity (artist, release, recording, release-group, label, work,
   area, place, or url).
3. Return the results to the user in a clear, readable format.

Rules:
* Always ground your choice of entity and fields in the schema graph before
  querying the live API.
* Prefer targeted Lucene field queries (e.g. country:JP AND ended:false) over
  broad keyword searches.
* Summarise results concisely; include names, types, and disambiguation when
  available."""

DEFAULT_AGENT_MODEL = "gpt-4o-mini"


def create_musicbrainz_agent(tools: list[BaseTool]) -> CompiledStateGraph:
    """Create the MusicBrainz LangGraph agent with the provided tools.

    Parameters
    ----------
    tools : list[BaseTool]
        Tools to bind to the agent — typically the Neocarta MCP schema tools
        plus :func:`musicbrainz_search`.

    Returns:
    -------
    CompiledStateGraph
        The compiled agent graph ready to stream messages.
    """
    model = ChatLiteLLM(model=os.getenv("AGENT_MODEL", DEFAULT_AGENT_MODEL))
    return create_agent(
        model=model,
        tools=tools,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=InMemorySaver(),
    )


# ---------------------------------------------------------------------------
# Interactive runner
# ---------------------------------------------------------------------------


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


# Env vars forwarded to the MCP subprocess. `StdioServerParameters` rejects None
# values, so any var not set in the parent environment is dropped below.
_mcp_env_candidates = {
    "NEO4J_URI": os.getenv("NEO4J_URI"),
    "NEO4J_USERNAME": os.getenv("NEO4J_USERNAME"),
    "NEO4J_PASSWORD": os.getenv("NEO4J_PASSWORD"),
    "NEO4J_DATABASE": os.getenv("NEO4J_DATABASE"),
    "EMBEDDING_MODEL": os.getenv("EMBEDDING_MODEL", "text-embedding-3-small"),
    "OPENAI_API_KEY": os.getenv("OPENAI_API_KEY"),
}

CONFIG = {"configurable": {"thread_id": "1"}}

# The BigQuery MCP server exposes many tools; we only want SQL execution.
BIGQUERY_ALLOWED_TOOLS = {"execute_sql"}


def _build_mcp_servers() -> tuple[dict, bool]:
    """Build the MCP server params, including BigQuery only when usable.

    Returns:
    -------
    tuple[dict, bool]
        The server-params mapping and whether the BigQuery server was added.
        BigQuery requires Google application default credentials, so it is
        skipped (with a notice) when those are unavailable.
    """
    servers = {
        "sql_metadata_graph": {
            "transport": "stdio",
            "command": "uv",
            "args": ["run", "neocarta-mcp"],
            "env": {k: v for k, v in _mcp_env_candidates.items() if v is not None},
        }
    }

    bigquery_available = False
    try:
        servers["bigquery"] = {
            "transport": "http",
            "url": "https://bigquery.googleapis.com/mcp",
            "auth": GoogleAuth(),
            "headers": {"Content-Type": "application/json"},
        }
        bigquery_available = True
    except Exception as e:
        print(f"BigQuery MCP server disabled (no Google credentials): {e}")

    return servers, bigquery_available


async def main() -> None:
    """Connect to MCP servers, build the agent, and run an interactive chat loop."""
    servers, bigquery_available = _build_mcp_servers()
    client = MultiServerMCPClient(servers)

    # The neocarta server self-filters its tool set based on the target
    # database's index inventory, so we trust everything it exposes.
    neocarta_tools = await client.get_tools(server_name="sql_metadata_graph")
    tools: list[BaseTool] = list(neocarta_tools)

    # The BigQuery MCP server exposes more than we want; allowlist execute_sql.
    if bigquery_available:
        try:
            bigquery_tools = await client.get_tools(server_name="bigquery")
            tools += [t for t in bigquery_tools if t.name in BIGQUERY_ALLOWED_TOOLS]
        except Exception as e:
            print(f"Could not load BigQuery tools: {e}")

    # The custom live MusicBrainz REST API tool.
    tools.append(musicbrainz_search)

    agent = create_musicbrainz_agent(tools)

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
            latest_message = chunk["messages"][-1]
            if latest_message.content:
                print(f"Agent: {latest_message.content}")
            elif hasattr(latest_message, "tool_calls") and latest_message.tool_calls:
                print(f"Calling tools: {[tc['name'] for tc in latest_message.tool_calls]}")


if __name__ == "__main__":
    asyncio.run(main())
