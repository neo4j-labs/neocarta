"""Ledger I/O boundary tests.

`read_ledger` lives at `dbxcarta.spark.ingest.transform.ledger` and catches only
`AnalysisException`. A non-existent Delta path returns None without raising;
other failures are expected to propagate as signal.
"""

from __future__ import annotations

import pytest
from dbxcarta.spark.contract import NodeLabel
from dbxcarta.spark.ingest.transform.ledger import read_ledger


@pytest.mark.skip(reason="requires Delta JAR on local Spark classpath")
def test_read_ledger_returns_none_on_missing_path(local_spark, tmp_path) -> None:
    """A path that doesn't exist returns None. If any exception other than the
    narrowed AnalysisException fires, it propagates — test would fail loudly."""
    missing = str(tmp_path / "ledger_never_created")
    result = read_ledger(local_spark, missing, NodeLabel.TABLE)
    assert result is None
