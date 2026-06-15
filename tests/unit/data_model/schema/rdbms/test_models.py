import numpy as np

from neocarta.data_model.schema.rdbms import Column, References


def test_column_valid():
    """Test creating a valid Column node."""
    column = Column(id="col1", name="my_column", description="my column description")
    assert column.id == "col1"
    assert column.name == "my_column"
    assert column.description == "my column description"


def test_column_pk_and_fk():
    """Test creating a Column node with both primary key and foreign key."""
    column = Column(
        id="col1",
        name="my_column",
        description="my column description",
        is_primary_key=True,
        is_foreign_key=True,
    )

    assert column.is_primary_key is True
    assert column.is_foreign_key is True


def test_column_references_criteria_nan_cast_to_none():
    """Test that the criteria field casts NaN values to None."""
    references = References(source_column_id="col1", target_column_id="col2", criteria=np.nan)
    assert references.criteria is None
