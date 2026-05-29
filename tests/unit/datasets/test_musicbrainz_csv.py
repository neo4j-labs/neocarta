"""Integrity checks for the bundled MusicBrainz schema CSVs.

These run without Neo4j: they load datasets/musicbrainz/ through the same
``CSVExtractor`` the connector uses and assert the schema is well-formed
(12 tables, 86 columns, 11 foreign keys, consistent references).
"""

from pathlib import Path

import pandas as pd
import pytest

from neocarta.connectors.csv.extract import CSVExtractor

MUSICBRAINZ_DIR = Path(__file__).resolve().parents[3] / "datasets" / "musicbrainz"


@pytest.fixture
def extractor() -> CSVExtractor:
    """A CSVExtractor pointed at the bundled MusicBrainz dataset."""
    e = CSVExtractor(str(MUSICBRAINZ_DIR))
    e.extract_all()
    return e


def _is_true(series: pd.Series) -> pd.Series:
    """Normalize a CSV boolean-ish column to a boolean Series."""
    return series.astype(str).str.lower() == "true"


def test_dataset_directory_exists():
    assert MUSICBRAINZ_DIR.is_dir()


def test_single_database_and_schema(extractor):
    assert len(extractor.database_info) == 1
    assert len(extractor.schema_info) == 1
    assert extractor.database_info.iloc[0]["database_name"] == "MusicBrainz"
    assert extractor.schema_info.iloc[0]["schema_name"] == "musicbrainz"


def test_expected_counts(extractor):
    assert len(extractor.table_info) == 12
    assert len(extractor.column_info) == 86
    assert len(extractor.column_references_info) == 11


def test_flag_counts(extractor):
    columns = extractor.column_info
    assert _is_true(columns["is_primary_key"]).sum() == 11
    assert _is_true(columns["is_foreign_key"]).sum() == 11


def test_descriptions_are_embeddable(extractor):
    # get_nodes_to_embed skips descriptions shorter than 20 chars.
    descriptions = extractor.column_info["description"]
    assert descriptions.notna().all()
    assert (descriptions.str.len() >= 20).all()


def test_references_point_at_real_columns(extractor):
    column_keys = {
        (row.table_name, row.column_name) for row in extractor.column_info.itertuples(index=False)
    }
    for ref in extractor.column_references_info.itertuples(index=False):
        assert (ref.source_table_name, ref.source_column_name) in column_keys
        assert (ref.target_table_name, ref.target_column_name) in column_keys


def test_every_fk_column_has_a_reference(extractor):
    columns = extractor.column_info
    fk_columns = {
        (row.table_name, row.column_name)
        for row in columns[_is_true(columns["is_foreign_key"])].itertuples(index=False)
    }
    reference_sources = {
        (ref.source_table_name, ref.source_column_name)
        for ref in extractor.column_references_info.itertuples(index=False)
    }
    assert fk_columns == reference_sources
