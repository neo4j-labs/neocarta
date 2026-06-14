"""Pure-Python tests for run-summary reporting, persistence, and path resolution.

These cover the embedding bookkeeping that is plain arithmetic and dict
flattening (`finalize_embedding_summary`, `EmbeddingCounts`, `RunSummary`
embedding keys), the `_persist_summary` UC Volume write, and the staging/ledger
path helpers, none of which touch Spark or Neo4j. They run in the default
``test-unit`` group exactly like the settings tests; the Spark-logic embedding
tests live in ``test_embeddings.py``.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from neocarta.connectors.databricks.contract import NodeLabel
from neocarta.connectors.databricks.ingest.summary import EmbeddingCounts, RunSummary
from neocarta.connectors.databricks.ingest.transform.embed_stage import (
    finalize_embedding_summary,
)
from neocarta.connectors.databricks.ingest.transform.staging import (
    resolve_ledger_path,
    resolve_transient_root,
)
from neocarta.connectors.databricks.settings import SparkIngestSettings


def _summary() -> RunSummary:
    """Build a minimal RunSummary shell for embedding-reporting assertions."""
    return RunSummary(
        run_id="r1",
        job_name="databricks",
        contract_version="1.1",
        catalog="c",
        schemas=["s"],
    )


def test_finalize_computes_per_label_and_aggregate_rates():
    """Per-label rate is (attempts - successes) / attempts; aggregate pools all."""
    summary = _summary()
    summary.embeddings = EmbeddingCounts(
        attempts={NodeLabel.TABLE: 10, NodeLabel.COLUMN: 5},
        successes={NodeLabel.TABLE: 8, NodeLabel.COLUMN: 5},
    )

    finalize_embedding_summary(summary)

    rates = summary.embeddings.failure_rate_per_label
    assert rates[NodeLabel.TABLE] == 0.2
    assert rates[NodeLabel.COLUMN] == 0.0
    # Pooled: (15 - 13) / 15.
    assert summary.embeddings.aggregate_failure_rate == 2 / 15


def test_finalize_handles_zero_attempts():
    """A label with zero attempts yields a 0.0 rate, never a ZeroDivisionError."""
    summary = _summary()
    summary.embeddings = EmbeddingCounts(
        attempts={NodeLabel.TABLE: 0},
        successes={NodeLabel.TABLE: 0},
    )

    finalize_embedding_summary(summary)

    assert summary.embeddings.failure_rate_per_label[NodeLabel.TABLE] == 0.0
    assert summary.embeddings.aggregate_failure_rate == 0.0


def test_embedding_counts_maps_key_by_public_label_string():
    """The as_*_map helpers re-key NodeLabel dicts by the public label string."""
    counts = EmbeddingCounts(
        flags={NodeLabel.TABLE: True, NodeLabel.COLUMN: False},
        attempts={NodeLabel.TABLE: 4},
        successes={NodeLabel.TABLE: 3},
        failure_rate_per_label={NodeLabel.TABLE: 0.25},
        ledger_hits={NodeLabel.TABLE: 1},
    )

    assert counts.as_flags_map() == {"Table": True, "Column": False}
    assert counts.as_attempts_map() == {"Table": 4}
    assert counts.as_successes_map() == {"Table": 3}
    assert counts.as_failure_rate_map() == {"Table": 0.25}
    assert counts.as_ledger_hits_map() == {"Table": 1}


def test_to_dict_external_mode_emits_null_embedding_view():
    """The default (external-mode) EmbeddingCounts serializes to an all-null view."""
    out = _summary().to_dict()

    assert out["embedding_model"] is None
    assert out["embedding_failure_rate"] is None
    assert out["embedding_failure_max"] is None
    assert out["embedding_flags"] == {}
    assert out["embedding_attempts"] == {}
    assert out["embedding_successes"] == {}
    assert out["embedding_failure_rate_per_label"] == {}
    assert out["embedding_ledger_hits"] == {}


def test_to_dict_inline_mode_emits_embedding_counts():
    """Populated embedding counters flatten into the serializable summary keys."""
    summary = _summary()
    summary.embeddings = EmbeddingCounts(
        model="databricks-gte-large-en",
        failure_max=5,
        flags={NodeLabel.TABLE: True},
        attempts={NodeLabel.TABLE: 10},
        successes={NodeLabel.TABLE: 9},
        aggregate_failure_rate=0.1,
    )

    out = summary.to_dict()

    assert out["embedding_model"] == "databricks-gte-large-en"
    assert out["embedding_failure_max"] == 5
    assert out["embedding_flags"] == {"Table": True}
    assert out["embedding_attempts"] == {"Table": 10}
    assert out["embedding_successes"] == {"Table": 9}
    assert out["embedding_failure_rate"] == 0.1


def _inline_settings(**overrides) -> SparkIngestSettings:
    """Inline-mode settings with a valid staging volume, plus any overrides."""
    kwargs = {
        "catalog": "c",
        "include_embeddings_tables": True,
        "embedding_staging_volume": "/Volumes/c/s/v/staging",
    }
    kwargs.update(overrides)
    return SparkIngestSettings(**kwargs)


def test_resolve_transient_root_is_the_staging_volume():
    """The transient root is the configured staging volume, trailing slash trimmed."""
    settings = _inline_settings(embedding_staging_volume="/Volumes/c/s/v/staging/")
    assert resolve_transient_root(settings) == "/Volumes/c/s/v/staging"


def test_resolve_ledger_path_defaults_to_sibling_of_staging_volume():
    """With no explicit ledger_path, the ledger is a sibling of the staging dir."""
    settings = _inline_settings()
    assert resolve_ledger_path(settings) == "/Volumes/c/s/v/ledger"


def test_resolve_ledger_path_uses_explicit_ledger_path_when_set():
    """An explicit ledger_path wins over the sibling default, slash trimmed."""
    settings = _inline_settings(ledger_path="/Volumes/c/s/v/my_ledger/")
    assert resolve_ledger_path(settings) == "/Volumes/c/s/v/my_ledger"


def test_persist_summary_writes_json_named_by_run_id_when_volume_set(tmp_path):
    """A set summary_volume gets summary_<run_id>.json with the flattened summary.

    A SimpleNamespace stub stands in for settings so the test can target a real
    temp dir (the /Volumes validator would reject one on the real settings).
    """
    from neocarta.connectors.databricks.run import _persist_summary

    summary = _summary()
    summary.finish(status="success")

    _persist_summary(SimpleNamespace(summary_volume=f"{tmp_path}/"), summary)

    out = tmp_path / "summary_r1.json"
    assert out.exists()
    payload = json.loads(out.read_text())
    assert payload["run_id"] == "r1"
    assert payload["status"] == "success"


def test_persist_summary_is_noop_when_volume_blank(tmp_path):
    """A blank summary_volume writes nothing (persistence disabled by default)."""
    from neocarta.connectors.databricks.run import _persist_summary

    _persist_summary(SimpleNamespace(summary_volume=""), _summary())

    assert list(tmp_path.iterdir()) == []


def test_persist_summary_swallows_write_error(tmp_path):
    """A write failure is logged, never raised, so it cannot mask the run outcome."""
    from neocarta.connectors.databricks.run import _persist_summary

    # Parent directory is absent, so the write raises OSError internally.
    missing = tmp_path / "absent_dir"
    _persist_summary(SimpleNamespace(summary_volume=str(missing)), _summary())

    assert not missing.exists()
