"""Models for Databricks schema extraction."""

from typing import TypedDict

import pandas as pd


class SchemaExtractorCache(TypedDict, total=False):
    """Cache dictionary for Databricks schema metadata extraction.

    Mirrors the BigQuery schema extractor cache: one pandas DataFrame per
    extraction stage, keyed by stage name. ``total=False`` so a partially
    populated cache (e.g. after a filtered or interrupted extract) is still a
    valid value.
    """

    database_info: pd.DataFrame | None
    schema_info: pd.DataFrame | None
    table_info: pd.DataFrame | None
    column_info: pd.DataFrame | None
    column_references_info: pd.DataFrame | None
    column_unique_values: pd.DataFrame | None
