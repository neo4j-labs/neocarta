"""Semantic-memory recall MCP tool.

Hybrid (vector + full-text) search over stored ``Phrase`` nodes, rolled up to
their ``Task`` and expanded to the task's latest canonical ``Query``. The two
branches run as separate reads and are fused in Python: each branch is
max-normalized to [0, 1] and summed, which rewards a Task matched by both
signals while keeping the raw cosine available as the calibrated confidence
gate.

A failing branch never aborts recall — it is logged and the other branch
carries. When the vector branch contributes nothing, recall additionally
diagnoses why (most usefully, a ``phrase_vector_index`` dimension mismatch) and
returns that on the ``diagnostics`` field so the calling agent — not just the
server log — can see that ``vector_score`` is an unreliable 0.
"""

from fastmcp import FastMCP
from fastmcp.utilities.logging import get_logger
from neo4j import AsyncDriver, RoutingControl

from ...enrichment.embeddings import LiteLLMEmbeddingsConnector
from ..cypher import (
    phrase_vector_index_dimension_cypher,
    recall_task_memory_expand_cypher,
    recall_task_memory_fulltext_cypher,
    recall_task_memory_vector_cypher,
)
from ..models import MemoryRecallResult, RecalledMemory
from ..utils import remove_lucene_chars

logger = get_logger("neocarta")

# Pre-normalization relevance floor for the vector branch: phrasings scoring
# below this cosine are dropped before max-pool and normalization, so a
# best-of-a-bad-batch match cannot be promoted to 1.0. It sits well below the
# 0.85 recall gate, so it strips noise without hiding borderline matches.
VECTOR_SCORE_FLOOR = 0.5


async def _diagnose_vector_branch(
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedding: list[float] | None,
    vector_error: str | None,
) -> str | None:
    """Explain why the vector branch produced nothing, for the agent's benefit.

    Prefers a concrete embedding-dimension mismatch (the common
    misconfiguration: ``phrase_vector_index`` built at a different size than the
    embedder produces) over the raw driver error. Returns ``None`` when the
    vector branch legitimately found no similar phrasing (no error, dimensions
    agree) so recall reports "no strong match" rather than crying wolf.
    """
    if embedding is None:
        return f"vector recall unavailable: {vector_error}"

    query_dim = len(embedding)
    try:
        records, _, _ = await neo4j_driver.execute_query(
            query_=phrase_vector_index_dimension_cypher(),
            routing_=RoutingControl.READ,
            database_=neo4j_database,
        )
        index_dim = records[0]["index_dim"] if records else None
    except Exception:
        index_dim = None

    if index_dim is not None and index_dim != query_dim:
        return (
            f"vector recall unavailable: phrase_vector_index is {index_dim}-dim but the query "
            f"embedding is {query_dim}-dim. Drop phrase_vector_index and re-run "
            f"`neocarta memory init-indexes` so the index matches the embedder, and align the "
            f"server's EMBEDDING_MODEL / EMBEDDING_DIMENSIONS with how the phrasings were "
            f"embedded, then restart."
        )
    if vector_error:
        return f"vector recall unavailable: {vector_error}"
    return None


