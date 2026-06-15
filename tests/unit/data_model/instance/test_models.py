"""Unit tests for the instance (data value) data model components."""

import numpy as np

from neocarta.data_model.instance import HasValue, Value


def test_value_string():
    """Test creating a Value node with string type."""
    value = Value(id="v1", value="John Doe")
    assert value.id == "v1"
    assert value.value == "John Doe"


def test_value_int():
    """Test creating a Value node with int type."""
    value = Value(id="v1", value=1)
    assert value.id == "v1"
    assert value.value == "1"


def test_value_float():
    """Test creating a Value node with float type."""
    value = Value(id="v1", value=3.14)
    assert value.id == "v1"
    assert value.value == "3.14"


def test_value_nan():
    """Test creating a Value node with NaN value."""
    value = Value(id="v1", value=np.nan)
    assert value.id == "v1"
    assert value.value == ""


def test_value_none():
    """Test creating a Value node with None value."""
    value = Value(id="v1", value=None)
    assert value.id == "v1"
    assert value.value == ""


def test_has_value_links_column_to_value():
    """A HasValue relationship carries the column and value ids."""
    rel = HasValue(column_id="col1", value_id="v1")
    assert rel.column_id == "col1"
    assert rel.value_id == "v1"
