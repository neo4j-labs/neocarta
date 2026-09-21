"""Unit tests for the semantic-memory MCP tools (fake driver, no database).

Async tool calls are driven with ``asyncio.run`` inside sync test functions, as
elsewhere in this suite — the project pins no pytest async plugin.
"""

import asyncio
from typing import Any

from fastmcp import FastMCP

from neocarta._mcp.models import RecalledMemory
from neocarta._mcp.tools import recall_task_memory


class _FakeRecord(dict):
    """A dict standing in for a neo4j Record (both index by key)."""


class _FakeDriver:
    """Returns a canned record set per query, keyed by a substring of the cypher.

    Recall issues four distinct reads (vector, full-text, dimension probe, expand);
    matching on a fragment keeps the fake independent of the cypher's exact text.
    """

    def __init__(self, responses: dict[str, list[_FakeRecord]]) -> None:
        self.responses = responses

    async def execute_query(self, query_: str, **_: Any) -> tuple[list[_FakeRecord], None, None]:
        for fragment, records in self.responses.items():
            if fragment in query_:
                return records, None, None
        return [], None, None


class _FakeEmbedder:
    async def _create_embedding_async(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


async def _recall(responses: dict[str, list[_FakeRecord]], **kwargs: Any) -> Any:
    """Register the recall tool against a fake driver and invoke it."""
    server = FastMCP("test")
    recall_task_memory.register(server, _FakeDriver(responses), "neo4j", _FakeEmbedder())
    tool = await server.get_tool("recall_task_memory")
    return await tool.fn(question="what is our revenue in 2025?", **kwargs)


def _expand_record(observations: list[str] | None) -> _FakeRecord:
    return _FakeRecord(
        task_name="TotalRevenue2025PaidInvoices",
        observations=observations,
        phrasings=["what is our revenue in 2025?"],
        query_description="Sums paid invoice totals for 2025.",
        sql="SELECT 1",
        tables=["p.d.invoices"],
        columns=["p.d.invoices.total_usd"],
    )


def test_recall_returns_task_observations() -> None:
    """Observations captured on the Task reach the calling agent.

    They were previously write-only: capture set them, no recall path read them,
    and the only reader was the removed :Memory label's external memory server.
    """
    result = asyncio.run(
        _recall(
            {
                "phrase_vector_index": [
                    _FakeRecord(
                        eid="4:abc:1", score=0.95, matched_phrase="what is our revenue in 2025?"
                    )
                ],
                "elementId(t) = $eid": [
                    _expand_record(
                        [
                            "Revenue = SUM(invoices.total_usd) WHERE status = 'paid'.",
                            "Scoped by paid_at year, not created_at.",
                        ]
                    )
                ],
            }
        )
    )

    assert len(result.candidates) == 1
    assert result.candidates[0].observations == [
        "Revenue = SUM(invoices.total_usd) WHERE status = 'paid'.",
        "Scoped by paid_at year, not created_at.",
    ]


def test_recall_tolerates_missing_observations() -> None:
    """A Task captured before observations existed recalls as an empty list.

    The expand cypher coalesces a null property, and the tool filters null
    entries, so neither a missing nor a partly-null list can fail validation.
    """
    result = asyncio.run(
        _recall(
            {
                "phrase_vector_index": [_FakeRecord(eid="4:abc:1", score=0.9, matched_phrase="q")],
                "elementId(t) = $eid": [_expand_record([])],
            }
        )
    )
    assert result.candidates[0].observations == []


def test_recalled_memory_defaults_observations_to_empty_list() -> None:
    """The field is optional, so the model stays backward compatible."""
    assert RecalledMemory(task_name="X").observations == []
