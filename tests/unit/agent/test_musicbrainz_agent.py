"""Unit tests for the MusicBrainz agent module.

Covers the custom ``musicbrainz_search`` tool (with the network patched out)
and the ``create_musicbrainz_agent`` factory (construction only, no LLM calls).

Async tool calls are driven with ``asyncio.run`` inside sync test functions,
matching the convention in ``tests/unit/enrichment/embeddings``.
"""

import asyncio

import httpx
import pytest
from langgraph.graph.state import CompiledStateGraph

from agent.musicbrainz_agent import (
    MUSICBRAINZ_BASE_URL,
    create_musicbrainz_agent,
    musicbrainz_search,
)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


@pytest.fixture
def captured_request(monkeypatch):
    """Patch httpx.AsyncClient.get and capture the outgoing request args."""
    captured: dict = {}
    payload = {"artists": [{"id": "abc", "name": "Boris"}], "count": 1}

    async def fake_get(self, url, params=None, headers=None):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return _FakeResponse(payload)

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    captured["payload"] = payload
    return captured


def test_search_builds_request_and_returns_json(captured_request):
    result = asyncio.run(
        musicbrainz_search.ainvoke({"query": "country:JP", "entity": "artist", "limit": 5})
    )

    assert captured_request["url"] == f"{MUSICBRAINZ_BASE_URL}/artist"
    assert captured_request["params"] == {"query": "country:JP", "fmt": "json", "limit": 5}
    assert captured_request["headers"]["User-Agent"].startswith("neocarta-musicbrainz-agent")
    assert result == captured_request["payload"]


def test_search_caps_limit(captured_request):
    asyncio.run(musicbrainz_search.ainvoke({"query": "x", "entity": "release", "limit": 100}))
    assert captured_request["params"]["limit"] == 25

    asyncio.run(musicbrainz_search.ainvoke({"query": "x", "entity": "release", "limit": 0}))
    assert captured_request["params"]["limit"] == 1


def test_search_rejects_unknown_entity(monkeypatch):
    called = False

    async def fail_get(self, *args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(httpx.AsyncClient, "get", fail_get)
    result = asyncio.run(musicbrainz_search.ainvoke({"query": "x", "entity": "bogus"}))

    assert "error" in result
    assert not called


def test_search_handles_http_error(monkeypatch):
    async def boom_get(self, url, params=None, headers=None):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx.AsyncClient, "get", boom_get)
    result = asyncio.run(musicbrainz_search.ainvoke({"query": "x", "entity": "artist"}))

    assert "error" in result


def test_create_agent_returns_compiled_graph():
    agent = create_musicbrainz_agent([])
    assert isinstance(agent, CompiledStateGraph)
