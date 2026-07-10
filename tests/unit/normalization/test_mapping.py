"""Unit tests for the rename-mapping primitives."""

from dataclasses import FrozenInstanceError

import pytest

from neocarta.data_model.normalized import DatabaseRecord
from neocarta.normalization import RecordMapping, apply_mappings
from neocarta.normalization.mapping import BaseMapping


def test_apply_mappings_one_to_one_drops_unmapped_source_keys():
    """A one-to-one rename keeps only mapped targets and drops unmapped source keys."""
    assert apply_mappings({"a": 1, "extra": 9}, [("a", "x")]) == {"x": 1}


def test_apply_mappings_one_source_two_targets():
    """One source field can feed multiple targets (mappings is an ordered list, not a dict)."""
    assert apply_mappings({"a": 1}, [("a", "x"), ("a", "y")]) == {"x": 1, "y": 1}


def test_apply_mappings_missing_source_yields_none():
    """A missing source key produces None for its target."""
    assert apply_mappings({}, [("a", "x")]) == {"x": None}


def test_apply_mappings_empty_mappings():
    """No mappings yields an empty dict regardless of the row."""
    assert apply_mappings({"a": 1}, []) == {}


def test_apply_mappings_duplicate_target_later_wins():
    """When two pairs share a target, the later pair wins."""
    assert apply_mappings({"a": 1, "b": 2}, [("a", "x"), ("b", "x")]) == {"x": 2}


def test_record_mapping_is_frozen():
    """RecordMapping is immutable; mutating a field raises FrozenInstanceError."""
    record_mapping = RecordMapping(
        record_type="database",
        target_model=DatabaseRecord,
        mappings=[("catalog", "database_name")],
        container_field="databases",
    )
    with pytest.raises(FrozenInstanceError):
        record_mapping.record_type = "other"


def test_base_mapping_default_is_empty():
    """The base mapping method returns no pairs by default."""
    assert BaseMapping().mappings() == []


def test_base_mapping_subclass_override():
    """A subclass can override the mapping method to return its own pairs."""

    class _Sub(BaseMapping):
        def mappings(self):
            return [("a", "b")]

    assert _Sub().mappings() == [("a", "b")]
