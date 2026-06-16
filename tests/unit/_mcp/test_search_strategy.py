"""Unit tests for the per-label search-strategy priority logic."""

import pytest

from neocarta._mcp.server import _select_search_strategy


@pytest.mark.parametrize(
    ("inventory", "business_term_search_available", "expected"),
    [
        # No indexes → no tool.
        (set(), False, None),
        # Vector only → vector.
        ({("Table", "VECTOR")}, False, "vector"),
        # Full-text only → full_text.
        ({("Table", "FULLTEXT")}, False, "full_text"),
        # Vector + FT, no BT available → hybrid.
        ({("Table", "VECTOR"), ("Table", "FULLTEXT")}, False, "hybrid"),
        # Vector + FT, BT available → BT-hybrid (top priority).
        ({("Table", "VECTOR"), ("Table", "FULLTEXT")}, True, "business_term_hybrid"),
        # BT available but missing one of vector/FT → falls back.
        ({("Table", "VECTOR")}, True, "vector"),
        ({("Table", "FULLTEXT")}, True, "full_text"),
    ],
)
def test_select_search_strategy_priority(
    inventory: set[tuple[str, str]],
    business_term_search_available: bool,
    expected: str | None,
) -> None:
    assert _select_search_strategy("Table", inventory, business_term_search_available) == expected


def test_select_search_strategy_is_per_label() -> None:
    """A label with no relevant indexes returns None even if other labels have tools."""
    inventory = {("Table", "VECTOR"), ("Table", "FULLTEXT")}
    assert _select_search_strategy("Column", inventory, True) is None
    assert _select_search_strategy("Table", inventory, True) == "business_term_hybrid"


@pytest.mark.parametrize(
    ("inventory", "business_term_search_available", "expected"),
    [
        # No Metric indexes → no metric tool.
        (set(), False, None),
        ({("Table", "VECTOR")}, True, None),
        # Vector only → vector.
        ({("Metric", "VECTOR")}, False, "vector"),
        # Full-text only → full_text.
        ({("Metric", "FULLTEXT")}, False, "full_text"),
        # Vector + FT, no BT → hybrid.
        ({("Metric", "VECTOR"), ("Metric", "FULLTEXT")}, False, "hybrid"),
        # Vector + FT, BT available → BT-hybrid (top priority).
        ({("Metric", "VECTOR"), ("Metric", "FULLTEXT")}, True, "business_term_hybrid"),
    ],
)
def test_select_search_strategy_for_metric(
    inventory: set[tuple[str, str]],
    business_term_search_available: bool,
    expected: str | None,
) -> None:
    """The same priority ladder drives Metric tool selection (keyed on the Metric label)."""
    assert _select_search_strategy("Metric", inventory, business_term_search_available) == expected
