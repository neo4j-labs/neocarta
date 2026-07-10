"""Concrete ``INFORMATION_SCHEMA`` normalizer adapters (Layer-1 retrievers + Layer-2 specs)."""

from .bigquery import (
    BIGQUERY_INFORMATION_SCHEMA_SPEC,
    BigQueryInformationSchemaRetriever,
    build_bigquery_information_schema_normalizer,
)

__all__ = [
    "BIGQUERY_INFORMATION_SCHEMA_SPEC",
    "BigQueryInformationSchemaRetriever",
    "build_bigquery_information_schema_normalizer",
]
