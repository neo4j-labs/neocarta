"""Offline drivers for the three connectors in the S1.6 proof set.

Each fixture returns a :class:`Case` holding both halves of the comparison: the object
today's hand-written ``transform.py`` produces, and the one the candidate mechanism produces
from the *same* extractor. Every driver runs fully offline against an oracle already committed
to the repo — the shared BigQuery cache seed, the SchemaCrawler JSON fixture, and the
``datasets/csv`` sample — so no fixture had to be invented for this spike.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from neocarta.connectors.bigquery.schema.extract import BigQuerySchemaExtractor
from neocarta.connectors.bigquery.schema.transform import BigQuerySchemaTransformer
from neocarta.connectors.csv import CSVConnector
from neocarta.connectors.jdbc.schema.extract import JdbcSchemaExtractor
from neocarta.connectors.jdbc.schema.transform import JdbcSchemaTransformer
from tests.support.characterization import DATASETS_CSV, serialize_transform
from tests.support.characterization.bigquery_cache import (
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)
from tests.support.mapping_spike import (
    BIGQUERY_SCHEMA,
    CSV,
    JDBC_SCHEMA,
    bind_all,
    observed_columns,
    transformer_for,
)

_JDBC_FIXTURE = (
    pathlib.Path(__file__).parents[3]
    / "unit"
    / "connectors"
    / "jdbc"
    / "schema"
    / "fixtures"
    / "schemacrawler_postgres.json"
)
_JAVA_CHECK = "neocarta.connectors.jdbc.schema.extract._assert_java_available"
_SUBPROCESS_RUN = "neocarta.connectors.jdbc.schema.extract.subprocess.run"


@dataclass
class Case:
    """One connector's before/after pair, plus what a sensitivity test needs to rebuild it.

    Attributes:
        name: The connector's name, for test ids and failure messages.
        legacy: The hand-written transformer, already driven.
        prototype: The candidate mechanism's transformer, already driven.
        extractor: The offline extractor both halves were driven from.
        mapping: The connector's declaration.
    """

    name: str
    legacy: Any
    prototype: Any
    extractor: Any
    mapping: Any

    def serialized(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Serialize both halves through the #291 Layer A harness."""
        return serialize_transform(self.legacy), serialize_transform(self.prototype)

    def rebuild(self) -> Any:
        """Re-run the mechanism from the same extractor.

        Sensitivity controls use this to rebuild *after* patching a production rule, so the
        injected change actually flows through id generation rather than being asserted about.
        """
        return _prototype(self.extractor, self.mapping)


def _prototype(extractor: Any, mapping: Any) -> Any:
    """Run the candidate mechanism end to end for one connector."""
    return transformer_for(mapping).transform(
        bind_all(extractor, mapping), observed_columns(extractor, mapping)
    )


@pytest.fixture
def bigquery_case() -> Case:
    """BigQuery schema: the hardest tabular case (derived-value row drop, values facet)."""
    extractor = seed_bigquery_schema_cache(
        BigQuerySchemaExtractor(client=make_mock_bigquery_client(), dataset_id="test_dataset")
    )
    legacy = BigQuerySchemaTransformer()
    legacy.transform_to_database_nodes(extractor.database_info)
    legacy.transform_to_schema_nodes(extractor.schema_info)
    legacy.transform_to_table_nodes(extractor.table_info)
    legacy.transform_to_column_nodes(extractor.column_info)
    legacy.transform_to_value_nodes(extractor.column_unique_values)
    legacy.transform_to_has_schema_relationships(extractor.schema_info)
    legacy.transform_to_has_table_relationships(extractor.table_info)
    legacy.transform_to_has_column_relationships(extractor.column_info)
    legacy.transform_to_references_relationships(extractor.column_references_info)
    legacy.transform_to_has_value_relationships(extractor.column_unique_values)
    return Case(
        "bigquery/schema",
        legacy,
        _prototype(extractor, BIGQUERY_SCHEMA),
        extractor,
        BIGQUERY_SCHEMA,
    )


@pytest.fixture
def jdbc_case() -> Case:
    """JDBC schema: whole-collection property scope, and Layer A's blindness to it."""
    catalog = _JDBC_FIXTURE.read_text(encoding="utf-8")
    with patch(_JAVA_CHECK):
        extractor = JdbcSchemaExtractor(
            jdbc_url="jdbc:postgresql://localhost:5432/neocarta_test",
            jdbc_driver="org.postgresql.Driver",
            jdbc_driver_jar="schemacrawler-jars/postgresql.jar",
            schemacrawler_jar="schemacrawler-jars/schemacrawler.jar",
            source_database_name="neocarta_test",
        )
        completed = MagicMock(returncode=0, stdout=catalog, stderr="")
        with patch(_SUBPROCESS_RUN, return_value=completed):
            extractor.extract()

    legacy = JdbcSchemaTransformer()
    legacy.transform_to_database_nodes(extractor.database_info)
    legacy.transform_to_schema_nodes(extractor.schema_info)
    legacy.transform_to_table_nodes(extractor.table_info)
    legacy.transform_to_column_nodes(extractor.column_info)
    legacy.transform_to_has_schema_relationships(extractor.schema_info)
    legacy.transform_to_has_table_relationships(extractor.table_info)
    legacy.transform_to_has_column_relationships(extractor.column_info)
    legacy.transform_to_references_relationships(extractor.column_references_info)
    return Case("jdbc/schema", legacy, _prototype(extractor, JDBC_SCHEMA), extractor, JDBC_SCHEMA)


@pytest.fixture
def csv_case() -> Case:
    """CSV: the widest type surface, column-presence property scope, two-frame assignments."""
    connector = CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=MagicMock())
    connector.extract()
    connector.transform()
    return Case(
        "csv",
        connector.transformer,
        _prototype(connector.extractor, CSV),
        connector.extractor,
        CSV,
    )
