"""Embedding utilities for the dbxcarta client."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from databricks.sdk.errors import DatabricksError

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient

logger = logging.getLogger(__name__)

# databricks-gte-large-en rejects requests with more than 150 inputs
# (BAD_REQUEST "Input embeddings size is too large, exceeding 150 limit").
# 100 is a safe fixed chunk size with margin under that cap. Embedding
# throughput is irrelevant next to the eval runtime, so this is not tuned.
EMBED_MAX_BATCH = 100


def _embed_chunk(
    ws: WorkspaceClient,
    endpoint: str,
    texts: list[str],
) -> list[list[float]]:
    """Embed a single chunk in one request, ordered to match ``texts``.

    Raises DatabricksError/KeyError/TypeError on any failure; the caller
    converts these into the ``(None, error)`` return contract.
    """
    data = ws.api_client.do(
        "POST",
        f"/serving-endpoints/{endpoint}/invocations",
        body={"input": texts},
    )
    if not isinstance(data, dict):
        actual_type = type(data).__name__
        raise TypeError(f"embedding response must be a dict, got {actual_type}")
    raw_items = data.get("data")
    if not isinstance(raw_items, list):
        raise TypeError("embedding response missing list field 'data'")

    items: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise TypeError("embedding response 'data' items must be objects")
        items.append(item)
    items.sort(key=lambda x: x["index"])
    return [item["embedding"] for item in items]


def embed_questions(
    ws: WorkspaceClient,
    endpoint: str,
    texts: list[str],
) -> tuple[list[list[float]] | None, str | None]:
    """Embed a list of texts, chunked under the endpoint input cap.

    Inputs are split into chunks of at most ``EMBED_MAX_BATCH`` so callers
    never have to know the endpoint limit. Results are concatenated in input
    order, so ``embeddings[i]`` corresponds to ``texts[i]``.

    Returns (embeddings, error). On any chunk failure the first element is
    None so callers can detect and abort rather than proceed with partial
    or missing embeddings.
    """
    if not texts:
        return [], None
    embeddings: list[list[float]] = []
    try:
        for start in range(0, len(texts), EMBED_MAX_BATCH):
            chunk = texts[start : start + EMBED_MAX_BATCH]
            embeddings.extend(_embed_chunk(ws, endpoint, chunk))
        return embeddings, None
    except (DatabricksError, KeyError, TypeError) as exc:
        logger.warning("embedding call to %s failed: %s", endpoint, exc)
        return None, str(exc)
