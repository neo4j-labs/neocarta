"""Salesforce Extractor: converts sobject describe dicts into neocarta DataFrames."""

import re
from pathlib import Path
from typing import Any

import pandas as pd

from ...connectors.utils.generate_id import (
    generate_column_id,
    generate_database_id,
    generate_schema_id,
    generate_table_id,
)
from .models import SalesforceExtractorCache, SalesforceObjectDict

# A valid namespace prefix is an alphanumeric token (no underscores) followed
# by double-underscore. Objects like CPP_CC_Entry__c have an underscore in the
# "prefix" so they don't match and fall through to "custom".
_NAMESPACE_PREFIX = re.compile(r"^([A-Za-z][A-Za-z0-9]*)__")


def _get_namespace(name: str, is_custom: bool) -> str:
    """Derive a neocarta schema name from a Salesforce object name.

    Standard objects (Account, Contact, …)         → "core"
    Managed-package objects (NS__Widget__c, …)      → lowercase namespace prefix
    Unmanaged custom objects (My_Widget__c, …)      → "custom"
    """
    if not is_custom:
        return "core"
    m = _NAMESPACE_PREFIX.match(name)
    if m and name.count("__") >= 2:
        return m.group(1).lower()
    return "custom"


def _normalize(s: str) -> str:
    """Lowercase and replace spaces/hyphens with underscores (mirrors generate_*_id)."""
    return s.lower().replace(" ", "_").replace("-", "_")


