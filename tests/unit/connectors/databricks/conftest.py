"""Shared fixtures for the Databricks connector unit tests.

Two concerns live here:

* ``local_spark`` — a session-scoped local-mode :class:`SparkSession` for the
  Spark-logic tests that exercise real DataFrame builders. It imports ``pyspark``
  lazily inside the fixture body, so this conftest still imports cleanly in the
  default ``test-unit`` group where the ``databricks`` dependency group (and
  therefore PySpark) is not installed. Spark-logic test *modules* guard their
  own top-level ``pyspark`` imports with ``pytest.importorskip`` so they are
  skipped, not errored, when collected without PySpark.
* ``_isolate_environ`` — restores ``os.environ`` after every test so a
  ``BaseSettings`` constructor reading ``NEOCARTA_DATABRICKS_*`` never sees a
  value another test (or the developer's shell) left behind.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session")
def _pristine_environ() -> dict[str, str]:
    """Snapshot of ``os.environ`` taken before any test mutates it."""
    return dict(os.environ)


@pytest.fixture(autouse=True)
def _isolate_environ(_pristine_environ: dict[str, str]) -> Iterator[None]:
    """Restore ``os.environ`` to the pristine baseline after every test."""
    yield
    if os.environ != _pristine_environ:
        os.environ.clear()
        os.environ.update(_pristine_environ)


@pytest.fixture(scope="session")
def local_spark() -> Iterator:
    """Local-mode SparkSession for unit tests of pure DataFrame builders."""
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.master("local[1]")
        .appName("neocarta-databricks-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .getOrCreate()
    )
    yield spark
    spark.stop()
