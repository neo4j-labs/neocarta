"""Unit tests for the MCP full-text query sanitiser (escape_lucene_query).

Guards V-03: the sanitiser must neutralise Lucene query syntax on untrusted
``text_content`` (so an MCP client cannot inject operators or trigger a Lucene
parse error) while preserving the search terms — a departure from the old
strip-based helper that silently dropped content and left AND/OR/NOT live.
"""

import pytest

from neocarta._mcp.utils import escape_lucene_query


@pytest.mark.parametrize("blank", [None, "", "   ", "\n\t"])
def test_blank_input_returns_none(blank):
    """Empty or whitespace-only input yields None (no query to run)."""
    assert escape_lucene_query(blank) is None


def test_plain_terms_pass_through_unchanged():
    """Ordinary words with no special characters are preserved verbatim."""
    assert escape_lucene_query("customer orders") == "customer orders"


def test_multi_whitespace_collapses_to_single_spaces():
    """Tokenisation normalises runs of whitespace to single spaces."""
    assert escape_lucene_query("  customer   orders \t revenue ") == "customer orders revenue"


@pytest.mark.parametrize(
    ("char"),
    ["+", "-", "&", "|", "!", "(", ")", "{", "}", "[", "]", "^", '"', "~", "*", "?", ":", "/"],
)
def test_each_special_char_is_backslash_escaped(char):
    """Every Lucene special character is escaped, not dropped."""
    result = escape_lucene_query(f"a{char}b")
    assert result == f"a\\{char}b"


def test_backslash_is_escaped():
    """A literal backslash is doubled so Lucene treats it literally."""
    assert escape_lucene_query("a\\b") == "a\\\\b"


def test_content_is_preserved_not_stripped():
    """Regression vs the old helper: 'C++' must survive, not become 'C  '."""
    assert escape_lucene_query("C++") == "C\\+\\+"


@pytest.mark.parametrize("operator", ["AND", "OR", "NOT", "TO"])
def test_boolean_operators_are_neutralised(operator):
    """Bare upper-case boolean operators are lower-cased into ordinary terms."""
    result = escape_lucene_query(f"alpha {operator} beta")
    assert f" {operator} " not in f" {result} "
    assert result == f"alpha {operator.lower()} beta"


def test_lowercase_operator_words_are_left_alone():
    """Only the reserved upper-case forms are operators; lower-case words stay."""
    assert escape_lucene_query("or and not") == "or and not"


def test_field_scoped_injection_is_defused():
    """A field:value probe can't reach Lucene as a field query — the colon is escaped."""
    assert escape_lucene_query("name:secret") == "name\\:secret"


def test_boolean_and_special_injection_combined():
    """A crafted operator+wildcard payload is fully neutralised."""
    # Would be an OR of everything under the old strip helper; now inert.
    assert escape_lucene_query("orders OR *") == "orders or \\*"
