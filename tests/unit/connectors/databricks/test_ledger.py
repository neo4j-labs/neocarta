"""Ledger I/O boundary tests.

``read_ledger`` catches only ``AnalysisException`` (what Spark raises for an
absent Delta path) and returns None; any other failure propagates as signal.
The missing-path case needs the Delta format on the local Spark classpath, so
it stays skipped exactly as it was in the dbxcarta source — the local-Spark
suite has no Delta JAR. The ledger join/split logic is covered without Delta in
``test_embeddings.py``.

These run under the ``databricks`` dependency group; the top-level ``pyspark``
import is guarded with ``importorskip`` so collection in the default
``test-unit`` group skips this module rather than erroring.
"""

from __future__ import annotations

import pytest

pytest.importorskip("pyspark")

from neocarta.connectors.databricks.contract import NodeLabel
from neocarta.connectors.databricks.ingest.transform.ledger import read_ledger


@pytest.mark.skip(reason="requires Delta JAR on local Spark classpath")
def test_read_ledger_returns_none_on_missing_path(local_spark, tmp_path) -> None:
    """A path that doesn't exist returns None.

    If any exception other than the narrowed AnalysisException fires, it
    propagates — the test would fail loudly rather than masking the failure.
    """
    missing = str(tmp_path / "ledger_never_created")
    result = read_ledger(local_spark, missing, NodeLabel.TABLE)
    assert result is None