class SalesforceExtractor:
    """
    Extractor that converts Salesforce sobject describe dicts into neocarta DataFrames.

    Input
    -----
    objects : list[SalesforceObjectDict]
        Raw output from ``sf sobject describe`` (or the equivalent REST API
        ``/services/data/vXX/sobjects/{SObject}/describe``).  Each dict must
        contain at minimum ``name``, ``label``, ``custom``, and ``fields``.
    org_name : str
        Logical name for this Salesforce org — becomes the neocarta Database name.
    output_dir : Path | None
        When provided, each extracted DataFrame is written as a CSV file to this
        directory (mirrors the CSV connector's on-disk format for inspectability).
    """

    def __init__(
        self,
        objects: list[SalesforceObjectDict],
        org_name: str,
        output_dir: Path | None = None,
    ) -> None:
        """Initialise the extractor with a list of sobject describe dicts."""
        self.objects = objects
        self.org_name = org_name
        self.output_dir = output_dir
        self._cache: SalesforceExtractorCache = SalesforceExtractorCache()

        # Pre-build a lookup: normalized object name → namespace, for reference resolution.
        self._obj_namespace: dict[str, str] = {
            _normalize(o["name"]): _get_namespace(o["name"], o.get("custom", False))
            for o in objects
        }

    # ------------------------------------------------------------------
    # Cache properties
    # ------------------------------------------------------------------

    @property
    def database_info(self) -> pd.DataFrame:
        """Extracted database info DataFrame."""
        return self._cache.get("database_info", pd.DataFrame())

    @property
    def schema_info(self) -> pd.DataFrame:
        """Extracted schema info DataFrame."""
        return self._cache.get("schema_info", pd.DataFrame())

    @property
    def table_info(self) -> pd.DataFrame:
        """Extracted table info DataFrame."""
        return self._cache.get("table_info", pd.DataFrame())

    @property
    def column_info(self) -> pd.DataFrame:
        """Extracted column info DataFrame."""
        return self._cache.get("column_info", pd.DataFrame())

    @property
    def column_references_info(self) -> pd.DataFrame:
        """Extracted column references DataFrame."""
        return self._cache.get("column_references_info", pd.DataFrame())

    @property
    def table_sfdc_props(self) -> pd.DataFrame:
        """Salesforce-specific Table extra properties DataFrame."""
        return self._cache.get("table_sfdc_props", pd.DataFrame())

    @property
    def column_sfdc_props(self) -> pd.DataFrame:
        """Salesforce-specific Column extra properties DataFrame."""
        return self._cache.get("column_sfdc_props", pd.DataFrame())

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_target(self, ref_to_name: str) -> tuple[str, str, str]:
        """Return (database_name, schema_name, table_name) for a referenceTo target.

        Falls back to (org_name, "system", ref_to_name) for objects not in the
        described set (RecordType, Profile, Group, …).
        """
        norm = _normalize(ref_to_name)
        ns = self._obj_namespace.get(norm, "system")
        return self.org_name, ns, _normalize(ref_to_name)

    def _write_csv(self, df: pd.DataFrame, filename: str) -> None:
        if self.output_dir is None:
            return
        self.output_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(self.output_dir / filename, index=False)

    # ------------------------------------------------------------------
    # Extract methods
    # ------------------------------------------------------------------

    def extract_database_info(self) -> pd.DataFrame:
        """Build the single-row database info DataFrame for the org."""
        df = pd.DataFrame(
            [
                {
                    "database_name": self.org_name,
                    "platform": "Salesforce",
                    "service": "Salesforce CRM",
                    "description": f"Salesforce org: {self.org_name}",
                    "database_id": generate_database_id(self.org_name),
                }
            ]
        )
        self._cache["database_info"] = df
        self._write_csv(df, "database_info.csv")
        print(f"  Extracted 1 database row ({self.org_name})")
        return df

    def extract_schema_info(self) -> pd.DataFrame:
        """Build the schema info DataFrame (one row per unique namespace)."""
        seen: dict[str, str] = {}
        for obj in self.objects:
            ns = _get_namespace(obj["name"], obj.get("custom", False))
            if ns not in seen:
                seen[ns] = f"Salesforce namespace: {ns}"

        rows = []
        for ns, desc in seen.items():
            rows.append(
                {
                    "database_name": self.org_name,
                    "schema_name": ns,
                    "description": desc,
                    "database_id": generate_database_id(self.org_name),
                    "schema_id": generate_schema_id(self.org_name, ns),
                }
            )

        df = pd.DataFrame(rows)
        self._cache["schema_info"] = df
        self._write_csv(df, "schema_info.csv")
        print(f"  Extracted {len(df)} schema rows")
        return df

    def extract_table_info(self) -> pd.DataFrame:
        """Build table info and SFDC-extra DataFrames (one row per object)."""
        table_rows: list[dict[str, Any]] = []
        sfdc_rows: list[dict[str, Any]] = []

        for obj in self.objects:
            name = _normalize(obj["name"])
            ns = _get_namespace(obj["name"], obj.get("custom", False))
            table_id = generate_table_id(self.org_name, ns, name)

            # Combine label + admin description for richer embeddings.
            # Label alone is used when no description exists (the common case).
            _t_label = obj.get("label", "")
            _t_desc = obj.get("description", "")
            table_desc = (
                f"{_t_label} — {_t_desc}" if _t_label and _t_desc else (_t_label or _t_desc or None)
            )
            table_rows.append(
                {
                    "database_name": self.org_name,
                    "schema_name": ns,
                    "table_name": name,
                    "description": table_desc,
                    "schema_id": generate_schema_id(self.org_name, ns),
                    "table_id": table_id,
                }
            )
            sfdc_rows.append(
                {
                    "id": table_id,
                    "label": obj.get("label", obj["name"]),
                    "labelPlural": obj.get("labelPlural", ""),
                    "keyPrefix": obj.get("keyPrefix"),
                    "namespace": ns,
                    "isCustom": obj.get("custom", False),
                    "isQueryable": obj.get("queryable", True),
                    "isCreateable": obj.get("createable", True),
                    "isUpdateable": obj.get("updateable", True),
                    "isDeletable": obj.get("deletable", True),
                }
            )

        df = pd.DataFrame(table_rows)
        sfdc_df = pd.DataFrame(sfdc_rows)
        self._cache["table_info"] = df
        self._cache["table_sfdc_props"] = sfdc_df
        self._write_csv(df, "table_info.csv")
        print(f"  Extracted {len(df)} table rows")
        return df

    def extract_column_info(self) -> pd.DataFrame:
        """Build column info and SFDC-extra DataFrames (one row per field)."""
        column_rows: list[dict[str, Any]] = []
        sfdc_rows: list[dict[str, Any]] = []

        for obj in self.objects:
            obj_name = _normalize(obj["name"])
            ns = _get_namespace(obj["name"], obj.get("custom", False))

            for field in obj.get("fields", []):
                col_name = _normalize(field["name"])
                column_id = generate_column_id(self.org_name, ns, obj_name, col_name)

                is_pk = field.get("type") == "id"
                is_fk = field.get("type") == "reference"
                picklist = [
                    v["value"] for v in field.get("picklistValues", []) if v.get("active", True)
                ]

                # Combine label + admin description for richer embeddings.
                _c_label = field.get("label", "")
                _c_desc = field.get("description", "")
                col_desc = (
                    f"{_c_label} — {_c_desc}"
                    if _c_label and _c_desc
                    else (_c_label or _c_desc or None)
                )
                column_rows.append(
                    {
                        "database_name": self.org_name,
                        "schema_name": ns,
                        "table_name": obj_name,
                        "column_name": col_name,
                        "data_type": field.get("type"),
                        "is_nullable": field.get("nillable", True),
                        "is_primary_key": is_pk,
                        "is_foreign_key": is_fk,
                        "description": col_desc,
                        "table_id": generate_table_id(self.org_name, ns, obj_name),
                        "column_id": column_id,
                    }
                )
                sfdc_rows.append(
                    {
                        "id": column_id,
                        "label": field.get("label", field["name"]),
                        "length": field.get("length"),
                        "precision": field.get("precision"),
                        "scale": field.get("scale"),
                        "isUnique": field.get("unique", False),
                        "picklistValues": picklist or None,
                    }
                )

        df = pd.DataFrame(column_rows)
        sfdc_df = pd.DataFrame(sfdc_rows)
        self._cache["column_info"] = df
        self._cache["column_sfdc_props"] = sfdc_df
        self._write_csv(df, "column_info.csv")
        print(f"  Extracted {len(df)} column rows")
        return df

    def extract_column_references_info(self) -> pd.DataFrame:
        """Build the column references DataFrame from all reference-type fields."""
        rows: list[dict[str, Any]] = []

        for obj in self.objects:
            obj_name = _normalize(obj["name"])
            src_ns = _get_namespace(obj["name"], obj.get("custom", False))

            for field in obj.get("fields", []):
                if field.get("type") != "reference":
                    continue
                ref_targets = field.get("referenceTo", [])
                if not ref_targets:
                    continue

                src_col = _normalize(field["name"])
                for target_obj in ref_targets:
                    tgt_db, tgt_ns, tgt_table = self._resolve_target(target_obj)

                    rows.append(
                        {
                            "source_database_name": self.org_name,
                            "source_schema_name": src_ns,
                            "source_table_name": obj_name,
                            "source_column_name": src_col,
                            "target_database_name": tgt_db,
                            "target_schema_name": tgt_ns,
                            "target_table_name": tgt_table,
                            "target_column_name": "id",
                            "criteria": f"{obj_name}.{src_col} → {target_obj}.Id",
                            "source_column_id": generate_column_id(
                                self.org_name, src_ns, obj_name, src_col
                            ),
                            "target_column_id": generate_column_id(tgt_db, tgt_ns, tgt_table, "id"),
                        }
                    )

        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(
                columns=[
                    "source_database_name",
                    "source_schema_name",
                    "source_table_name",
                    "source_column_name",
                    "target_database_name",
                    "target_schema_name",
                    "target_table_name",
                    "target_column_name",
                    "criteria",
                    "source_column_id",
                    "target_column_id",
                ]
            )
        )
        self._cache["column_references_info"] = df
        self._write_csv(df, "column_references_info.csv")
        print(f"  Extracted {len(df)} reference rows")
        return df

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def extract_all(self) -> None:
        """Run all extraction steps and populate the cache."""
        print(
            f"Extracting Salesforce schema for org: {self.org_name} ({len(self.objects)} objects)..."
        )
        self.extract_database_info()
        self.extract_schema_info()
        self.extract_table_info()
        self.extract_column_info()
        self.extract_column_references_info()
