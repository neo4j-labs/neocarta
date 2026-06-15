# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "mcp>=1.26.0",
# ]
# ///
"""Exercise a running neocarta MCP server over streamable HTTP.

The neocarta MCP server is a FastMCP server. Launch it independently over HTTP
with `neocarta-mcp --http` (entry point `neocarta._mcp.server:run`); it reads
its own Neo4j connection from the environment via load_dotenv() at startup. At
startup it probes the target Neo4j database for search indexes and the presence
of BusinessTerm nodes, then registers only the tools whose prerequisites are
satisfied. The catalog tools (`list_schemas`, `list_tables_by_schema`,
`get_full_metadata_schema`) are always registered; the search tools vary by
database. Because of this, the registered tool set must be discovered at runtime
rather than assumed.

This script is the client only. It does not launch the server and reads no
Neo4j credentials. It connects to the URL passed with `--url`, lists the
available tools with their descriptions and input schemas, then calls each tool
with a sensible probe argument and prints a short preview of every result.

Usage:
    # terminal 1: launch the server independently over HTTP. It reads NEO4J_*
    # and OPENAI_API_KEY from its .env (cp .env.example .env and fill it in).
    uv run neocarta-mcp --http --port 8000

    # terminal 2: connect the client and probe every tool
    uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp

    # probe the search tools with a custom query string
    uv run scripts/test-neocarta-mcp.py --url http://127.0.0.1:8000/mcp \
        --query "customer orders revenue"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from mcp.types import Tool

# Tools that take no arguments can be probed with an empty payload.
NO_ARG_TOOLS = frozenset({"list_schemas", "get_full_metadata_schema"})

# Default probe query for the semantic and full-text search tools. The search
# tools share a `text_content` argument, so one default covers all of them.
DEFAULT_QUERY = "customer orders and revenue"

PREVIEW_CHARS = 600


def fail(message: str) -> None:
    """Print an error to stderr and exit non-zero."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to the neocarta MCP server, list its tools, and probe each one.",
    )
    parser.add_argument(
        "--query",
        default=DEFAULT_QUERY,
        help="Probe string passed to search tools via their text_content argument.",
    )
    parser.add_argument(
        "--url",
        required=True,
        help="URL of a running streamable HTTP neocarta MCP server, e.g. "
        "http://127.0.0.1:8000/mcp. Launch one with `neocarta-mcp --http`.",
    )
    return parser.parse_args()


@asynccontextmanager
async def open_session(args: argparse.Namespace) -> AsyncIterator[ClientSession]:
    """Open an initialized MCP client session over streamable HTTP.

    The server is launched independently (`neocarta-mcp --http`); this client
    only connects to its URL. It never launches the server and reads no Neo4j
    credentials.
    """
    print(f"transport    : streamable-http -> {args.url}")
    async with streamablehttp_client(args.url) as (read, write, _get_session_id):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def build_probe_arguments(tool: Tool, query: str) -> dict[str, Any] | None:
    """Return a minimal valid argument payload for a tool, or None if unsupported.

    The catalog tools take either no arguments or a schema name; the search
    tools share a `text_content` argument. Any tool with an unrecognized
    required argument that cannot be auto-filled returns None and is skipped.
    """
    if tool.name in NO_ARG_TOOLS:
        return {}

    schema = tool.inputSchema or {}
    properties: dict[str, Any] = schema.get("properties", {})
    required: list[str] = schema.get("required", [])

    # Search tools: fill the text_content probe, leave numeric args defaulted.
    if "text_content" in properties:
        return {"text_content": query}

    # list_tables_by_schema needs a real schema name. It cannot be auto-filled
    # without first querying the database, so it is handled separately by the
    # caller after list_schemas runs.
    if tool.name == "list_tables_by_schema":
        return None

    # No required arguments at all: an empty payload is valid.
    if not required:
        return {}

    return None


