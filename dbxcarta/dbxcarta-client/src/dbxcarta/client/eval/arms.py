"""Per-arm evaluation runners for the Text2SQL harness.

Each ``_run_*_arm`` function evaluates one arm against the question set and
records results on the shared ``ClientRunSummary``. ``run.py`` owns the
orchestration (settings, preflight, summary emission); this module owns the
arm-specific generation/execution/grading logic.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, NamedTuple

from dbxcarta.client.compare import compare_result_sets as _compare_result_sets
from dbxcarta.client.embed import embed_questions as _embed_questions
from dbxcarta.client.sql import parse_sql as _parse_sql
from dbxcarta.core.executor import fetch_rows

if TYPE_CHECKING:
    from databricks.sdk import WorkspaceClient
    from dbxcarta.client.questions import Question
    from dbxcarta.client.settings import ClientSettings
    from dbxcarta.client.summary import ClientRunSummary

_REFERENCE_ARM = "reference"
_LLM_ARMS = {"no_context", "schema_dump"}
_STAGING_ARMS = _LLM_ARMS | {"graph_rag"}

# graph_rag retrieval is I/O-bound (~10-11 sequential Cypher round trips per
# question) and per-question independent, so it parallelizes cleanly. Default
# hardcoded for the 10K multi-catalog demo; at that scale each retrieve() is
# heavier, so 8 is the safer default unless the Neo4j tier is confirmed large.
_RETRIEVAL_CONCURRENCY = 8
_RETRIEVAL_CONCURRENCY_ENV = "DBXCARTA_CLIENT_RETRIEVAL_CONCURRENCY"


def _retrieval_concurrency() -> int:
    raw = os.environ.get(_RETRIEVAL_CONCURRENCY_ENV)
    if raw is None or not raw.strip():
        return _RETRIEVAL_CONCURRENCY
    value = int(raw)
    if value < 1:
        raise ValueError(f"{_RETRIEVAL_CONCURRENCY_ENV} must be a positive integer, got {value!r}")
    return value


def _client_retrieval_table(settings: ClientSettings) -> str:
    parts = settings.dbxcarta_summary_table.split(".")
    return f"{parts[0]}.{parts[1]}.client_retrieval"


class _ReferenceCache:
    """Memoize one ``fetch_rows`` per question's reference SQL across arms.

    The demo question set is fixed, so a question's reference result is stable
    for the whole run. Keyed by ``question_id``; the cached tuple is
    ``(cols, rows, error)`` from a single warehouse execution, reused by the
    reference arm and every grading arm instead of re-running the reference
    SQL once per arm.
    """

    def __init__(self, ws: WorkspaceClient, warehouse_id: str, timeout_sec: int) -> None:
        self._ws = ws
        self._warehouse_id = warehouse_id
        self._timeout_sec = timeout_sec
        self._cache: dict[str, tuple[list[str] | None, list[list[Any]] | None, str | None]] = {}

    def get(
        self, question_id: str, reference_sql: str
    ) -> tuple[list[str] | None, list[list[Any]] | None, str | None]:
        if question_id not in self._cache:
            self._cache[question_id] = fetch_rows(
                self._ws, self._warehouse_id, reference_sql, self._timeout_sec
            )
        return self._cache[question_id]


def _grade_correct(
    gen_cols: list[str] | None,
    gen_rows: list[list[Any]],
    reference_sql: str,
    question_id: str,
    ref_cache: _ReferenceCache,
) -> tuple[bool, str | None]:
    """Compare already-fetched generated rows against the cached reference set.

    The caller already executed the generated SQL once and passes its rows in
    rather than re-running it. The reference set comes from ``ref_cache`` so
    the reference SQL runs at most once per question for the whole run.

    Returns (correct, error). correct is False when the reference statement
    failed or the result sets do not match.
    """
    ref_cols, ref_rows, ref_err = ref_cache.get(question_id, reference_sql)
    if ref_rows is None:
        return False, f"reference SQL failed: {ref_err}"

    return _compare_result_sets(gen_cols or [], gen_rows, ref_cols or [], ref_rows)


class _ExecGrade(NamedTuple):
    executed: bool
    non_empty: bool
    gradable: bool
    correct: bool
    error: str | None


def _execute_and_grade(
    ws: WorkspaceClient,
    settings: ClientSettings,
    generated_sql: str,
    reference_sql: str | None,
    question_id: str,
    ref_cache: _ReferenceCache,
) -> _ExecGrade:
    """Run the generated SQL once, then grade it against the cached reference.

    ``executed``/``non_empty``/``error`` come from the single ``fetch_rows``
    call; ``gradable`` requires a reference SQL and a successful execution;
    ``correct`` is the result-set comparison (False unless gradable). Shared
    by the LLM and graph_rag arms so the grading contract cannot drift.
    """
    gen_cols, gen_rows, error = fetch_rows(
        ws,
        settings.databricks_warehouse_id,
        generated_sql,
        settings.dbxcarta_client_timeout_sec,
    )
    executed = gen_rows is not None
    non_empty = bool(gen_rows)
    gradable = bool(reference_sql) and executed
    correct = False
    if gradable:
        if reference_sql is None or gen_rows is None:
            raise RuntimeError("gradable SQL missing reference or generated rows")
        correct, _ = _grade_correct(gen_cols, gen_rows, reference_sql, question_id, ref_cache)
    return _ExecGrade(executed, non_empty, gradable, correct, error)


def _run_reference_arm(
    questions: list[Question],
    summary: ClientRunSummary,
    ref_cache: _ReferenceCache,
) -> None:
    for q in questions:
        if not q.reference_sql:
            continue
        _cols, rows, error = ref_cache.get(q.question_id, q.reference_sql)
        summary.add_result(
            question_id=q.question_id,
            question=q.question,
            arm=_REFERENCE_ARM,
            sql=q.reference_sql,
            parsed=True,
            executed=rows is not None,
            non_empty=bool(rows),
            error=error,
        )


def _run_llm_arm(
    spark: Any,
    ws: WorkspaceClient,
    settings: ClientSettings,
    questions: list[Question],
    summary: ClientRunSummary,
    ref_cache: _ReferenceCache,
    arm: str,
    staging_table: str,
    schema_text: str | None = None,
) -> None:
    from dbxcarta.client.generation import generate_sql_batch
    from dbxcarta.client.prompt import no_context_prompt, schema_dump_prompt

    catalog = settings.dbxcarta_catalog
    schemas = settings.schemas_list

    questions_with_prompts = []
    for q in questions:
        if arm == "no_context":
            prompt = no_context_prompt(q.question, catalog, schemas)
        elif arm == "schema_dump":
            if schema_text is None:
                raise RuntimeError("schema_text required for schema_dump arm")
            prompt = schema_dump_prompt(q.question, catalog, schemas, schema_text)
        else:
            raise ValueError(f"Unknown LLM arm: {arm!r}")
        questions_with_prompts.append({"question_id": q.question_id, "prompt": prompt})

    responses = generate_sql_batch(
        spark,
        settings.dbxcarta_chat_endpoint,
        questions_with_prompts,
        staging_table,
        arm,
        refresh=settings.dbxcarta_client_refresh,
    )

    for q in questions:
        qid = q.question_id
        raw_sql, ai_error = responses.get(qid, (None, "no response"))

        cleaned_sql, parse_ok = _parse_sql(raw_sql)

        if not parse_ok:
            summary.add_result(
                question_id=qid,
                question=q.question,
                arm=arm,
                sql=raw_sql,
                parsed=False,
                executed=False,
                non_empty=False,
                error=ai_error or "response did not contain valid SQL",
            )
            continue

        if cleaned_sql is None:
            raise RuntimeError("parser reported success but produced no SQL")
        graded = _execute_and_grade(ws, settings, cleaned_sql, q.reference_sql, qid, ref_cache)
        summary.add_result(
            question_id=qid,
            question=q.question,
            arm=arm,
            sql=cleaned_sql,
            parsed=True,
            executed=graded.executed,
            non_empty=graded.non_empty,
            correct=graded.correct,
            gradable=graded.gradable,
            error=graded.error,
        )


def _run_graph_rag_arm(
    spark: Any,
    ws: WorkspaceClient,
    settings: ClientSettings,
    questions: list[Question],
    summary: ClientRunSummary,
    ref_cache: _ReferenceCache,
    staging_table: str,
) -> None:
    from dbxcarta.client.generation import generate_sql_batch
    from dbxcarta.client.graph_rag import build_graph_rag_context
    from dbxcarta.client.graph_retriever import GraphRetriever
    from dbxcarta.client.trace import (
        RetrievalTrace,
        chosen_schemas_from_columns,
        compute_retrieval_metrics,
        emit_retrieval_traces,
        schema_scores_from_seeds,
    )

    texts = [q.question for q in questions]
    embeddings, embed_error = _embed_questions(ws, settings.dbxcarta_embed_endpoint, texts)
    if embeddings is None:
        raise RuntimeError(
            f"graph_rag embedding failed against "
            f"{settings.dbxcarta_embed_endpoint!r}: {embed_error}"
        )
    if len(embeddings) != len(questions):
        raise RuntimeError(
            f"graph_rag embedding returned {len(embeddings)} vectors for "
            f"{len(questions)} questions; refusing to run with misaligned embeddings"
        )

    retriever = GraphRetriever(settings)
    try:
        # Retrieval is I/O-bound and per-question independent; the Neo4j
        # driver is thread-safe and retrieve() opens its own session per
        # call. Each worker runs the shared retrieval-and-prompt seam with
        # the pre-computed embedding and the shared retriever (the seam does
        # not close a caller-owned retriever). Collect by question_id, then
        # build traces by iterating `questions` in original order so the
        # output is identical to the serial path. A worker exception
        # propagates and aborts the run (retriever closed in the finally
        # below).
        contexts: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=_retrieval_concurrency()) as executor:
            future_to_qid = {
                executor.submit(
                    build_graph_rag_context,
                    ws,
                    settings,
                    q.question,
                    embedding=emb,
                    retriever=retriever,
                ): q.question_id
                for q, emb in zip(questions, embeddings, strict=False)
            }
            for future, qid in future_to_qid.items():
                contexts[qid] = future.result()

        questions_with_prompts = []
        traces: dict[str, RetrievalTrace] = {}
        for q in questions:
            qid = q.question_id
            context = contexts[qid]
            bundle = context.bundle
            context_text = context.context_text
            questions_with_prompts.append({"question_id": qid, "prompt": context.prompt})

            final_col_ids = [c.column_id for c in bundle.columns if c.column_id]
            sch_scores = schema_scores_from_seeds(
                bundle.col_seed_ids,
                bundle.col_seed_scores,
                bundle.tbl_seed_ids,
                bundle.tbl_seed_scores,
            )
            trace = RetrievalTrace(
                run_id=summary.run_id,
                question_id=qid,
                question=q.question,
                target_schema=q.schema_,
                col_seed_ids=bundle.col_seed_ids,
                col_seed_scores=bundle.col_seed_scores,
                tbl_seed_ids=bundle.tbl_seed_ids,
                tbl_seed_scores=bundle.tbl_seed_scores,
                schema_scores=sch_scores,
                chosen_schemas=(
                    bundle.selected_schemas or chosen_schemas_from_columns(bundle.columns)
                ),
                expansion_tbl_ids=bundle.expansion_tbl_ids,
                final_col_ids=final_col_ids,
                rendered_context=context_text,
                reference_sql=q.reference_sql,
            )
            compute_retrieval_metrics(trace)
            traces[qid] = trace
    finally:
        retriever.close()

    responses = generate_sql_batch(
        spark,
        settings.dbxcarta_chat_endpoint,
        questions_with_prompts,
        staging_table,
        "graph_rag",
        refresh=settings.dbxcarta_client_refresh,
    )

    for q in questions:
        qid = q.question_id
        raw_sql, ai_error = responses.get(qid, (None, "no response"))
        cleaned_sql, parse_ok = _parse_sql(raw_sql)
        trace = traces[qid]

        if not parse_ok:
            trace.generated_sql = raw_sql
            trace.execution_error = ai_error or "response did not contain valid SQL"
            summary.add_result(
                question_id=qid,
                question=q.question,
                arm="graph_rag",
                sql=raw_sql,
                context_ids=trace.col_seed_ids + trace.tbl_seed_ids,
                parsed=False,
                executed=False,
                non_empty=False,
                error=ai_error or "response did not contain valid SQL",
                top1_schema_match=trace.top1_schema_match,
                schema_in_context=trace.schema_in_context,
                context_purity=trace.context_purity,
            )
            continue

        if cleaned_sql is None:
            raise RuntimeError("parser reported success but produced no SQL")
        graded = _execute_and_grade(ws, settings, cleaned_sql, q.reference_sql, qid, ref_cache)

        trace.generated_sql = cleaned_sql
        trace.parsed = True
        trace.executed = graded.executed
        trace.correct = graded.correct
        trace.execution_error = graded.error

        summary.add_result(
            question_id=qid,
            question=q.question,
            arm="graph_rag",
            sql=cleaned_sql,
            context_ids=trace.col_seed_ids + trace.tbl_seed_ids,
            parsed=True,
            executed=graded.executed,
            non_empty=graded.non_empty,
            correct=graded.correct,
            gradable=graded.gradable,
            error=graded.error,
            top1_schema_match=trace.top1_schema_match,
            schema_in_context=trace.schema_in_context,
            context_purity=trace.context_purity,
        )

    emit_retrieval_traces(spark, list(traces.values()), _client_retrieval_table(settings))
