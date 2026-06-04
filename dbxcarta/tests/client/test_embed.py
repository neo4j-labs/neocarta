"""Tests for batch-chunked embedding and graph_rag fail-fast behaviour."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from databricks.sdk.errors import DatabricksError
from dbxcarta.client.embed import EMBED_MAX_BATCH, embed_questions
from dbxcarta.client.eval import arms
from dbxcarta.client.questions import Question
from dbxcarta.client.retriever import ColumnEntry, ContextBundle
from dbxcarta.client.summary import ClientRunSummary


class _RecordingApiClient:
    """Returns one float per input; index is per-request, shuffled on return."""

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def do(self, method: str, path: str, body: dict) -> dict:
        inputs = body["input"]
        self.batch_sizes.append(len(inputs))
        items = [
            {"index": i, "embedding": [float(hash(text) % 1000)]} for i, text in enumerate(inputs)
        ]
        # Endpoint does not guarantee response order; force callers to sort.
        items.reverse()
        return {"data": items}


class _Workspace:
    def __init__(self, api_client) -> None:
        self.api_client = api_client


def test_empty_input_returns_empty_no_call() -> None:
    api = _RecordingApiClient()
    embeddings, error = embed_questions(_Workspace(api), "ep", [])
    assert embeddings == []
    assert error is None
    assert api.batch_sizes == []


def test_chunks_respect_max_batch() -> None:
    api = _RecordingApiClient()
    texts = [f"q{i}" for i in range(EMBED_MAX_BATCH * 2 + 5)]

    embeddings, error = embed_questions(_Workspace(api), "ep", texts)

    assert error is None
    assert embeddings is not None
    assert len(embeddings) == len(texts)
    assert all(size <= EMBED_MAX_BATCH for size in api.batch_sizes)
    assert sum(api.batch_sizes) == len(texts)
    assert api.batch_sizes == [EMBED_MAX_BATCH, EMBED_MAX_BATCH, 5]


def test_order_preserved_across_chunk_boundaries() -> None:
    api = _RecordingApiClient()
    texts = [f"unique-{i}" for i in range(EMBED_MAX_BATCH + 3)]

    embeddings, error = embed_questions(_Workspace(api), "ep", texts)

    assert error is None
    assert embeddings is not None
    expected = [[float(hash(t) % 1000)] for t in texts]
    assert embeddings == expected


def test_batch_over_endpoint_limit_returns_error() -> None:
    class _RejectingApiClient:
        def do(self, *_args, **_kwargs):
            raise DatabricksError(
                "Input embeddings size is too large, exceeding 150 limit "
                "for databricks-gte-large-en"
            )

    embeddings, error = embed_questions(_Workspace(_RejectingApiClient()), "ep", ["a", "b"])

    assert embeddings is None
    assert error is not None
    assert "exceeding 150 limit" in error


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        dbxcarta_catalog="cat",
        schemas_list=["s"],
        dbxcarta_embed_endpoint="ep",
        dbxcarta_chat_endpoint="chat",
        databricks_warehouse_id="warehouse",
        dbxcarta_client_timeout_sec=30,
        dbxcarta_summary_table="cat.s.run_summary",
        dbxcarta_client_refresh=False,
    )


def _questions(n: int) -> list[Question]:
    return [Question(question_id=f"q{i}", question=f"text {i}") for i in range(n)]


def test_graph_rag_raises_when_embedding_fails(monkeypatch) -> None:
    monkeypatch.setattr(arms, "_embed_questions", lambda *_a, **_k: (None, "boom"))
    with pytest.raises(RuntimeError, match="graph_rag embedding failed"):
        arms._run_graph_rag_arm(None, None, _settings(), _questions(3), None, None, "staging")


def test_graph_rag_raises_on_embedding_count_mismatch(monkeypatch) -> None:
    monkeypatch.setattr(arms, "_embed_questions", lambda *_a, **_k: ([[0.1]], None))
    with pytest.raises(RuntimeError, match="misaligned embeddings"):
        arms._run_graph_rag_arm(None, None, _settings(), _questions(3), None, None, "staging")


def test_retrieval_concurrency_default(monkeypatch) -> None:
    monkeypatch.delenv(arms._RETRIEVAL_CONCURRENCY_ENV, raising=False)

    assert arms._retrieval_concurrency() == 8


def test_retrieval_concurrency_override(monkeypatch) -> None:
    monkeypatch.setenv(arms._RETRIEVAL_CONCURRENCY_ENV, "3")

    assert arms._retrieval_concurrency() == 3


def test_retrieval_concurrency_rejects_non_positive(monkeypatch) -> None:
    monkeypatch.setenv(arms._RETRIEVAL_CONCURRENCY_ENV, "0")

    with pytest.raises(ValueError, match="positive integer"):
        arms._retrieval_concurrency()


def test_graph_rag_preserves_question_order_after_parallel_retrieval(
    monkeypatch,
) -> None:
    from dbxcarta.client import generation, graph_retriever, trace

    recorded_prompt_ids: list[str] = []
    emitted_trace_ids: list[str] = []

    class RetrieverStub:
        def __init__(self, _settings) -> None:
            self.closed = False

        def retrieve(self, question: str, _embedding: list[float]) -> ContextBundle:
            if question.endswith("0"):
                time.sleep(0.02)
            table = question.replace("text ", "t")
            return ContextBundle(
                columns=[
                    ColumnEntry(
                        table_fqn=f"`cat`.`s`.`{table}`",
                        column_name="id",
                        data_type="BIGINT",
                        column_id=f"cat.s.{table}.id",
                    )
                ],
                selected_schemas=["s"],
            )

        def close(self) -> None:
            self.closed = True

    def fake_generate_sql_batch(
        _spark,
        _endpoint,
        questions_with_prompts,
        _staging_table,
        _arm,
        *,
        refresh=False,
    ):
        recorded_prompt_ids.extend(item["question_id"] for item in questions_with_prompts)
        return {item["question_id"]: ("SELECT 1", None) for item in questions_with_prompts}

    monkeypatch.setattr(arms, "_embed_questions", lambda *_a, **_k: ([[0.1], [0.2], [0.3]], None))
    monkeypatch.setenv(arms._RETRIEVAL_CONCURRENCY_ENV, "3")
    monkeypatch.setattr(graph_retriever, "GraphRetriever", RetrieverStub)
    monkeypatch.setattr(generation, "generate_sql_batch", fake_generate_sql_batch)
    monkeypatch.setattr(arms, "fetch_rows", lambda *_a, **_k: (["one"], [[1]], None))
    monkeypatch.setattr(
        trace,
        "emit_retrieval_traces",
        lambda _spark, traces, _table: emitted_trace_ids.extend(
            item.question_id for item in traces
        ),
    )

    summary = ClientRunSummary(
        run_id="run",
        job_name="job",
        catalog="cat",
        schemas=["s"],
        arms=["graph_rag"],
    )

    arms._run_graph_rag_arm(
        None, object(), _settings(), _questions(3), summary, None, "cat.s.stage"
    )

    assert recorded_prompt_ids == ["q0", "q1", "q2"]
    assert emitted_trace_ids == ["q0", "q1", "q2"]
    assert [result.question_id for result in summary.question_results] == [
        "q0",
        "q1",
        "q2",
    ]


def test_graph_rag_closes_retriever_when_worker_fails(monkeypatch) -> None:
    from dbxcarta.client import graph_retriever

    instances = []

    class FailingRetriever:
        def __init__(self, _settings) -> None:
            self.closed = False
            instances.append(self)

        def retrieve(self, *_args, **_kwargs) -> ContextBundle:
            raise RuntimeError("retrieve failed")

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(arms, "_embed_questions", lambda *_a, **_k: ([[0.1]], None))
    monkeypatch.setenv(arms._RETRIEVAL_CONCURRENCY_ENV, "1")
    monkeypatch.setattr(graph_retriever, "GraphRetriever", FailingRetriever)

    summary = ClientRunSummary(
        run_id="run",
        job_name="job",
        catalog="cat",
        schemas=["s"],
        arms=["graph_rag"],
    )

    with pytest.raises(RuntimeError, match="retrieve failed"):
        arms._run_graph_rag_arm(
            None, object(), _settings(), _questions(1), summary, None, "cat.s.stage"
        )

    assert instances
    assert instances[0].closed is True