def preview_result(payload: Any) -> str:
    """Return a short, single-block preview string for a tool result."""
    try:
        rendered = json.dumps(payload, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        rendered = str(payload)
    if len(rendered) > PREVIEW_CHARS:
        return rendered[:PREVIEW_CHARS] + " ... [truncated]"
    return rendered


def result_to_payload(result: Any) -> Any:
    """Extract a JSON-friendly payload from a CallToolResult."""
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured
    blocks = getattr(result, "content", None) or []
    texts = [getattr(block, "text", None) for block in blocks]
    texts = [text for text in texts if text is not None]
    if texts:
        return texts if len(texts) > 1 else texts[0]
    return blocks


async def call_tool(
    session: ClientSession, name: str, arguments: dict[str, Any]
) -> tuple[bool, str, Any]:
    """Call one tool defensively, returning (ok, preview, payload)."""
    try:
        result = await session.call_tool(name, arguments)
    except Exception as exc:  # one bad tool must not abort the whole run.
        return False, f"call raised {type(exc).__name__}: {exc}", None
    payload = result_to_payload(result)
    if getattr(result, "isError", False):
        return False, f"tool reported an error: {preview_result(payload)}", payload
    return True, preview_result(payload), payload


def first_schema_name(payload: Any) -> str | None:
    """Pull a schema name out of a list_schemas payload, if present."""
    records: Any = payload
    if isinstance(payload, str):
        try:
            records = json.loads(payload)
        except json.JSONDecodeError:
            return None
    if isinstance(records, dict):
        records = records.get("result", records)
    if isinstance(records, list):
        for record in records:
            if isinstance(record, dict) and record.get("schema_name"):
                return str(record["schema_name"])
    return None


async def run(args: argparse.Namespace) -> int:
    """Drive the full list-and-probe flow, returning a process exit code."""
    async with open_session(args) as session:
        print("\n[1/3] listing tools")
        listed = await session.list_tools()
        tools = list(listed.tools)
        if not tools:
            fail("server registered no tools; check the Neo4j database has data and indexes")

        for tool in tools:
            print(f"\n  - {tool.name}")
            if tool.description:
                summary = tool.description.strip().splitlines()[0]
                print(f"      description: {summary}")
            schema = tool.inputSchema or {}
            properties = list((schema.get("properties") or {}).keys())
            required = schema.get("required") or []
            print(f"      input args : {properties or '(none)'}")
            print(f"      required   : {required or '(none)'}")

        print(f"\n[2/3] probing {len(tools)} tools (query={args.query!r})")
        called_ok = 0
        failed = 0
        skipped: list[str] = []

        # Discover a real schema name up front so list_tables_by_schema can be
        # probed instead of skipped, when list_schemas is available.
        discovered_schema: str | None = None
        names = {tool.name for tool in tools}
        if "list_schemas" in names:
            ok, _, payload = await call_tool(session, "list_schemas", {})
            if ok:
                discovered_schema = first_schema_name(payload)

        for tool in tools:
            arguments = build_probe_arguments(tool, args.query)
            if arguments is None and tool.name == "list_tables_by_schema":
                if discovered_schema is None:
                    skipped.append(f"{tool.name} (no schema name available to probe with)")
                    print(f"\n  ~ {tool.name}: skipped, no schema name available")
                    continue
                arguments = {"schema_name": discovered_schema}
                print(f"\n  > {tool.name} (schema_name={discovered_schema!r})")
            elif arguments is None:
                skipped.append(f"{tool.name} (required args cannot be auto-filled)")
                print(f"\n  ~ {tool.name}: skipped, required args cannot be auto-filled")
                continue
            else:
                print(f"\n  > {tool.name} ({arguments or 'no args'})")

            ok, preview, _ = await call_tool(session, tool.name, arguments)
            if ok:
                called_ok += 1
                print(f"      ok: {preview}")
            else:
                failed += 1
                print(f"      FAILED: {preview}")

        print("\n[3/3] summary")
        print(f"  tools listed : {len(tools)}")
        print(f"  called ok    : {called_ok}")
        print(f"  failed       : {failed}")
        print(f"  skipped      : {len(skipped)}")
        for entry in skipped:
            print(f"      - {entry}")

        return 1 if failed else 0


async def main() -> None:
    args = parse_args()
    exit_code = await run(args)
    if exit_code != 0:
        raise SystemExit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
