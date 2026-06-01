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
USER_AGENT = "neocarta-musicbrainz-agent/0.1"
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


async def main() -> None:
    """Connect to the Neocarta MCP server, build the agent, and run a chat loop."""
    client = MultiServerMCPClient(
        {
            "sql_metadata_graph": {
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "neocarta-mcp"],
                "env": {k: v for k, v in _mcp_env_candidates.items() if v is not None},
            }
        }
    )

    # The neocarta server self-filters its tool set based on the target
    # database's index inventory, so we trust everything it exposes. Add the
    # custom live MusicBrainz REST API tool alongside it.
    neocarta_tools = await client.get_tools(server_name="sql_metadata_graph")
    tools: list[BaseTool] = [*neocarta_tools, musicbrainz_search]

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
