"""Pure-Python tests for the transient/ledger path error detection.

``_is_missing_path_error`` decides whether a failed ``dbutils.fs.ls`` probe
means "the path is simply absent" (fine — the batch had nothing to embed, or
the ledger does not exist yet) versus a real failure that must propagate. It
inspects only the exception text, so it needs neither Spark nor dbutils and
runs in the default ``test-unit`` group.
"""

from __future__ import annotations

from neocarta.connectors.databricks.ingest.transform.staging import _is_missing_path_error


def test_is_missing_path_error_matches_databricks_execution_error_text():
    """A FileNotFoundException-bearing execution error counts as a missing path."""
    exc = RuntimeError(
        "ExecutionError: java.io.FileNotFoundException: "
        "No such file or directory /Volumes/cat/schema/vol/staging"
    )

    assert _is_missing_path_error(exc)


def test_is_missing_path_error_rejects_permission_errors():
    """A permission error is real signal, not an absent path, so it propagates."""
    exc = RuntimeError("Permission denied: /Volumes/cat/schema/vol/staging")

    assert not _is_missing_path_error(exc)
