"""Root conftest: shared local_spark fixture for unit tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture(scope="session")
def _pristine_environ() -> dict[str, str]:
    """Snapshot of ``os.environ`` taken before any test mutates it.

    Instantiated lazily at the first test's setup. No collected test module
    writes ``os.environ`` at import time, so this captures the pre-pollution
    baseline.
    """
    return dict(os.environ)


@pytest.fixture(autouse=True)
def _isolate_environ(_pristine_environ: dict[str, str]) -> Iterator[None]:
    """Restore ``os.environ`` to the pristine baseline after every test.

    The production ``inject_params`` helper writes to ``os.environ`` via
    ``setdefault`` by design. Without this, those writes leak across tests
    and poison ``BaseSettings`` constructors that read unset fields from the
    environment.
    """
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
        .appName("dbxcarta-tests")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.shuffle.partitions", "1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.driver.host", "127.0.0.1")
        .getOrCreate()
    )
    yield spark
    spark.stop()
