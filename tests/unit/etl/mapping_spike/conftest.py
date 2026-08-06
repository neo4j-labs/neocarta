"""Before/after pairs for the three connectors in the S1.6 Layer A parity proof.

Each fixture returns a :class:`Case` holding both halves of the comparison: the object today's
hand-written ``transform.py`` produces, and the one the mechanism produces from the *same*
extractor. The extractors themselves come from ``tests/support/connectors/offline.py``, shared
with the ``metadata_normalizer`` suite so both drive the same objects rather than two lookalikes.

The mechanism's record half is production as of S1.7 (#298); only the record→graph transform is
still a prototype, and it is what these fixtures exist to compare.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from neocarta.connectors.bigquery.schema.transform import BigQuerySchemaTransformer
from neocarta.connectors.jdbc.schema.transform import JdbcSchemaTransformer
from tests.support.characterization import serialize_transform
from tests.support.connectors.offline import build_extractor, csv_connector
from tests.support.mapping_spike import (
    BIGQUERY_SCHEMA,
    CSV,
    JDBC_SCHEMA,
    bind_all,
    observed_columns,
    transformer_for,
)


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
    extractor = build_extractor("bigquery/schema")
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
    extractor = build_extractor("jdbc/schema")
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
    connector = csv_connector()
    connector.transform()
    return Case(
        "csv",
        connector.transformer,
        _prototype(connector.extractor, CSV),
        connector.extractor,
        CSV,
    )
