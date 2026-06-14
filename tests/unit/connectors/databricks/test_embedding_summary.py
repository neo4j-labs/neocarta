"""Pure-Python tests for inline-embedding reporting and path resolution.

These cover the embedding bookkeeping that is plain arithmetic and dict
flattening (`finalize_embedding_summary`, `EmbeddingCounts`, `RunSummary`
embedding keys) plus the staging/ledger path helpers, none of which touch Spark
or Neo4j. They run in the default ``test-unit`` group exactly like the settings
tests; the Spark-logic embedding tests live in ``test_embeddings.py``.
"""

from __future__ import annotations

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
