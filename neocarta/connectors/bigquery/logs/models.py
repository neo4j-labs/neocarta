"""Models for BigQuery query log extraction."""

from typing import TypedDict

import pandas as pd


class LogsExtractorCache(TypedDict):
    """Cache dictionary for BigQuery query logs extraction."""

    query_info: pd.DataFrame | None
    table_info: pd.DataFrame | None
    column_info: pd.DataFrame | None
    column_references_info: pd.DataFrame | None
    cte_info: pd.DataFrame | None
