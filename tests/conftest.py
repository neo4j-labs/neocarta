"""Shared fixtures usable by both the unit and integration test suites.

Fixtures here are loaded for every ``tests/`` run (rootdir is the repo root), so
keep this file to genuinely cross-cutting fixtures — colocated per-package
fixtures remain the norm elsewhere.

This module also auto-applies the suite-group marker to every collected test (see
``pytest_collection_modifyitems`` below), which is what lets ``make test-*`` select
by marker rather than by directory path (S0-3 / GUIDE D4).
"""

import os
from pathlib import Path

import pytest

from neocarta.data_model.normalized import (
    ColumnRecord,
    DatabaseRecord,
    InformationSchemaTable,
    ReferenceRecord,
    SchemaRecord,
    TableRecord,
    ValueRecord,
)

# A hyphenated project id (normalizes to ``test_project_id``); lowercase
# platform/service to exercise the record validators' upper-casing.
_DATABASE = "test-project-id"
_SCHEMA = "test_dataset"

# Suite-group markers, keyed by where a test file lives under ``tests/``. Special
# subdirectories win over the parent ``unit``/``integration`` group (checked first),
# mirroring the legacy ``--ignore`` layout so the marker-selected set is identical
# to the old path-selected set.
_SUBDIR_MARKERS = (("_mcp", "mcp"), ("_cli", "cli"), ("agent", "agent"))
_ROOT_MARKERS = {"smoke": "smoke", "integration": "integration", "unit": "unit"}


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register ``--update-goldens`` for the characterization harness (S0-SPIKE-1)."""
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Regenerate characterization golden files instead of comparing against them.",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Map ``--update-goldens`` onto the ``UPDATE_GOLDENS`` env flag the harness reads."""
    if config.getoption("--update-goldens"):
        os.environ["UPDATE_GOLDENS"] = "1"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-tag every collected test with its suite-group marker by location.

    Assigns exactly one registered group marker (``mcp``/``cli``/``agent``/``smoke``/
    ``integration``/``unit``) to each item based on where its file lives under
    ``tests/``, so ``make test-*`` can select by ``-m <marker>`` instead of by
    directory path (S0-3 / GUIDE D4). This keeps selection intent-based and stable
    across the file moves in later refactor tickets.

    Args:
        config: The pytest config, used to resolve the ``tests/`` root.
        items: The collected test items, mutated in place via ``add_marker``.
    """
    tests_root = Path(config.rootpath) / "tests"
    for item in items:
        try:
            parts = item.path.relative_to(tests_root).parts
        except ValueError:
            continue  # Defensive: item not under tests/ — leave it untagged.
        marker = next((m for seg, m in _SUBDIR_MARKERS if seg in parts), None)
        if marker is None and parts:
            marker = _ROOT_MARKERS.get(parts[0])
        if marker is not None:
            item.add_marker(marker)


@pytest.fixture
def information_schema_table() -> InformationSchemaTable:
    """A small customers/orders ``InformationSchemaTable`` shared by the graph-transform tests.

    Exercises every relational family plus the parity-critical edge cases: a
    ``is_nullable`` given raw as ``"YES"``/``"NO"``, a real foreign key, a
    self-referential foreign-key artifact (which the transformer must drop), and
    sampled column values.
    """
    return InformationSchemaTable(
        databases=[
            DatabaseRecord(
                database_name=_DATABASE, platform="gcp", service="bigquery", description=None
            ),
        ],
        schemas=[
            SchemaRecord(
                database_name=_DATABASE, schema_name=_SCHEMA, description="Test dataset description"
            ),
        ],
        tables=[
            TableRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                description="Customer table",
            ),
            TableRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="orders",
                description="Order table",
            ),
        ],
        columns=[
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_id",
                data_type="INT64",
                is_nullable="NO",
                is_primary_key=True,
                is_foreign_key=False,
                description="Customer ID",
            ),
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_name",
                data_type="STRING",
                is_nullable="YES",
                is_primary_key=False,
                is_foreign_key=False,
                description="Customer name",
            ),
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="orders",
                column_name="order_id",
                data_type="INT64",
                is_nullable="NO",
                is_primary_key=True,
                is_foreign_key=False,
                description="Order ID",
            ),
            ColumnRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="orders",
                column_name="customer_id",
                data_type="INT64",
                is_nullable="NO",
                is_primary_key=False,
                is_foreign_key=True,
                description="Customer ID reference",
            ),
        ],
        references=[
            # Real FK: orders.customer_id -> customers.customer_id.
            ReferenceRecord(
                source_database_name=_DATABASE,
                source_schema_name=_SCHEMA,
                source_table_name="orders",
                source_column_name="customer_id",
                target_database_name=_DATABASE,
                target_schema_name=_SCHEMA,
                target_table_name="customers",
                target_column_name="customer_id",
                criteria=None,
            ),
            # Self-referential FK artifact: the transformer must drop this.
            ReferenceRecord(
                source_database_name=_DATABASE,
                source_schema_name=_SCHEMA,
                source_table_name="orders",
                source_column_name="customer_id",
                target_database_name=_DATABASE,
                target_schema_name=_SCHEMA,
                target_table_name="orders",
                target_column_name="customer_id",
                criteria=None,
            ),
        ],
        values=[
            ValueRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_id",
                value="1",
            ),
            ValueRecord(
                database_name=_DATABASE,
                schema_name=_SCHEMA,
                table_name="customers",
                column_name="customer_id",
                value="2",
            ),
        ],
    )
