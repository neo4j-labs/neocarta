"""CSV Extractor for reading and validating CSV files into a cache."""

from pathlib import Path
from typing import ClassVar

import pandas as pd

from ...enums import NodeLabel, RelationshipType
from ..utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_column_id,
    generate_database_id,
    generate_glossary_id,
    generate_schema_id,
    generate_table_id,
    generate_value_id,
)
from .models import CSVExtractorCache

# Required columns per entity type
REQUIRED_COLUMNS: dict[str, list[str]] = {
    NodeLabel.DATABASE: ["database_name"],
    NodeLabel.SCHEMA: ["database_name", "schema_name"],
    NodeLabel.TABLE: ["database_name", "schema_name", "table_name"],
    NodeLabel.COLUMN: ["database_name", "schema_name", "table_name", "column_name"],
    RelationshipType.REFERENCES: [
        "source_database_name",
        "source_schema_name",
        "source_table_name",
        "source_column_name",
        "target_database_name",
        "target_schema_name",
        "target_table_name",
        "target_column_name",
    ],
    NodeLabel.VALUE: ["database_name", "schema_name", "table_name", "column_name", "value"],
    NodeLabel.QUERY: ["query_id", "content"],
    RelationshipType.USES_TABLE: ["query_id", "table_id"],
    RelationshipType.USES_COLUMN: ["query_id", "column_id"],
    NodeLabel.GLOSSARY: ["glossary_name"],
    NodeLabel.CATEGORY: ["glossary_name", "category_name"],
    NodeLabel.BUSINESS_TERM: ["glossary_name", "category_name", "term_name"],
    "column_tagged_with": [
        "database_name",
        "schema_name",
        "table_name",
        "column_name",
        "glossary_name",
        "category_name",
        "term_name",
    ],
    "table_tagged_with": [
        "database_name",
        "schema_name",
        "table_name",
        "glossary_name",
        "category_name",
        "term_name",
    ],
}


# Maps node/relationship type names (as passed by callers) to the internal
# entity keys used by _extract() and csv_file_map. Defined at module level so
# they are shared between extract_all() and any validation logic.
NODE_ENTITIES: dict[NodeLabel, str] = {
    NodeLabel.DATABASE: "database",
    NodeLabel.SCHEMA: "schema",
    NodeLabel.TABLE: "table",
    NodeLabel.COLUMN: "column",
    NodeLabel.VALUE: "value",
    NodeLabel.QUERY: "query",
    NodeLabel.GLOSSARY: "glossary",
    NodeLabel.CATEGORY: "category",
    NodeLabel.BUSINESS_TERM: "business_term",
}

# Relationships that share a CSV with their parent node entity reuse that entity
# key (e.g. has_schema is built from schema_info.csv). Cross-entity relationship
# CSVs (column_references, query_table, query_column) have their own keys.
REL_ENTITIES: dict[RelationshipType, str] = {
    RelationshipType.HAS_SCHEMA: "schema",
    RelationshipType.HAS_TABLE: "table",
    RelationshipType.HAS_COLUMN: "column",
    RelationshipType.HAS_VALUE: "value",
    RelationshipType.HAS_CATEGORY: "category",
    RelationshipType.HAS_BUSINESS_TERM: "business_term",
    RelationshipType.REFERENCES: "column_references",
    RelationshipType.TAGGED_WITH: "tagged_with",
    RelationshipType.USES_TABLE: "query_table",
    RelationshipType.USES_COLUMN: "query_column",
}


