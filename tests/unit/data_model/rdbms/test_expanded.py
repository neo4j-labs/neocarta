import numpy as np

from neocarta.data_model.rdbms.expanded import BusinessTerm, Category, Glossary, Value


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


def test_glossary_resource_path_defaults_to_none():
    glossary = Glossary(id="my_glossary", name="My Glossary")
    assert glossary.resource_path is None


def test_glossary_resource_path_set():
    path = "projects/my-project/locations/us/glossaries/my-glossary"
    glossary = Glossary(id="my_glossary", name="My Glossary", resource_path=path)
    assert glossary.resource_path == path


def test_category_resource_path_defaults_to_none():
    category = Category(id="my_glossary.entity_identifiers", name="entity-identifiers")
    assert category.resource_path is None


def test_category_resource_path_set():
    path = "projects/my-project/locations/us/glossaries/my-glossary/categories/entity-identifiers"
    category = Category(
        id="my_glossary.entity_identifiers",
        name="entity-identifiers",
        resource_path=path,
    )
    assert category.resource_path == path


def test_business_term_resource_path_defaults_to_none():
    term = BusinessTerm(id="my_glossary.entity_identifiers.order_id", name="Order ID")
    assert term.resource_path is None


def test_business_term_resource_path_set():
    path = "projects/my-project/locations/us/glossaries/my-glossary/terms/order-id"
    term = BusinessTerm(
        id="my_glossary.entity_identifiers.order_id",
        name="Order ID",
        resource_path=path,
    )
    assert term.resource_path == path
