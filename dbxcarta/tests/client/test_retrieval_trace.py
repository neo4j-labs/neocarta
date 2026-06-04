"""Unit tests for RetrievalTrace diagnostics (Phase E)."""

from __future__ import annotations

from dbxcarta.client.ids import catalog_from_node_id, schema_from_node_id
from dbxcarta.client.retriever import ColumnEntry
from dbxcarta.client.trace import (
    RetrievalTrace,
    chosen_schemas_from_columns,
    compute_retrieval_metrics,
    emit_retrieval_traces,
    schema_scores_from_seeds,
)

# ---------------------------------------------------------------------------
# schema_from_node_id
# ---------------------------------------------------------------------------


def test_schema_from_column_id() -> None:
    assert schema_from_node_id("cat.myschema.tbl.col") == "myschema"


def test_schema_from_table_id() -> None:
    assert schema_from_node_id("cat.myschema.tbl") == "myschema"


def test_schema_from_short_id_returns_none() -> None:
    assert schema_from_node_id("cat.tbl") is None
    assert schema_from_node_id("only") is None


# ---------------------------------------------------------------------------
# catalog_from_node_id
# ---------------------------------------------------------------------------


def test_catalog_from_column_id() -> None:
    assert catalog_from_node_id("cat.myschema.tbl.col") == "cat"


def test_catalog_from_table_id() -> None:
    assert catalog_from_node_id("cat.myschema.tbl") == "cat"


def test_catalog_from_short_id_returns_none() -> None:
    assert catalog_from_node_id("cat.tbl") is None
    assert catalog_from_node_id("only") is None


# ---------------------------------------------------------------------------
# schema_scores_from_seeds
# ---------------------------------------------------------------------------


def test_schema_scores_single_schema() -> None:
    scores = schema_scores_from_seeds(
        col_seed_ids=["cat.alpha.tbl.col1", "cat.alpha.tbl.col2"],
        col_seed_scores=[0.9, 0.8],
        tbl_seed_ids=["cat.alpha.tbl"],
        tbl_seed_scores=[0.7],
    )
    assert scores == {"alpha": 1.0}


def test_schema_scores_two_schemas_normalized() -> None:
    scores = schema_scores_from_seeds(
        col_seed_ids=["cat.alpha.t.c", "cat.beta.t.c"],
        col_seed_scores=[0.6, 0.4],
        tbl_seed_ids=[],
        tbl_seed_scores=[],
    )
    assert abs(scores["alpha"] - 0.6) < 1e-9
    assert abs(scores["beta"] - 0.4) < 1e-9
    assert abs(sum(scores.values()) - 1.0) < 1e-9


def test_schema_scores_three_schemas() -> None:
    scores = schema_scores_from_seeds(
        col_seed_ids=["cat.alpha.t.c", "cat.beta.t.c"],
        col_seed_scores=[1.0, 1.0],
        tbl_seed_ids=["cat.gamma.t"],
        tbl_seed_scores=[2.0],
    )
    assert abs(scores["alpha"] - 0.25) < 1e-9
    assert abs(scores["beta"] - 0.25) < 1e-9
    assert abs(scores["gamma"] - 0.5) < 1e-9


def test_schema_scores_normalizes_column_and_table_indexes_first() -> None:
    scores = schema_scores_from_seeds(
        col_seed_ids=["cat.alpha.t.c"],
        col_seed_scores=[10.0],
        tbl_seed_ids=["cat.beta.t"],
        tbl_seed_scores=[1.0],
    )
    assert scores == {"alpha": 0.5, "beta": 0.5}


def test_schema_scores_empty_seeds() -> None:
    scores = schema_scores_from_seeds([], [], [], [])
    assert scores == {}


def test_schema_scores_skips_unparseable_ids() -> None:
    scores = schema_scores_from_seeds(
        col_seed_ids=["bad_id", "cat.alpha.t.c"],
        col_seed_scores=[1.0, 1.0],
        tbl_seed_ids=[],
        tbl_seed_scores=[],
    )
    assert "alpha" in scores
    assert all("bad" not in k for k in scores)


# ---------------------------------------------------------------------------
# chosen_schemas_from_columns
# ---------------------------------------------------------------------------


def _col(fqn: str) -> ColumnEntry:
    return ColumnEntry(table_fqn=fqn, column_name="x", data_type="STRING")


