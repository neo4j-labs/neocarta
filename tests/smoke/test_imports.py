"""Smoke tests — verify the installed wheel exposes all expected public symbols."""


def test_root_imports():
    import neocarta

    assert hasattr(neocarta, "NodeLabel")
    assert hasattr(neocarta, "RelationshipType")


def test_bigquery_connector_imports():
    from neocarta.connectors.bigquery import (
        BigQueryLogsConnector,
        BigQueryLogsExtractor,
        BigQuerySchemaConnector,
        BigQuerySchemaExtractor,
        BigQuerySchemaTransformer,
    )

    assert BigQueryLogsConnector
    assert BigQueryLogsExtractor
    assert BigQuerySchemaConnector
    assert BigQuerySchemaExtractor
    assert BigQuerySchemaTransformer


def test_csv_connector_imports():
    from neocarta.connectors.csv import CSVConnector, CSVExtractor, CSVTransformer

    assert CSVConnector
    assert CSVExtractor
    assert CSVTransformer


def test_query_log_connector_imports():
    from neocarta.connectors.query_log import (
        QueryLogConnector,
        QueryLogExtractor,
        QueryLogTransformer,
    )

    assert QueryLogConnector
    assert QueryLogExtractor
    assert QueryLogTransformer


def test_rdbms_data_model_imports():
    from neocarta.data_model.rdbms import (
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
    from neocarta.connectors.osi import OsiConnector
    from neocarta.connectors.osi.export import OsiExportTransformer, OsiGraphExtractor
    from neocarta.connectors.osi.ingest import OsiIngestTransformer, OsiSpecExtractor
    from neocarta.connectors.osi.load import OsiNeo4jLoader

    assert OsiConnector
    assert OsiSpecExtractor
    assert OsiIngestTransformer
    assert OsiGraphExtractor
    assert OsiExportTransformer
    assert OsiNeo4jLoader


def test_osi_data_model_imports():
    from neocarta.data_model.rdbms import (
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
