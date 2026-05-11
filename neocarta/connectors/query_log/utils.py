"""Utility functions for parsing and processing query log data."""

import json
from pathlib import Path

import pandas as pd
import sqlglot
from sqlglot.expressions import CTE, Column, Join, Table

from neocarta.connectors.utils.generate_id import (
    create_query_id,
    generate_column_id,
    generate_cte_id,
    generate_schema_id,
    generate_table_id,
)


def parse_bigquery_query_log_json(query_log_file: str) -> pd.DataFrame:
    """Parse a BigQuery query log JSON file into a Pandas DataFrame."""
    with Path(query_log_file).open() as f:
        data = json.load(f)

    query_metadata = []
    table_ids: set[str] = set()

    for item in data:
        if "jobQueryRequest" not in item["protoPayload"]["serviceData"]:
            continue

        base = item["protoPayload"]["serviceData"]
        project_id = base["jobQueryRequest"]["projectId"]
        query = base["jobQueryRequest"]["query"]
        ref_tables = base["jobQueryResponse"]["job"]["jobStatistics"]["referencedTables"]

        query_metadata.append(
            {
                "project_id": project_id,
                "query": query,
                "query_id": create_query_id(query),
            }
        )
        # format as table id
        for ref_table in ref_tables:
            table_ids.add(
                generate_table_id(project_id, ref_table["datasetId"], ref_table["tableId"])
            )

    ref_tables_metadata = []
    for tid in table_ids:
        parts = tid.split(".")
        project_id = parts[0]
        dataset_id = parts[1]
        table_id = parts[2]
        ref_tables_metadata.append(
            {
                "project_id": project_id,
                "dataset_id": dataset_id,
                "table_id": table_id,
            }
        )
    return {
        "query_info": pd.DataFrame(query_metadata),
        "table_info": pd.DataFrame(ref_tables_metadata),
    }


