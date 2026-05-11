"""Unit tests for Dataplex connector utility functions."""

import pytest

from neocarta.connectors.dataplex.utils import (
    parse_business_term_slug,
    parse_category_slug,
    parse_glossary_resource_path,
)


class TestParseCategorySlug:
    def test_valid_path(self):
        path = (
            "projects/my-project/locations/us/glossaries/my-glossary/categories/entity-identifiers"
        )
        assert parse_category_slug(path) == "entity-identifiers"

    def test_valid_path_hyphenated_slug(self):
        path = "projects/p/locations/us/glossaries/g/categories/revenue-metrics"
        assert parse_category_slug(path) == "revenue-metrics"

    def test_invalid_path_missing_categories_segment(self):
        path = "projects/my-project/locations/us/glossaries/my-glossary"
        with pytest.raises(ValueError, match="categories"):
            parse_category_slug(path)

    def test_invalid_path_term_segment(self):
        path = "projects/my-project/locations/us/glossaries/my-glossary/terms/order-item-id"
        with pytest.raises(ValueError, match="categories"):
            parse_category_slug(path)

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="categories"):
            parse_category_slug("")


class TestParseBusinessTermSlug:
    def test_valid_path(self):
        path = "projects/my-project/locations/us/glossaries/my-glossary/terms/order-item-id"
        assert parse_business_term_slug(path) == "order-item-id"

    def test_valid_path_hyphenated_slug(self):
        path = "projects/p/locations/us/glossaries/g/terms/annual-recurring-revenue"
        assert parse_business_term_slug(path) == "annual-recurring-revenue"

    def test_invalid_path_missing_terms_segment(self):
        path = "projects/my-project/locations/us/glossaries/my-glossary"
        with pytest.raises(ValueError, match="terms"):
            parse_business_term_slug(path)

    def test_invalid_path_category_segment(self):
        path = (
            "projects/my-project/locations/us/glossaries/my-glossary/categories/entity-identifiers"
        )
        with pytest.raises(ValueError, match="terms"):
            parse_business_term_slug(path)

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="terms"):
            parse_business_term_slug("")


class TestParseGlossaryResourcePath:
    def test_from_category_path(self):
        path = (
            "projects/my-project/locations/us/glossaries/my-glossary/categories/entity-identifiers"
        )
        assert (
            parse_glossary_resource_path(path)
            == "projects/my-project/locations/us/glossaries/my-glossary"
        )

    def test_from_term_path(self):
        path = "projects/my-project/locations/us/glossaries/my-glossary/terms/order-item-id"
        assert (
            parse_glossary_resource_path(path)
            == "projects/my-project/locations/us/glossaries/my-glossary"
        )

    def test_consistent_across_category_and_term(self):
        glossary_base = "projects/p/locations/us/glossaries/g"
        category_path = f"{glossary_base}/categories/metrics"
        term_path = f"{glossary_base}/terms/arr"
        assert parse_glossary_resource_path(category_path) == parse_glossary_resource_path(
            term_path
        )

    def test_invalid_path_missing_glossaries_segment(self):
        path = "projects/my-project/locations/us"
        with pytest.raises(ValueError, match="glossaries"):
            parse_glossary_resource_path(path)

    def test_invalid_path_no_slug_after_glossaries(self):
        path = "projects/my-project/locations/us/glossaries"
        with pytest.raises(ValueError, match="glossaries"):
            parse_glossary_resource_path(path)

    def test_invalid_empty_string(self):
        with pytest.raises(ValueError, match="glossaries"):
            parse_glossary_resource_path("")
