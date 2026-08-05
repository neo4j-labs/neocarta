"""Seam 3 (Layer B): the mapping mechanism produces the same **graph**, end to end (Docker).

Layer A proves the mechanism emits the same models; this proves those models land as the same
Neo4j graph once the real loader has written them. The distinction is not academic — the
loader decides which properties are written from the ``properties_list`` it is handed, so a
mechanism that got model contents right but property *scope* wrong would pass Layer A and
still corrupt the graph by writing ``NULL`` over another connector's data (**D10**,
``docs/refactor/merge-contract.md``).

That is exactly the case Layer A cannot see for every connector: ``serialize_transform`` only
records an allowlist for transformers exposing ``get_properties``. So this is the seam where
property scope is proven by its *effect* rather than by comparing a list.

Both goldens are the ones committed for the hand-written connectors — reused unchanged, which
is what makes this a parity proof rather than a new characterization.
"""

from __future__ import annotations

from pathlib import Path

from neocarta.connectors.bigquery.schema.connector import BigQuerySchemaConnector
from neocarta.connectors.csv import CSVConnector
from tests.support.characterization import (
    DATASETS_CSV,
    assert_matches_golden,
    dump_graph,
    make_mock_bigquery_client,
    seed_bigquery_schema_cache,
)
from tests.support.mapping_spike import (
    BIGQUERY_SCHEMA,
    CSV,
    bind_all,
    observed_columns,
    transformer_for,
)

_CONNECTORS_DIR = Path(__file__).parents[1] / "connectors"
_BIGQUERY_GOLDEN = _CONNECTORS_DIR / "bigquery" / "schema" / "golden" / "bigquery_schema_graph.json"
_CSV_GOLDEN = _CONNECTORS_DIR / "csv" / "golden" / "csv_graph.json"


def _drive(extractor: object, mapping: object) -> object:
    """Run the mechanism for one connector against an already-populated extractor."""
    return transformer_for(mapping).transform(
        bind_all(extractor, mapping), observed_columns(extractor, mapping)
    )


def test_bigquery_graph_matches_the_committed_golden(neo4j_driver) -> None:
    """BigQuery: the mechanism's models, through the real loader, reproduce the graph golden.

    The connector's own ``load()`` sequence is used verbatim, with only the transformer
    swapped, so the loader — constraints, indexes, merge policy and property defaults — is
    the production one throughout.
    """
    connector = BigQuerySchemaConnector(
        client=make_mock_bigquery_client(),
        project_id="test-project-id",
        neo4j_driver=neo4j_driver,
    )
    seed_bigquery_schema_cache(connector.extractor)
    transformer = _drive(connector.extractor, BIGQUERY_SCHEMA)

    loader = connector.loader
    loader.load_database_nodes(transformer.database_nodes)
    loader.load_schema_nodes(transformer.schema_nodes)
    loader.load_table_nodes(transformer.table_nodes)
    loader.load_column_nodes(transformer.column_nodes)
    loader.load_value_nodes(transformer.value_nodes)
    loader.load_has_schema_relationships(transformer.has_schema_relationships)
    loader.load_has_table_relationships(transformer.has_table_relationships)
    loader.load_has_column_relationships(transformer.has_column_relationships)
    loader.load_references_relationships(transformer.references_relationships)
    loader.load_has_value_relationships(transformer.has_value_relationships)
    loader.upsert_neocarta_graph_node()

    assert_matches_golden(_BIGQUERY_GOLDEN, dump_graph(neo4j_driver, "neo4j"))


def test_csv_structural_and_glossary_graph_matches_the_committed_golden(neo4j_driver) -> None:
    """CSV: the same, with the mechanism's ``property_scope`` driving what gets written.

    CSV is the connector whose written-property set is computed from each file's own header, so
    this is where the ``property_scope`` hatch is validated by its effect on the graph. The
    query families (**D11**, no normalized table) are loaded from the hand-written transformer
    so the comparison is against the *whole* committed golden rather than a trimmed copy — the
    tabular half comes from the mechanism, and any divergence in it still fails.
    """
    connector = CSVConnector(csv_directory=str(DATASETS_CSV), neo4j_driver=neo4j_driver)
    connector.extract()
    connector.transform()
    legacy = connector.transformer
    mechanism = _drive(connector.extractor, CSV)
    loader = connector.loader

    def scope(family: str) -> list[str]:
        return mechanism.get_properties(family)

    loader.load_database_nodes(mechanism.database_nodes, properties_list=scope("database_nodes"))
    loader.load_schema_nodes(mechanism.schema_nodes, properties_list=scope("schema_nodes"))
    loader.load_table_nodes(mechanism.table_nodes, properties_list=scope("table_nodes"))
    loader.load_column_nodes(mechanism.column_nodes, properties_list=scope("column_nodes"))
    loader.load_value_nodes(mechanism.value_nodes, properties_list=scope("value_nodes"))
    loader.load_glossary_nodes(mechanism.glossary_nodes, properties_list=scope("glossary_nodes"))
    loader.load_category_nodes(mechanism.category_nodes, properties_list=scope("category_nodes"))
    loader.load_business_term_nodes(
        mechanism.business_term_nodes, properties_list=scope("business_term_nodes")
    )
    loader.load_has_schema_relationships(mechanism.has_schema_relationships)
    loader.load_has_table_relationships(mechanism.has_table_relationships)
    loader.load_has_column_relationships(mechanism.has_column_relationships)
    loader.load_has_value_relationships(mechanism.has_value_relationships)
    loader.load_references_relationships(mechanism.references_relationships)
    loader.load_has_category_relationships(mechanism.has_category_relationships)
    loader.load_has_business_term_relationships(mechanism.has_business_term_relationships)
    loader.load_column_tagged_with_relationships(mechanism.column_tagged_with_relationships)
    loader.load_table_tagged_with_relationships(mechanism.table_tagged_with_relationships)

    # The D11 query surface, from the hand-written transformer: it has no normalized table, so
    # the mechanism cannot produce it and the committed golden contains it.
    loader.load_query_nodes(
        legacy.query_nodes, properties_list=legacy.get_properties("query_nodes")
    )
    loader.load_uses_table_relationships(legacy.uses_table_relationships)
    loader.load_uses_column_relationships(legacy.uses_column_relationships)
    loader.upsert_neocarta_graph_node()

    assert_matches_golden(_CSV_GOLDEN, dump_graph(neo4j_driver, "neo4j"))
