"""Unit tests for the Neocarta library exception hierarchy.

These tests pin down two contracts that other modules rely on:

1. Every concrete error sets a ``code`` that exists in
   :data:`neocarta._cli.errors.EXIT_CODES`, so the CLI adapter can always
   map a library error to a documented exit code.
2. Cross-cutting errors (rate limit, timeout) default to ``retryable=True``
   so callers can branch on the attribute without inspecting the class.
"""

from __future__ import annotations

import pytest

from neocarta._cli.errors import EXIT_CODES
from neocarta.errors import (
    AuthError,
    ConfigError,
    ConnectorError,
    ConstraintCreationError,
    EnrichmentError,
    ExtractionError,
    IndexCreationError,
    LoadError,
    Neo4jConnectionError,
    Neo4jError,
    NeocartaError,
    OperationTimeoutError,
    RateLimitError,
    StateError,
    TransformError,
)

ALL_ERRORS: list[type[NeocartaError]] = [
    NeocartaError,
    ConfigError,
    AuthError,
    StateError,
    RateLimitError,
    OperationTimeoutError,
    ConnectorError,
    ExtractionError,
    TransformError,
    EnrichmentError,
    Neo4jError,
    Neo4jConnectionError,
    LoadError,
    ConstraintCreationError,
    IndexCreationError,
]


@pytest.mark.parametrize("error_cls", ALL_ERRORS)
def test_error_code_is_a_known_exit_code(error_cls: type[NeocartaError]) -> None:
    """Every error class must declare an exit-code key that the CLI knows."""
    assert error_cls.code in EXIT_CODES, (
        f"{error_cls.__name__}.code={error_cls.code!r} is not in EXIT_CODES"
    )


@pytest.mark.parametrize("error_cls", ALL_ERRORS)
def test_all_errors_subclass_neocarta_error(error_cls: type[NeocartaError]) -> None:
    """A single ``except NeocartaError`` must catch every library error."""
    assert issubclass(error_cls, NeocartaError)


def test_default_attributes() -> None:
    err = NeocartaError("boom")
    assert err.message == "boom"
    assert err.suggestion is None
    assert err.retryable is False
    assert err.details == {}
    # The stdlib Exception message must round-trip via str().
    assert str(err) == "boom"


def test_structured_context_round_trips() -> None:
    err = ExtractionError(
        "BigQuery query failed during extract_table_info.",
        suggestion="Check IAM permissions on the dataset.",
        details={"connector": "bigquery.schema", "op": "extract_table_info"},
    )
    assert err.code == "upstream_error"
    assert err.suggestion == "Check IAM permissions on the dataset."
    assert err.details["op"] == "extract_table_info"


def test_rate_limit_error_defaults_retryable_true() -> None:
    err = RateLimitError("Quota exceeded.")
    assert err.retryable is True


def test_rate_limit_error_respects_explicit_retryable() -> None:
    err = RateLimitError("Quota exceeded.", retryable=False)
    assert err.retryable is False


def test_operation_timeout_defaults_retryable_true() -> None:
    err = OperationTimeoutError("Deadline exceeded.")
    assert err.retryable is True


def test_neo4j_errors_share_a_base_for_broad_catch() -> None:
    """LoadError, ConstraintCreationError, IndexCreationError, and
    Neo4jConnectionError must all be catchable as :class:`Neo4jError`."""
    for cls in (LoadError, ConstraintCreationError, IndexCreationError, Neo4jConnectionError):
        assert issubclass(cls, Neo4jError)


def test_chained_cause_is_preserved() -> None:
    """``raise NeocartaError(...) from e`` must keep the original exception
    reachable via ``__cause__`` so debugging information is not lost."""
    original = RuntimeError("vendor SDK blew up")

    def reraise() -> None:
        try:
            raise original
        except RuntimeError as e:
            raise ExtractionError("Extraction failed.") from e

    with pytest.raises(ExtractionError) as excinfo:
        reraise()
    assert excinfo.value.__cause__ is original
