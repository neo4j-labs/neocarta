"""CLI verbosity wiring: --log-level / --debug map onto the neocarta logger."""

import logging

import pytest
from click.testing import CliRunner

from neocarta._cli import cli
from neocarta._logging import PACKAGE_LOGGER_NAME


@pytest.fixture(autouse=True)
def restore_neocarta_logger():
    """Restore the neocarta logger after each CLI invocation configures it."""
    logger = logging.getLogger(PACKAGE_LOGGER_NAME)
    original_handlers = logger.handlers[:]
    original_level = logger.level
    yield
    for handler in logger.handlers[:]:
        if handler not in original_handlers:
            logger.removeHandler(handler)
            handler.close()
    logger.setLevel(original_level)


def test_help_lists_log_level():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "--log-level" in result.output


def test_log_level_flag_sets_logger_level():
    result = CliRunner().invoke(cli, ["--log-level", "DEBUG", "agent-context"])
    assert result.exit_code == 0
    assert logging.getLogger(PACKAGE_LOGGER_NAME).level == logging.DEBUG


def test_debug_flag_aliases_debug_level():
    result = CliRunner().invoke(cli, ["--debug", "agent-context"])
    assert result.exit_code == 0
    assert logging.getLogger(PACKAGE_LOGGER_NAME).level == logging.DEBUG


def test_default_level_is_info():
    result = CliRunner().invoke(cli, ["agent-context"])
    assert result.exit_code == 0
    assert logging.getLogger(PACKAGE_LOGGER_NAME).level == logging.INFO


def test_agent_context_stdout_stays_valid_json_under_logging():
    """Logs go to stderr; stdout must remain parseable JSON even at DEBUG."""
    import json

    # Click >=8.2 captures stdout and stderr separately, so result.output is stdout only.
    result = CliRunner().invoke(cli, ["--log-level", "DEBUG", "agent-context"])
    assert result.exit_code == 0
    json.loads(result.output)  # raises if stdout was polluted by log records
