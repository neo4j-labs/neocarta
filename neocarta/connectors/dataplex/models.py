"""Models for Dataplex metadata extraction."""

from typing import TypedDict

from pydantic import Field


class BigQueryMetadataInfoResponse(TypedDict):
    """Row returned by the Dataplex BigQuery metadata extraction query."""

    project_id: str = Field(..., description="The project ID")
    project_number: str = Field(..., description="The project number")
    dataset_id: str = Field(..., description="The dataset ID")
    table_id: str = Field(..., description="The table ID")
    table_display_name: str = Field(..., description="The table display name")
    table_description: str = Field(..., description="The table description")
    column_name: str = Field(..., description="The column name")
    column_data_type: str = Field(..., description="The column data type")
    column_metadata_type: str = Field(..., description="The column data metadata type")
    column_mode: str = Field(..., description="Whether column is nullable")
    column_description: str = Field(..., description="The column description")
    service: str = Field(..., description="The service")
    platform: str = Field(..., description="The platform")
    location: str = Field(..., description="The location")
    resource_name: str = Field(..., description="The resource name")
    fully_qualified_name: str = Field(..., description="The fully qualified name")
    parent_entry: str = Field(..., description="The parent entry")
    entry_type: str = Field(..., description="The entry type")


class GlossaryInfoResponse(TypedDict):
    """Row returned by the Dataplex glossary term extraction query."""

    term_id: str = Field(..., description="The term ID")
    term_name: str = Field(..., description="The term name")
    term_description: str = Field(..., description="The term description")
    glossary_id: str = Field(..., description="The glossary ID")
    glossary_name: str = Field(..., description="The glossary name")
    term_parent: str = Field(..., description="The term parent")
    category_id: str = Field(..., description="The category ID")


class EntryLinkInfoResponse(TypedDict):
    """Row returned by the Dataplex entry link extraction."""

    entity_id: str = Field(
        ..., description="Neo4j node id: project_id.dataset_id.table_id[.column_name]"
    )
    entity_type: str = Field(..., description="'COLUMN' or 'TABLE'")
    term_id: str = Field(
        ..., description="Neo4j BusinessTerm node id: full term resource name from the SDK"
    )
