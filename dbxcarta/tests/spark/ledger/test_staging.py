from __future__ import annotations

from dbxcarta.spark.ingest.transform.staging import _is_missing_path_error


def test_is_missing_path_error_matches_databricks_execution_error_text() -> None:
    exc = RuntimeError(
        "ExecutionError: java.io.FileNotFoundException: "
        "No such file or directory /Volumes/cat/schema/vol/dbxcarta/staging"
    )

    assert _is_missing_path_error(exc)


def test_is_missing_path_error_rejects_permission_errors() -> None:
    exc = RuntimeError("Permission denied: /Volumes/cat/schema/vol/staging")

    assert not _is_missing_path_error(exc)