class CSVExtractor:
    """
    Extractor for reading CSV files from a directory and caching their contents.

    Reads each CSV file, validates that required columns are present,
    and stores the resulting DataFrames in an internal cache. After loading,
    each DataFrame is augmented with resolved ``*_id`` columns used for node
    identity and relationship foreign keys.

    **ID strategy — choose one, apply consistently across all files:**

    *Auto-generated (recommended)*
      Omit all ``*_id`` columns. IDs are derived from the name columns using a
      deterministic dot-separated hierarchy::

          database_id = database_name
          schema_id = database_name.schema_name
          table_id = database_name.schema_name.table_name
          column_id = database_name.schema_name.table_name.column_name

    *Explicit*
      Supply every ``*_id`` column (``database_id``, ``schema_id``,
      ``table_id``, ``column_id``, ``value_id``) in **every** CSV file in the
      hierarchy. Explicit IDs are used as-is and must be consistent across
      files — e.g. the ``database_id`` value in ``schema_info.csv`` must match
      the ``database_id`` in ``database_info.csv``.

    Mixing explicit and auto-generated IDs across files in the same hierarchy
    is not supported and will produce inconsistent node references.
    """

    DEFAULT_FILE_MAP: ClassVar[dict[str, str]] = {
        NodeLabel.DATABASE: "database_info.csv",
        NodeLabel.SCHEMA: "schema_info.csv",
        NodeLabel.TABLE: "table_info.csv",
        NodeLabel.COLUMN: "column_info.csv",
        NodeLabel.VALUE: "value_info.csv",
        NodeLabel.QUERY: "query_info.csv",
        RelationshipType.USES_TABLE: "query_table_info.csv",
        RelationshipType.USES_COLUMN: "query_column_info.csv",
        NodeLabel.GLOSSARY: "glossary_info.csv",
        NodeLabel.CATEGORY: "category_info.csv",
        NodeLabel.BUSINESS_TERM: "business_term_info.csv",
        RelationshipType.REFERENCES: "column_references_info.csv",
        "column_tagged_with": "column_term_info.csv",
        "table_tagged_with": "table_term_info.csv",
    }

    def __init__(
        self,
        csv_directory: str,
        csv_file_map: dict[str, str] | None = None,
    ) -> None:
        """
        Initialize the CSV extractor.

        Parameters
        ----------
        csv_directory : str
            Path to the directory containing CSV files.
        csv_file_map : dict[str, str], optional
            Custom mapping of entity keys to CSV filenames.
            Merges with DEFAULT_FILE_MAP, allowing partial overrides.
        """
        self.csv_directory = Path(csv_directory)
        if not self.csv_directory.exists():
            raise ValueError(f"csv_directory does not exist: {self.csv_directory}")
        if not self.csv_directory.is_dir():
            raise ValueError(f"csv_directory is not a directory: {self.csv_directory}")

        self.csv_file_map = self.DEFAULT_FILE_MAP.copy()
        if csv_file_map:
            self.csv_file_map.update(csv_file_map)

        self._cache: CSVExtractorCache = CSVExtractorCache()

    # ------------------------------------------------------------------
    # Cache properties
    # ------------------------------------------------------------------

    @property
    def database_info(self) -> pd.DataFrame:
        """Return cached database info DataFrame."""
        return self._cache.get("database_info", pd.DataFrame())

    @property
    def schema_info(self) -> pd.DataFrame:
        """Return cached schema info DataFrame."""
        return self._cache.get("schema_info", pd.DataFrame())

    @property
    def table_info(self) -> pd.DataFrame:
        """Return cached table info DataFrame."""
        return self._cache.get("table_info", pd.DataFrame())

    @property
    def column_info(self) -> pd.DataFrame:
        """Return cached column info DataFrame."""
        return self._cache.get("column_info", pd.DataFrame())

    @property
    def column_references_info(self) -> pd.DataFrame:
        """Return cached column references info DataFrame."""
        return self._cache.get("column_references_info", pd.DataFrame())

    @property
    def value_info(self) -> pd.DataFrame:
        """Return cached value info DataFrame."""
        return self._cache.get("value_info", pd.DataFrame())

    @property
    def query_info(self) -> pd.DataFrame:
        """Return cached query info DataFrame."""
        return self._cache.get("query_info", pd.DataFrame())

    @property
    def query_table_info(self) -> pd.DataFrame:
        """Return cached query-to-table mapping DataFrame."""
        return self._cache.get("query_table_info", pd.DataFrame())

    @property
    def query_column_info(self) -> pd.DataFrame:
        """Return cached query-to-column mapping DataFrame."""
        return self._cache.get("query_column_info", pd.DataFrame())

    @property
    def glossary_info(self) -> pd.DataFrame:
        """Return cached glossary info DataFrame."""
        return self._cache.get("glossary_info", pd.DataFrame())

    @property
    def category_info(self) -> pd.DataFrame:
        """Return cached category info DataFrame."""
        return self._cache.get("category_info", pd.DataFrame())

    @property
    def business_term_info(self) -> pd.DataFrame:
        """Return cached business term info DataFrame."""
        return self._cache.get("business_term_info", pd.DataFrame())

    @property
    def column_tagged_with_info(self) -> pd.DataFrame:
        """Return cached (:Column)-[:TAGGED_WITH]->(:BusinessTerm) DataFrame."""
        return self._cache.get("column_tagged_with_info", pd.DataFrame())

    @property
    def table_tagged_with_info(self) -> pd.DataFrame:
        """Return cached (:Table)-[:TAGGED_WITH]->(:BusinessTerm) DataFrame."""
        return self._cache.get("table_tagged_with_info", pd.DataFrame())

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_csv(self, filename: str) -> pd.DataFrame | None:
        """Read a CSV file if it exists, returning None otherwise."""
        filepath = self.csv_directory / filename
        if not filepath.exists():
            return None
        df = pd.read_csv(filepath)
        # pandas already converts "NaN", "NULL", "null" to float NaN via its
        # default na_values. Convert remaining NaN to Python None so downstream
        # code receives None rather than float('nan').
        return df.where(df.notna(), None)

    def _validate_columns(self, df: pd.DataFrame, entity_key: str, filename: str) -> None:
        """
        Raise ValueError if any required columns are missing from df.

        Parameters
        ----------
        df : pd.DataFrame
            The DataFrame to validate.
        entity_key : str
            Key into REQUIRED_COLUMNS (e.g. "schema", "column").
        filename : str
            CSV filename, used only for the error message.
        """
        required = REQUIRED_COLUMNS.get(entity_key, [])
        missing = [col for col in required if col not in df.columns]
        if missing:
            raise ValueError(
                f"{filename} is missing required columns: {missing}. "
                f"Required columns for '{entity_key}': {required}"
            )

    def _extract(self, entity_key: str, cache_key: str) -> pd.DataFrame | None:
        """
        Read, validate, and cache a single CSV file.

        Parameters
        ----------
        entity_key : str
            Key into csv_file_map and REQUIRED_COLUMNS.
        cache_key : str
            Key used to store the DataFrame in the cache.

        Returns:
        -------
        pd.DataFrame or None
            The loaded DataFrame, or None if the file does not exist.
        """
        filename = self.csv_file_map[entity_key]
        df = self._read_csv(filename)
        if df is None:
            print(f"  Skipping {filename} (file not found)")
            return None
        if df.empty:
            print(f"  Skipping {filename} (file is empty)")
            return None

        self._validate_columns(df, entity_key, filename)
        self._cache[cache_key] = df
        print(f"  Extracted {len(df)} rows from {filename}")
        return df

    # ------------------------------------------------------------------
    # Public extract methods
    # ------------------------------------------------------------------

    def extract_database_info(self) -> pd.DataFrame | None:
        """Extract and cache database info from CSV."""
        df = self._extract(NodeLabel.DATABASE, "database_info")
        if df is None:
            return None
        if "database_id" not in df.columns:
            df["database_id"] = df["database_name"].apply(generate_database_id)
        self._cache["database_info"] = df
        return df

    def extract_schema_info(self) -> pd.DataFrame | None:
        """Extract and cache schema info from CSV."""
        df = self._extract(NodeLabel.SCHEMA, "schema_info")
        if df is None:
            return None
        if "database_id" not in df.columns:
            df["database_id"] = df["database_name"].apply(generate_database_id)
        if "schema_id" not in df.columns:
            df["schema_id"] = df.apply(
                lambda r: generate_schema_id(r["database_name"], r["schema_name"]), axis=1
            )
        self._cache["schema_info"] = df
        return df

    def extract_table_info(self) -> pd.DataFrame | None:
        """Extract and cache table info from CSV."""
        df = self._extract(NodeLabel.TABLE, "table_info")
        if df is None:
            return None
        if "schema_id" not in df.columns:
            df["schema_id"] = df.apply(
                lambda r: generate_schema_id(r["database_name"], r["schema_name"]), axis=1
            )
        if "table_id" not in df.columns:
            df["table_id"] = df.apply(
                lambda r: generate_table_id(r["database_name"], r["schema_name"], r["table_name"]),
                axis=1,
            )
        self._cache["table_info"] = df
        return df

    def extract_column_info(self) -> pd.DataFrame | None:
        """Extract and cache column info from CSV."""
        df = self._extract(NodeLabel.COLUMN, "column_info")
        if df is None:
            return None
        if "table_id" not in df.columns:
            df["table_id"] = df.apply(
                lambda r: generate_table_id(r["database_name"], r["schema_name"], r["table_name"]),
                axis=1,
            )
        if "column_id" not in df.columns:
            df["column_id"] = df.apply(
                lambda r: generate_column_id(
                    r["database_name"], r["schema_name"], r["table_name"], r["column_name"]
                ),
                axis=1,
            )
        self._cache["column_info"] = df
        return df

    def extract_column_references_info(self) -> pd.DataFrame | None:
        """Extract and cache column references info from CSV."""
        df = self._extract(RelationshipType.REFERENCES, "column_references_info")
        if df is None:
            return None
        if "source_column_id" not in df.columns:
            df["source_column_id"] = df.apply(
                lambda r: generate_column_id(
                    r["source_database_name"],
                    r["source_schema_name"],
                    r["source_table_name"],
                    r["source_column_name"],
                ),
                axis=1,
            )
        if "target_column_id" not in df.columns:
            df["target_column_id"] = df.apply(
                lambda r: generate_column_id(
                    r["target_database_name"],
                    r["target_schema_name"],
                    r["target_table_name"],
                    r["target_column_name"],
                ),
                axis=1,
            )
        self._cache["column_references_info"] = df
        return df

    def extract_value_info(self) -> pd.DataFrame | None:
        """Extract and cache value info from CSV."""
        df = self._extract(NodeLabel.VALUE, "value_info")
        if df is None:
            return None
        if "column_id" not in df.columns:
            df["column_id"] = df.apply(
                lambda r: generate_column_id(
                    r["database_name"], r["schema_name"], r["table_name"], r["column_name"]
                ),
                axis=1,
            )
        if "value_id" not in df.columns:
            df["value_id"] = df.apply(
                lambda r: generate_value_id(
                    r["database_name"],
                    r["schema_name"],
                    r["table_name"],
                    r["column_name"],
                    r["value"],
                ),
                axis=1,
            )
        self._cache["value_info"] = df
        return df

    def extract_query_info(self) -> pd.DataFrame | None:
        """Extract and cache query info from CSV."""
        return self._extract(NodeLabel.QUERY, "query_info")

    def extract_query_table_info(self) -> pd.DataFrame | None:
        """Extract and cache query-to-table mapping from CSV."""
        return self._extract(RelationshipType.USES_TABLE, "query_table_info")

    def extract_query_column_info(self) -> pd.DataFrame | None:
        """Extract and cache query-to-column mapping from CSV."""
        return self._extract(RelationshipType.USES_COLUMN, "query_column_info")

    def extract_glossary_info(self) -> pd.DataFrame | None:
        """Extract and cache glossary info from CSV."""
        df = self._extract(NodeLabel.GLOSSARY, "glossary_info")
        if df is None:
            return None
        if "glossary_id" not in df.columns:
            df["glossary_id"] = df["glossary_name"].apply(generate_glossary_id)
        self._cache["glossary_info"] = df
        return df

    def extract_category_info(self) -> pd.DataFrame | None:
        """Extract and cache category info from CSV."""
        df = self._extract(NodeLabel.CATEGORY, "category_info")
        if df is None:
            return None
        if "glossary_id" not in df.columns:
            df["glossary_id"] = df["glossary_name"].apply(generate_glossary_id)
        if "category_id" not in df.columns:
            df["category_id"] = df.apply(
                lambda r: generate_category_id(r["glossary_name"], r["category_name"]), axis=1
            )
        self._cache["category_info"] = df
        return df

    def extract_business_term_info(self) -> pd.DataFrame | None:
        """Extract and cache business term info from CSV."""
        df = self._extract(NodeLabel.BUSINESS_TERM, "business_term_info")
        if df is None:
            return None
        if "category_id" not in df.columns:
            df["category_id"] = df.apply(
                lambda r: generate_category_id(r["glossary_name"], r["category_name"]), axis=1
            )
        if "business_term_id" not in df.columns:
            df["business_term_id"] = df.apply(
                lambda r: generate_business_term_id(
                    r["glossary_name"], r["category_name"], r["term_name"]
                ),
                axis=1,
            )
        self._cache["business_term_info"] = df
        return df

    def extract_column_tagged_with_info(self) -> pd.DataFrame | None:
        """Extract and cache (:Column)-[:TAGGED_WITH]->(:BusinessTerm) relationships from CSV."""
        filename = self.csv_file_map.get("column_tagged_with", "column_term_info.csv")
        df = self._read_csv(filename)
        if df is None:
            print(f"  Skipping {filename} (file not found)")
            return None
        if df.empty:
            print(f"  Skipping {filename} (file is empty)")
            return None
        self._validate_columns(df, "column_tagged_with", filename)
        if "column_id" not in df.columns:
            df["column_id"] = df.apply(
                lambda r: generate_column_id(
                    r["database_name"], r["schema_name"], r["table_name"], r["column_name"]
                ),
                axis=1,
            )
        if "business_term_id" not in df.columns:
            df["business_term_id"] = df.apply(
                lambda r: generate_business_term_id(
                    r["glossary_name"], r["category_name"], r["term_name"]
                ),
                axis=1,
            )
        self._cache["column_tagged_with_info"] = df
        print(f"  Extracted {len(df)} rows from {filename}")
        return df

    def extract_table_tagged_with_info(self) -> pd.DataFrame | None:
        """Extract and cache (:Table)-[:TAGGED_WITH]->(:BusinessTerm) relationships from CSV."""
        filename = self.csv_file_map.get("table_tagged_with", "table_term_info.csv")
        df = self._read_csv(filename)
        if df is None:
            print(f"  Skipping {filename} (file not found)")
            return None
        if df.empty:
            print(f"  Skipping {filename} (file is empty)")
            return None
        self._validate_columns(df, "table_tagged_with", filename)
        if "table_id" not in df.columns:
            df["table_id"] = df.apply(
                lambda r: generate_table_id(r["database_name"], r["schema_name"], r["table_name"]),
                axis=1,
            )
        if "business_term_id" not in df.columns:
            df["business_term_id"] = df.apply(
                lambda r: generate_business_term_id(
                    r["glossary_name"], r["category_name"], r["term_name"]
                ),
                axis=1,
            )
        self._cache["table_tagged_with_info"] = df
        print(f"  Extracted {len(df)} rows from {filename}")
        return df

    def extract_all(
        self,
        include_nodes: list[NodeLabel] | None = None,
        include_relationships: list[RelationshipType] | None = None,
    ) -> None:
        """
        Extract and validate CSV files, caching results.

        When include_nodes or include_relationships are provided, only the CSV
        files required to satisfy those requests are read. Otherwise all files
        are extracted.

        Parameters
        ----------
        include_nodes : list[NodeLabel], optional
            Node types to include. Allowed values are from the `NodeLabel` enum.
        include_relationships : list[RelationshipType], optional
            Relationship types to include. Allowed values are from the `RelationshipType` enum.
        """
        if include_nodes is not None:
            unknown = sorted(set(include_nodes) - NODE_ENTITIES.keys(), key=str)
            if unknown:
                valid = sorted(label.value for label in NODE_ENTITIES)
                raise ValueError(
                    f"Unknown node types: {[str(x) for x in unknown]}. Valid values: {valid}"
                )

        if include_relationships is not None:
            unknown = sorted(set(include_relationships) - REL_ENTITIES.keys(), key=str)
            if unknown:
                valid = sorted(rel.value for rel in REL_ENTITIES)
                raise ValueError(
                    f"Unknown relationship types: {[str(x) for x in unknown]}. "
                    f"Valid values: {valid}"
                )

        if include_nodes is None and include_relationships is None:
            needed: set[str] = set(NODE_ENTITIES.values()) | set(REL_ENTITIES.values())
        else:
            needed = set()
            for name in include_nodes or []:
                needed.add(NODE_ENTITIES[name])
            for name in include_relationships or []:
                needed.add(REL_ENTITIES[name])

        print(f"Extracting CSV files from {self.csv_directory}...")
        if "database" in needed:
            self.extract_database_info()
        if "schema" in needed:
            self.extract_schema_info()
        if "table" in needed:
            self.extract_table_info()
        if "column" in needed:
            self.extract_column_info()
        if "column_references" in needed:
            self.extract_column_references_info()
        if "value" in needed:
            self.extract_value_info()
        if "query" in needed:
            self.extract_query_info()
        if "query_table" in needed:
            self.extract_query_table_info()
        if "query_column" in needed:
            self.extract_query_column_info()
        if "glossary" in needed:
            self.extract_glossary_info()
        if "category" in needed:
            self.extract_category_info()
        if "business_term" in needed:
            self.extract_business_term_info()
        if "tagged_with" in needed:
            self.extract_column_tagged_with_info()
            self.extract_table_tagged_with_info()
