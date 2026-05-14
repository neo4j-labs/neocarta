"""TypedDict models for the Salesforce connector cache."""

from typing import Any, TypedDict

import pandas as pd


class SalesforceObjectDict(TypedDict, total=False):
    """Shape of a Salesforce sobject describe response."""

    name: str
    label: str
    labelPlural: str
    keyPrefix: str | None
    custom: bool
    queryable: bool
    createable: bool
    updateable: bool
    deletable: bool
    fields: list[dict[str, Any]]


class SalesforceExtractorCache(TypedDict, total=False):
    """In-memory cache for DataFrames produced by SalesforceExtractor."""

    # Standard neocarta DataFrames (consumed by CSVTransformer)
    database_info: pd.DataFrame
    schema_info: pd.DataFrame
    table_info: pd.DataFrame
    column_info: pd.DataFrame
    column_references_info: pd.DataFrame

    # Salesforce-specific extras (consumed directly by SalesforceConnector)
    table_sfdc_props: pd.DataFrame
    column_sfdc_props: pd.DataFrame
