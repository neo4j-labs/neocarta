"""Unit tests for UC volume-path parsing and the protected-name guard."""

from __future__ import annotations

import pytest
from dbxcarta.core.identifiers import (
    UC_PROTECTED_NAMES,
    check_not_protected,
    parse_volume_path,
)


def test_parse_volume_path_splits_three_identifiers() -> None:
    assert parse_volume_path("/Volumes/cat/sch/vol") == ("cat", "sch", "vol")


def test_parse_volume_path_tolerates_trailing_slash() -> None:
    assert parse_volume_path("/Volumes/cat/sch/vol/") == ("cat", "sch", "vol")


@pytest.mark.parametrize(
    "value",
    [
        "/Volumes/cat/sch",  # too few parts
        "/Volumes/cat/sch/vol/sub",  # has a subdir; use validate_uc_volume_subpath
        "/Wrong/cat/sch/vol",  # not a Volumes path
        "/Volumes/cat/sch/1bad",  # invalid leading-digit identifier
    ],
)
def test_parse_volume_path_rejects_bad_paths(value: str) -> None:
    with pytest.raises(ValueError):
        parse_volume_path(value)


def test_check_not_protected_allows_example_catalog() -> None:
    assert check_not_protected("schemapile_lakehouse") == "schemapile_lakehouse"


@pytest.mark.parametrize("name", sorted(UC_PROTECTED_NAMES))
def test_check_not_protected_refuses_system_catalogs(name: str) -> None:
    with pytest.raises(ValueError, match="protected"):
        check_not_protected(name)
