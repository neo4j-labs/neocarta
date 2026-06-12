"""Models for JDBC schema extraction."""

from typing import TypedDict

import pandas as pd


class JdbcSchemaExtractorCache(TypedDict):
    """Cache dictionary for JDBC schema metadata extraction.

    Mirrors the BigQuery schema cache shape (minus value sampling, which
    SchemaCrawler does not perform). Each DataFrame carries the
    ``database_name`` / ``schema_name`` / ... columns the transformer needs to
    build hierarchical ids.
    """

    database_info: pd.DataFrame | None
    schema_info: pd.DataFrame | None
    table_info: pd.DataFrame | None
    column_info: pd.DataFrame | None
    column_references_info: pd.DataFrame | None
