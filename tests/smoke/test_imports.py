"""Smoke tests — verify the installed wheel exposes all expected public symbols."""


def test_root_imports():
    import neocarta

    assert hasattr(neocarta, "NodeLabel")
    assert hasattr(neocarta, "RelationshipType")


def test_bigquery_connector_imports():
    from neocarta.connectors.bigquery import BigQueryLogsConnector, BigQuerySchemaConnector

    assert BigQueryLogsConnector
    assert BigQuerySchemaConnector


def test_snowflake_connector_imports():
    from neocarta.connectors.snowflake import SnowflakeLogsConnector, SnowflakeSchemaConnector

    assert SnowflakeLogsConnector
    assert SnowflakeSchemaConnector


def test_databricks_connector_imports():
    # Must import cleanly WITHOUT the optional `databricks` extra installed — guards against an
    # accidental top-level `import databricks.sql`/`databricks.sdk` that would break
    # neocarta[cli] / neocarta[snowflake] users who don't install the databricks driver.
    from neocarta.connectors.databricks import DatabricksSchemaConnector, DatabricksTagsConnector

    assert DatabricksSchemaConnector
    assert DatabricksTagsConnector


def test_csv_connector_imports():
    from neocarta.connectors.csv import CSVConnector

    assert CSVConnector


def test_query_log_connector_imports():
    from neocarta.connectors.query_log import QueryLogConnector

    assert QueryLogConnector


def test_dataplex_connector_imports():
    from neocarta.connectors.dataplex import DataplexGlossaryConnector, DataplexSchemaConnector

    assert DataplexGlossaryConnector
    assert DataplexSchemaConnector


def test_rdbms_data_model_imports():
    from neocarta.data_model.glossary import (
        BusinessTerm,
        Category,
        Glossary,
        HasBusinessTerm,
        HasCategory,
    )
    from neocarta.data_model.instance import HasValue, Value
    from neocarta.data_model.query import Query, UsesColumn, UsesTable
    from neocarta.data_model.schema.rdbms import (
        Column,
        Database,
        HasColumn,
        HasSchema,
        HasTable,
        References,
        Schema,
        Table,
    )

    assert all(
        [
            BusinessTerm,
            Category,
            Column,
            Database,
            Glossary,
            HasBusinessTerm,
            HasCategory,
            HasColumn,
            HasSchema,
            HasTable,
            HasValue,
            Query,
            References,
            Schema,
            Table,
            UsesColumn,
            UsesTable,
            Value,
        ]
    )


def test_enrichment_imports():
    from neocarta.enrichment.embeddings import LiteLLMEmbeddingsConnector, OpenAIEmbeddingsConnector

    assert LiteLLMEmbeddingsConnector
    assert OpenAIEmbeddingsConnector


def test_ingest_imports():
    from neocarta.ingest.rdbms import Neo4jRDBMSLoader

    assert Neo4jRDBMSLoader


def test_osi_connector_imports():
    from neocarta.connectors.osi import OsiConnector, UnsupportedOsiVersionWarning

    assert OsiConnector
    assert UnsupportedOsiVersionWarning


def test_warnings_module_imports():
    from neocarta.warnings import NeocartaWarning, UnsupportedOsiVersionWarning

    assert issubclass(NeocartaWarning, UserWarning)
    assert issubclass(UnsupportedOsiVersionWarning, NeocartaWarning)


def test_osi_data_model_imports():
    from neocarta.data_model.osi import (
        Aspect,
        Domain,
        DomainHasTable,
        Expression,
        HasAspect,
        HasExpression,
        HasMetric,
        HasQuery,
        HasSourceTable,
        HasTargetTable,
        Join,
        Metric,
        OsiAiContext,
        OsiColumn,
        OsiCustomExtensions,
        OsiSemanticModel,
        OsiTable,
        UsedInJoin,
    )

    assert all(
        [
            Aspect,
            Domain,
            DomainHasTable,
            Expression,
            HasAspect,
            HasExpression,
            HasMetric,
            HasQuery,
            HasSourceTable,
            HasTargetTable,
            Join,
            Metric,
            OsiAiContext,
            OsiColumn,
            OsiCustomExtensions,
            OsiSemanticModel,
            OsiTable,
            UsedInJoin,
        ]
    )


def test_etl_scaffold_imports():
    # Empty 1.0.0 target packages scaffolded in S0-5 (#286); no code moved yet (see GUIDE §5).
    import neocarta.etl
    import neocarta.etl.enrichment
    import neocarta.etl.metadata_normalizer
    import neocarta.etl.metadata_normalizer.normalized_schema
    import neocarta.etl.models
    import neocarta.etl.ontology
    import neocarta.etl.pipeline
    import neocarta.etl.transform

    assert neocarta.etl.pipeline


def test_extensions_scaffold_imports():
    # Empty 1.0.0 target packages scaffolded in S0-5 (#286); no code moved yet (see GUIDE §5).
    import neocarta.extensions
    import neocarta.extensions.connectors
    import neocarta.extensions.enrichments

    assert neocarta.extensions.connectors