def test_chosen_schemas_deduplicates() -> None:
    cols = [_col("cat.alpha.t1"), _col("cat.alpha.t2"), _col("cat.beta.t1")]
    assert chosen_schemas_from_columns(cols) == ["alpha", "beta"]


def test_chosen_schemas_preserves_order() -> None:
    cols = [_col("cat.beta.t"), _col("cat.alpha.t")]
    assert chosen_schemas_from_columns(cols) == ["beta", "alpha"]


def test_chosen_schemas_empty() -> None:
    assert chosen_schemas_from_columns([]) == []


# ---------------------------------------------------------------------------
# compute_retrieval_metrics
# ---------------------------------------------------------------------------


def _trace(target_schema: str | None, **kwargs) -> RetrievalTrace:
    defaults = {
        "run_id": "r1",
        "question_id": "q1",
        "question": "test?",
        "col_seed_ids": [],
        "col_seed_scores": [],
        "tbl_seed_ids": [],
        "tbl_seed_scores": [],
        "schema_scores": {},
        "chosen_schemas": [],
        "expansion_tbl_ids": [],
        "final_col_ids": [],
        "rendered_context": "",
    }
    defaults.update(kwargs)
    return RetrievalTrace(target_schema=target_schema, **defaults)


def test_metrics_no_target_schema_leaves_none() -> None:
    t = _trace(
        target_schema=None,
        schema_scores={"alpha": 1.0},
        chosen_schemas=["alpha"],
        final_col_ids=["cat.alpha.t.c"],
    )
    compute_retrieval_metrics(t)
    assert t.top1_schema_match is None
    assert t.schema_in_context is None
    assert t.context_purity is None


def test_top1_schema_match_correct() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"alpha": 0.7, "beta": 0.3},
        chosen_schemas=["alpha"],
        final_col_ids=["cat.alpha.t.c"],
    )
    compute_retrieval_metrics(t)
    assert t.top1_schema_match is True


def test_top1_schema_match_wrong() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"beta": 0.8, "alpha": 0.2},
        chosen_schemas=["beta", "alpha"],
        final_col_ids=["cat.beta.t.c", "cat.alpha.t.c"],
    )
    compute_retrieval_metrics(t)
    assert t.top1_schema_match is False


def test_schema_in_context_true() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"beta": 0.6, "alpha": 0.4},
        chosen_schemas=["beta", "alpha"],
        final_col_ids=["cat.beta.t.c", "cat.alpha.t.c"],
    )
    compute_retrieval_metrics(t)
    assert t.schema_in_context is True


def test_schema_in_context_false() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"beta": 1.0},
        chosen_schemas=["beta"],
        final_col_ids=["cat.beta.t.c"],
    )
    compute_retrieval_metrics(t)
    assert t.schema_in_context is False


def test_context_purity_full() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"alpha": 1.0},
        chosen_schemas=["alpha"],
        final_col_ids=["cat.alpha.t.c1", "cat.alpha.t.c2"],
    )
    compute_retrieval_metrics(t)
    assert t.context_purity == 1.0


def test_context_purity_partial() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"alpha": 0.5, "beta": 0.5},
        chosen_schemas=["alpha", "beta"],
        final_col_ids=["cat.alpha.t.c", "cat.beta.t.c", "cat.beta.t.d"],
    )
    compute_retrieval_metrics(t)
    assert abs(t.context_purity - 1 / 3) < 1e-9


def test_context_purity_none_when_empty_cols() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={"alpha": 1.0},
        chosen_schemas=[],
        final_col_ids=[],
    )
    compute_retrieval_metrics(t)
    assert t.context_purity is None


def test_top1_none_when_no_schema_scores() -> None:
    t = _trace(
        target_schema="alpha",
        schema_scores={},
        chosen_schemas=[],
        final_col_ids=[],
    )
    compute_retrieval_metrics(t)
    assert t.top1_schema_match is None


def test_emit_retrieval_traces_noops_for_empty_trace_list() -> None:
    class SparkStub:
        def createDataFrame(self, *_args, **_kwargs):  # pragma: no cover
            raise AssertionError("createDataFrame should not be called")

    emit_retrieval_traces(SparkStub(), [], "cat.schema.client_retrieval")
