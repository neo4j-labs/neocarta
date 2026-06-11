"""Unit tests for the central logging helpers in ``neocarta._logging``."""

import logging

import pandas as pd
import pytest

from neocarta._logging import (
    PACKAGE_LOGGER_NAME,
    _row_count,
    _safe_target,
    configure_logging,
    humanize,
    log_stage,
    log_timing,
    log_transform_counts,
)


@pytest.fixture
def restore_neocarta_logger():
    """Snapshot and restore the ``neocarta`` logger so configure_logging tests are isolated."""
    logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    original_handlers = logger.handlers[:]
    original_level = logger.level
    original_propagate = logger.propagate
    yield logger
    for handler in logger.handlers[:]:
        if handler not in original_handlers:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(original_level)
    logger.propagate = original_propagate


def test_humanize_capitalizes_and_despaces():
    assert humanize("extract_table_info") == "Extract table info"


def test_row_count_dataframe():
    assert _row_count(pd.DataFrame([{"a": 1}, {"a": 2}])) == 2


def test_row_count_dict_of_dataframes_sums():
    payload = {"x": pd.DataFrame([{"a": 1}, {"a": 2}]), "y": pd.DataFrame([{"a": 3}])}
    assert _row_count(payload) == 3


def test_row_count_list():
    assert _row_count([1, 2, 3]) == 3


def test_row_count_none_and_plain_dict_return_none():
    assert _row_count(None) is None
    # A parsed OSI spec dict carries no row-shaped values.
    assert _row_count({"version": "0.1.1", "name": "x"}) is None


def test_log_transform_counts_logs_nonzero_and_skips_empty(caplog):
    class _Transformer:
        def __init__(self):
            self.table_nodes = [1, 2, 3]
            self.column_nodes = [1, 2]
            self.value_nodes = []  # empty -> skipped

    fields = (("tables", "table_nodes"), ("columns", "column_nodes"), ("values", "value_nodes"))
    logger = logging.getLogger(__name__)
    with caplog.at_level(logging.INFO, logger=__name__):
        log_transform_counts(logger, _Transformer(), fields)

    messages = [r.getMessage() for r in caplog.records]
    assert "Transformed 3 tables" in messages
    assert "Transformed 2 columns" in messages
    # Zero-count types stay quiet.
    assert all("values" not in m for m in messages)


def test_safe_target_includes_allowlisted_excludes_data_bearing_keys():
    target = _safe_target(
        {"dataset_id": "sales", "query": "SELECT * FROM t", "column_names": ["a", "b"]}
    )
    assert target == "dataset_id=sales"


def test_safe_target_empty_when_no_allowlisted_keys():
    assert _safe_target({"query": "SELECT 1"}) is None


def test_log_stage_logs_count_target_and_module_logger(caplog):
    class _Dummy:
        @log_stage
        def fetch(self, query=None, **kwargs):
            # `query` is a method-local concern; it must never reach the log line.
            # `dataset_id` arrives via kwargs and is surfaced as the safe target.
            assert query is not None
            assert "dataset_id" in kwargs
            return pd.DataFrame([{"a": 1}, {"a": 2}])

    with caplog.at_level(logging.INFO, logger=__name__):
        _Dummy().fetch(query="SELECT secret FROM customers", dataset_id="sales")

    records = [r for r in caplog.records if "Fetch" in r.getMessage()]
    assert len(records) == 1
    record = records[0]
    assert record.levelno == logging.INFO
    # Logger name follows the wrapped function's module (per-module hierarchy).
    assert record.name == __name__
    message = record.getMessage()
    assert "dataset_id=sales" in message
    assert "2 rows" in message
    # No SQL / row values leak — the allowlist excludes `query`.
    assert "SELECT" not in message
    assert "secret" not in message


def test_log_stage_count_false_omits_row_count(caplog):
    class _Dummy:
        @log_stage(count=False)
        def fetch(self):
            return {"version": "0.1.1"}

    with caplog.at_level(logging.INFO, logger=__name__):
        _Dummy().fetch()

    message = next(r.getMessage() for r in caplog.records if "Fetch" in r.getMessage())
    assert "rows" not in message


def test_log_timing_emits_label(caplog):
    logger = logging.getLogger(__name__)
    with caplog.at_level(logging.INFO, logger=__name__), log_timing(logger, "Doing work"):
        pass
    assert any("Doing work" in r.getMessage() for r in caplog.records)


def test_configure_logging_is_idempotent(restore_neocarta_logger):
    logger = restore_neocarta_logger
    configure_logging(logging.INFO)
    configure_logging(logging.DEBUG)
    managed = [h for h in logger.handlers if getattr(h, "_neocarta_managed", False)]
    # Repeated calls replace, never accumulate, the managed handler.
    assert len(managed) == 1
    assert logger.level == logging.DEBUG


def test_configure_logging_keeps_propagate_true(restore_neocarta_logger):
    logger = restore_neocarta_logger
    configure_logging(logging.INFO)
    # Propagation must stay on so pytest caplog keeps capturing neocarta.* records.
    assert logger.propagate is True
