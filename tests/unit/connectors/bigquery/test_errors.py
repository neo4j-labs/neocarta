"""Tests for the BigQuery vendor-exception → NeocartaError adapter.

The :func:`wrap_bigquery_errors` decorator is applied to every public
``extract_*`` method on the BigQuery extractors. These tests pin down the
mapping so callers never see raw ``google.api_core.exceptions``.
"""

from __future__ import annotations

import pytest
from google.api_core import exceptions as gax

from neocarta.connectors.bigquery._errors import wrap_bigquery_errors
from neocarta.errors import (
    AuthError,
    ConfigError,
    ExtractionError,
    OperationTimeoutError,
    RateLimitError,
)


def _make_raiser(exc: Exception):
    @wrap_bigquery_errors
    def fake_extract_thing(_self):
        raise exc

    return fake_extract_thing


@pytest.mark.parametrize(
    ("vendor_exc", "expected_type"),
    [
        (gax.Unauthenticated("token expired"), AuthError),
        (gax.PermissionDenied("no IAM"), AuthError),
        (gax.BadRequest("project not enabled"), ConfigError),
        (gax.NotFound("dataset missing"), ConfigError),
        (gax.TooManyRequests("rate"), RateLimitError),
        (gax.ResourceExhausted("quota"), RateLimitError),
        (gax.DeadlineExceeded("slow"), OperationTimeoutError),
        (gax.ServiceUnavailable("down"), ExtractionError),
        (gax.InternalServerError("500"), ExtractionError),
    ],
)
def test_vendor_exception_maps_to_neocarta_error(
    vendor_exc: gax.GoogleAPICallError, expected_type: type[Exception]
):
    fn = _make_raiser(vendor_exc)
    with pytest.raises(expected_type) as excinfo:
        fn(None)
    assert excinfo.value.__cause__ is vendor_exc


def test_op_name_recorded_in_details():
    """The wrapped function's name becomes ``details['op']`` so the JSON
    envelope identifies which extraction step failed."""
    fn = _make_raiser(gax.BadRequest("bad project"))
    with pytest.raises(ConfigError) as excinfo:
        fn(None)
    assert excinfo.value.details["op"] == "fake_extract_thing"
    assert excinfo.value.details["connector"] == "bigquery"


def test_vendor_details_preserved_in_envelope():
    """The vendor exception's class, message, and HTTP status are copied
    into ``details`` so they survive in the JSON envelope even without
    ``--debug`` (which surfaces the full chained traceback)."""
    fn = _make_raiser(gax.BadRequest("The project wrong has not enabled BigQuery."))
    with pytest.raises(ConfigError) as excinfo:
        fn(None)
    assert excinfo.value.details["vendor_exception"] == "BadRequest"
    assert excinfo.value.details["vendor_message"] == "The project wrong has not enabled BigQuery."
    assert excinfo.value.details["vendor_http_status"] == 400


def test_transient_5xx_marks_retryable():
    """ServiceUnavailable / InternalServerError → retryable=True so agents
    know they can back off and retry."""
    fn = _make_raiser(gax.ServiceUnavailable("scheduled maintenance"))
    with pytest.raises(ExtractionError) as excinfo:
        fn(None)
    assert excinfo.value.retryable is True


def test_non_transient_4xx_is_not_retryable():
    """Generic 4xx that falls through to GoogleAPICallError stays non-retryable."""

    class WeirdCallError(gax.GoogleAPICallError):
        code = 418

    fn = _make_raiser(WeirdCallError("teapot"))
    with pytest.raises(ExtractionError) as excinfo:
        fn(None)
    assert excinfo.value.retryable is False


def test_unrelated_exception_passes_through():
    """Non-vendor exceptions are not caught — only ``GoogleAPICallError``
    subclasses get mapped."""

    @wrap_bigquery_errors
    def fn(_self):
        raise RuntimeError("not a vendor exception")

    with pytest.raises(RuntimeError, match="not a vendor exception"):
        fn(None)
