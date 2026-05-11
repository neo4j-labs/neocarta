"""Models for query log extraction."""

from typing import TypedDict

import pandas as pd


class QueryLogExtractorCache(TypedDict):
    """Cache dictionary used to store extracted query log information."""

    database_info: pd.DataFrame | None
    schema_info: pd.DataFrame | None
    table_info: pd.DataFrame | None
    column_info: pd.DataFrame | None
    column_references_info: pd.DataFrame | None
    query_info: pd.DataFrame | None
    cte_info: pd.DataFrame | None
