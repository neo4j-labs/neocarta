"""Unit tests for the glossary data model components."""

from neocarta.data_model.glossary import BusinessTerm, Category, Glossary


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