def register(
    server: FastMCP,
    neo4j_driver: AsyncDriver,
    neo4j_database: str,
    embedder: LiteLLMEmbeddingsConnector,
) -> None:
    """Register the semantic-memory recall tool on the MCP server."""

    @server.tool()
    async def recall_task_memory(question: str, top_k: int = 5) -> MemoryRecallResult:
        """
        Recall previously answered questions from semantic memory via hybrid
        (vector + full-text) search over stored phrasings, rolled up to their
        Task.

        Call this FIRST for every data question, before schema discovery or SQL
        generation. Returns `candidates` (best-first by `hybrid_score`, a
        weighted sum of the vector and full-text scores each normalized to
        [0, 1] by its own branch max) and an optional `diagnostics` string. Each
        candidate carries `matched_phrase` (the stored phrasing that best
        matched), `phrasings` (all stored phrasings of the Task) with
        `phrase_count`, `observations`, the canonical SQL, its description, and
        the tables/columns that SQL uses.

        `observations` are the analytical notes recorded when the task was
        captured — the chosen metric definition, join path or weighting. Read
        them before reusing the SQL and honour them in any adaptation: they are
        how a previously agreed definition survives into this answer. If an
        observation contradicts what the user is now asking for, say so rather
        than silently reusing the SQL.

        `hybrid_score` orders candidates but is NOT calibrated: its magnitude is
        relative to this query's result set. Use `vector_score` (the raw cosine
        of the best-matching phrasing, in [0, 1]) as the confidence gate on the
        top candidate to decide what to DO with it:
        - >= 0.92: same question, reuse the stored SQL directly.
        - 0.85-0.92: similar, confirm with the user or use as a few-shot example.
        - < 0.85: treat as no hit; discover fresh via the semantic-layer tools.

        If `diagnostics` is non-null, the vector branch was degraded (e.g. an
        index dimension mismatch): `vector_score` is an unreliable 0, so do NOT
        apply the gate above — surface the diagnostics to the user instead.

        Parameters
        ----------
        question: str
            The user's natural-language question, verbatim.
        top_k: int
            Maximum number of candidate memories to return.
        """
        search_top_k = max(top_k * 4, 20)
        scores: dict[str, dict] = {}
        embedding: list[float] | None = None
        vector_error: str | None = None

        # Vector branch: search Phrases, roll up to their Task by max-pool. A
        # failure is logged and recorded (not swallowed) so the full-text branch
        # can carry and the diagnostics below can explain the gap.
        try:
            embedding = await embedder._create_embedding_async(question)
            if embedding is None:
                vector_error = (
                    "the embedding provider returned no vector (check the server's "
                    "OPENAI_API_KEY / EMBEDDING_MODEL)"
                )
                logger.warning("memory recall: vector branch skipped — %s", vector_error)
            else:
                records, _, _ = await neo4j_driver.execute_query(
                    query_=recall_task_memory_vector_cypher(),
                    parameters_={
                        "topK": search_top_k,
                        "embedding": embedding,
                        "vectorFloor": VECTOR_SCORE_FLOOR,
                    },
                    routing_=RoutingControl.READ,
                    database_=neo4j_database,
                )
                for r in records:
                    entry = scores.setdefault(r["eid"], {})
                    entry["vector"] = r["score"]  # max cosine over the Task's phrasings
                    entry["matched_phrase"] = r["matched_phrase"]
        except Exception as e:
            vector_error = str(e)
            logger.warning("memory recall: vector branch failed — %s", e)

        # Full-text branch: same Phrase -> Task max-pool roll-up.
        query_text = remove_lucene_chars(question)
        if query_text:
            try:
                records, _, _ = await neo4j_driver.execute_query(
                    query_=recall_task_memory_fulltext_cypher(),
                    parameters_={"topK": search_top_k, "queryText": query_text},
                    routing_=RoutingControl.READ,
                    database_=neo4j_database,
                )
                for r in records:
                    scores.setdefault(r["eid"], {})["fulltext"] = r["score"]
            except Exception as e:
                logger.warning("memory recall: full-text branch failed — %s", e)

        # Diagnose a degraded vector branch (agent-visible via the return value).
        diagnostics: str | None = None
        if not any("vector" in s for s in scores.values()):
            diagnostics = await _diagnose_vector_branch(
                neo4j_driver, neo4j_database, embedding, vector_error
            )
            if diagnostics:
                logger.warning("memory recall diagnostics: %s", diagnostics)

        if not scores:
            return MemoryRecallResult(candidates=[], diagnostics=diagnostics)

        # Fuse: weighted sum of per-branch max-normalized scores (equal weights).
        # Normalizing each branch by its own max makes the incompatible scales
        # (cosine vs. unbounded Lucene) comparable; summing rewards a Task matched
        # by both branches. Ordering stays magnitude-aware, unlike rank-fusion.
        vector_max = max((s.get("vector", 0.0) for s in scores.values()), default=0.0) or 1.0
        ft_max = max((s.get("fulltext", 0.0) for s in scores.values()), default=0.0) or 1.0

        def _hybrid(s: dict) -> float:
            return s.get("vector", 0.0) / vector_max + s.get("fulltext", 0.0) / ft_max

        ranked = sorted(scores.items(), key=lambda kv: _hybrid(kv[1]), reverse=True)[:top_k]

        candidates: list[RecalledMemory] = []
        for eid, branch_scores in ranked:
            records, _, _ = await neo4j_driver.execute_query(
                query_=recall_task_memory_expand_cypher(),
                parameters_={"eid": eid},
                routing_=RoutingControl.READ,
                database_=neo4j_database,
            )
            for r in records:
                phrasings = [p for p in r["phrasings"] if p]
                candidates.append(
                    RecalledMemory(
                        task_name=r["task_name"],
                        matched_phrase=branch_scores.get("matched_phrase"),
                        phrasings=phrasings,
                        phrase_count=len(phrasings),
                        observations=[o for o in r["observations"] if o],
                        vector_score=round(branch_scores.get("vector", 0.0), 4),
                        hybrid_score=round(_hybrid(branch_scores), 4),
                        query_description=r["query_description"],
                        sql=r["sql"],
                        tables=[t for t in r["tables"] if t],
                        columns=[c for c in r["columns"] if c],
                    )
                )
        return MemoryRecallResult(candidates=candidates, diagnostics=diagnostics)