def parse_sql_query(
    query: str,
    query_id: str,
    read: str = "bigquery",
    default_project_id: str | None = None,
    default_schema_id: str | None = None,
) -> dict[str, list[dict]]:
    """
    Parse a SQL query into a Pandas DataFrame.

    Parameters
    ----------
    query: str
        The SQL query to parse.
    query_id: str
        The id of the query.
    read: str
        The dialect of the query.
    default_project_id: str
        The default project ID to use when table references don't include a catalog/project.
    default_schema_id: str
        The default schema/dataset ID to use when table references don't include a database/schema.

    Returns:
    -------
    dict[str, list[dict]]
        A dictionary with the query information.
        - table_info: A list of dictionaries with the table information.
        - column_info: A list of dictionaries with the column information.
        - references_info: A list of dictionaries with the references information.
    """
    # Database node properties
    platform = None
    service = None

    match read:
        case "bigquery":
            platform = "GCP"
            service = "BIGQUERY"
        case _:
            raise ValueError(f"Unsupported read argument: {read}")

    try:
        parsed = sqlglot.parse_one(query, read=read)
        column_info = []
        references_info = []
        alias_to_table_name = {}
        alias_to_table_id = {}
        table_name_to_id = {}
        table_name_to_alias = {}

        table_info = []

        table_ids = set()

        # CTE aliases must not be treated as real tables — sqlglot's `find_all(Table)`
        # returns both physical tables and CTE references with the same node type.
        cte_info = []
        cte_aliases: set[str] = set()
        for cte in parsed.find_all(CTE):
            if not cte.alias:
                continue
            cte_aliases.add(cte.alias)
            # `cte.this` is the inner SELECT; render it back to SQL for storage.
            definition = cte.this.sql(dialect=read) if cte.this is not None else ""
            cte_info.append(
                {
                    "cte_id": generate_cte_id(query_id, cte.alias),
                    "cte_name": cte.alias,
                    "definition": definition,
                    "query_id": query_id,
                }
            )

        # Table information and defining aliases
        for t in parsed.find_all(Table):
            table = t.this
            table_name = table.name
            table_alias = t.alias

            # Skip CTE references — they are query-local aliases, not catalog tables.
            if table_name in cte_aliases:
                continue

            # Skip BigQuery pseudo/metadata tables (e.g. `__TABLES__`, `__TABLES_SUMMARY__`).
            if table_name.startswith("__") and table_name.endswith("__"):
                continue

            # Use the catalog/project and database/dataset from the table reference, or fall back to defaults
            project_id = t.catalog or default_project_id
            dataset_name = t.db or default_schema_id

            # Validate required identifiers
            if not project_id or project_id == "":
                raise ValueError(
                    f"Cannot generate table ID for '{table_name}': missing project_id. Provide `default_project_id` or use fully qualified table names in query."
                )
            if not dataset_name or dataset_name == "":
                raise ValueError(
                    f"Cannot generate table ID for '{table_name}': missing schema/dataset. Provide `default_schema_id` or use fully qualified table names in query."
                )

            # Build table_id and dataset_id using standardized ID generation functions
            table_id = generate_table_id(project_id, dataset_name, table_name)
            dataset_id = generate_schema_id(project_id, dataset_name)

            table_name_to_id[table_name] = table_id
            table_name_to_alias[table_name] = table_alias

            if table_alias:
                alias_to_table_name[table_alias] = table_name
                alias_to_table_id[table_alias] = table_id

            table_ids.add(table_id)
            table_info.append(
                {
                    "platform": platform,
                    "service": service,
                    "table_id": table_id,
                    "table_name": table_name,
                    "dataset_id": dataset_id,
                    "dataset_name": dataset_name,
                    "project_name": project_id,
                    "project_id": project_id,
                    "table_alias": table_alias,
                    "query_id": query_id,
                }
            )

        # Column information
        for c in parsed.find_all(Column):
            table_name = c.table if c.table != "" else None
            table_alias = c.alias if c.alias != "" else table_name
            table_id = table_name_to_id.get(table_name) or alias_to_table_id.get(table_alias)

            # if we can't identify the table a column belongs to, we skip it
            if table_id is None:
                print(f"Unable to resolve table for column {c.name}. Skipping column.")
                continue

            column_name = c.name

            # Skip star projections (e.g. `t.*`) — sqlglot models these as a Column
            # whose name is "*", but they are projection wildcards, not catalog columns.
            if column_name == "*" or not column_name:
                continue

            db, schema, tbl = table_id.split(".")
            column_info.append(
                {
                    "table_alias": table_alias,
                    "table_name": table_name,
                    "column_name": column_name,
                    "table_id": table_id,
                    "column_id": generate_column_id(db, schema, tbl, column_name),
                    "query_id": query_id,
                }
            )

        # Join information
        for j in parsed.find_all(Join):
            left_table = j.this
            left_table_name = left_table.name
            left_table_alias = left_table.alias
            left_table_id = table_name_to_id.get(left_table_name) or alias_to_table_id.get(
                left_table_alias
            )
            join_condition = j.args.get("on") if "on" in j.args else None

            if join_condition:
                right_table_alias = (
                    getattr(join_condition.this, "table", None)
                    if hasattr(join_condition, "this")
                    else None
                )
                right_table_name = alias_to_table_name.get(right_table_alias, right_table_alias)
                right_table_id = table_name_to_id.get(right_table_name) or alias_to_table_id.get(
                    right_table_alias
                )

            else:
                right_table_id = None
                right_table_name = None
                right_table_alias = None

            # Extract column information from join condition if available
            left_column_name = None
            left_column_id = None
            right_column_name = None
            right_column_id = None

            # if we don't know the table ids, we skip the join - impossible to resolve columns
            if not left_table_id or not right_table_id:
                continue

            if join_condition:
                # Try to extract left column (expression side)
                if hasattr(join_condition, "expression") and join_condition.expression:
                    left_column_name = getattr(join_condition.expression, "name", None)
                    if left_column_name and left_table_alias:
                        left_col = str(getattr(join_condition.expression, "this", left_column_name))
                        db, schema, tbl = left_table_id.split(".")
                        left_column_id = generate_column_id(db, schema, tbl, left_col)

                # Try to extract right column (this side)
                if hasattr(join_condition, "this") and join_condition.this:
                    right_column_name = getattr(join_condition.this, "name", None)
                    if right_column_name and right_table_alias:
                        right_col = str(getattr(join_condition.this, "this", right_column_name))
                        db, schema, tbl = right_table_id.split(".")
                        right_column_id = generate_column_id(db, schema, tbl, right_col)

            to_add = {
                "left_table_name": left_table_name,
                "left_table_id": left_table_id,
                "left_table_alias": left_table_alias,
                "left_column_name": left_column_name,
                "left_column_id": left_column_id,
                "right_table_name": right_table_name,
                "right_table_id": right_table_id,
                "right_table_alias": right_table_alias,
                "right_column_name": right_column_name,
                "right_column_id": right_column_id,
                "criteria": str(join_condition) if join_condition else None,
            }

            # only add valid references. we know a reference is valid if both left and right column ids are known
            if (
                to_add.get("left_column_id") is not None
                and to_add.get("right_column_id") is not None
                # Skip self-references — a column joining itself is a parser artifact,
                # not a real foreign-key relationship.
                and to_add["left_column_id"] != to_add["right_column_id"]
            ):
                references_info.append(to_add)

        return {
            "table_info": table_info,
            "column_info": column_info,
            "references_info": references_info,
            "cte_info": cte_info,
        }
    except Exception as e:
        print(f"Error parsing SQL query: {e}")
        # sometimes it doesn't work
        return None
