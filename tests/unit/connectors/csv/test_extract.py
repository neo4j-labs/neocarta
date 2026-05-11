import pytest

from neocarta.connectors.csv.extract import NODE_ENTITIES, REL_ENTITIES, CSVExtractor
from neocarta.connectors.utils.generate_id import (
    generate_business_term_id,
    generate_category_id,
    generate_column_id,
    generate_database_id,
    generate_glossary_id,
    generate_schema_id,
    generate_table_id,
    generate_value_id,
)
from neocarta.enums import NodeLabel, RelationshipType

# ---------------------------------------------------------------------------
# Fix #1 — csv_directory validation
# ---------------------------------------------------------------------------


class TestCsvDirectoryValidation:
    def test_nonexistent_directory_raises(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(ValueError, match="does not exist"):
            CSVExtractor(str(missing))

    def test_file_path_raises(self, tmp_path):
        f = tmp_path / "not_a_dir.csv"
        f.write_text("a,b\n1,2\n")
        with pytest.raises(ValueError, match="not a directory"):
            CSVExtractor(str(f))

    def test_valid_directory_does_not_raise(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        assert extractor.csv_directory == csv_dir

    def test_path_object_accepted(self, csv_dir):
        extractor = CSVExtractor(csv_dir)  # Path, not str
        assert extractor.csv_directory == csv_dir


# ---------------------------------------------------------------------------
# Fix #2 — include_nodes / include_relationships validation in extract_all
# ---------------------------------------------------------------------------


class TestIncludeValidation:
    def test_invalid_include_nodes_raises(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Unknown node types"):
            extractor.extract_all(include_nodes=["databse"])  # typo

    def test_invalid_include_relationships_raises(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Unknown relationship types"):
            extractor.extract_all(include_relationships=["has_schema_rel"])  # wrong name

    def test_multiple_invalid_include_nodes_raises(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Unknown node types"):
            extractor.extract_all(include_nodes=["foo", "bar", "database"])

    def test_multiple_invalid_include_relationships_raises(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Unknown relationship types"):
            extractor.extract_all(include_relationships=["foo", "has_schema"])

    def test_error_message_lists_invalid_values(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="typo_node"):
            extractor.extract_all(include_nodes=["typo_node"])

    def test_error_message_lists_valid_values(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Database"):
            extractor.extract_all(include_nodes=["bad"])

    def test_all_valid_node_types_accepted(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        extractor.extract_all(include_nodes=list(NODE_ENTITIES.keys()))
        # No error; missing files are silently skipped

    def test_all_valid_relationship_types_accepted(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        extractor.extract_all(include_relationships=list(REL_ENTITIES.keys()))

    def test_none_include_nodes_extracts_all(self, csv_dir):
        extractor = CSVExtractor(str(csv_dir))
        extractor.extract_all(include_nodes=None, include_relationships=None)
        # No error; empty dir simply produces no cached data

    def test_empty_include_nodes_list_extracts_nothing(self, csv_dir):
        """An empty list is valid but results in no files being read."""
        extractor = CSVExtractor(str(csv_dir))
        extractor.extract_all(include_nodes=[], include_relationships=[])
        assert extractor.database_info.empty
        assert extractor.schema_info.empty

    def test_selective_extract_only_reads_needed_files(self, csv_dir_with_files):
        """Requesting only NodeLabel.DATABASE does not populate other caches."""
        extractor = CSVExtractor(str(csv_dir_with_files))
        extractor.extract_all(include_nodes=[NodeLabel.DATABASE])
        assert not extractor.database_info.empty
        assert extractor.schema_info.empty  # not requested
        assert extractor.table_info.empty  # not requested

    def test_relationship_include_reads_shared_csv(self, csv_dir_with_files):
        """HAS_SCHEMA reuses schema_info.csv, so schema_info cache is populated."""
        extractor = CSVExtractor(str(csv_dir_with_files))
        extractor.extract_all(include_relationships=[RelationshipType.HAS_SCHEMA])
        assert not extractor.schema_info.empty

    def test_references_include_reads_column_references_csv(self, csv_dir_with_files):
        extractor = CSVExtractor(str(csv_dir_with_files))
        extractor.extract_all(include_relationships=[RelationshipType.REFERENCES])
        assert not extractor.column_references_info.empty
        assert extractor.schema_info.empty  # not requested


# ---------------------------------------------------------------------------
# Raw string compatibility (exact enum value match)
# ---------------------------------------------------------------------------


class TestRawStringCompatibility:
    def test_exact_node_label_value_accepted(self, csv_dir_with_files):
        """Raw strings that exactly match NodeLabel.value work in place of the enum."""
        extractor = CSVExtractor(str(csv_dir_with_files))
        extractor.extract_all(include_nodes=["Database"])
        assert not extractor.database_info.empty

    def test_exact_relationship_type_value_accepted(self, csv_dir_with_files):
        """Raw strings that exactly match RelationshipType.value work in place of the enum."""
        extractor = CSVExtractor(str(csv_dir_with_files))
        extractor.extract_all(include_relationships=["HAS_SCHEMA"])
        assert not extractor.schema_info.empty

    def test_lowercase_node_label_rejected(self, csv_dir):
        """Lowercase strings do not match and raise ValueError."""
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Unknown node types"):
            extractor.extract_all(include_nodes=["database"])

    def test_lowercase_relationship_type_rejected(self, csv_dir):
        """Lowercase strings do not match and raise ValueError."""
        extractor = CSVExtractor(str(csv_dir))
        with pytest.raises(ValueError, match="Unknown relationship types"):
            extractor.extract_all(include_relationships=["has_schema"])


# ---------------------------------------------------------------------------
# Core extraction behaviour
# ---------------------------------------------------------------------------


class TestExtraction:
    def test_extract_database_info_row_count(self, csv_dir_with_files):
        extractor = CSVExtractor(str(csv_dir_with_files))
        df = extractor.extract_database_info()
        assert df is not None
        assert len(df) == 1
        assert extractor.database_info["database_name"].iloc[0] == "my_db"

    def test_extract_schema_info_row_count(self, csv_dir_with_files):
        extractor = CSVExtractor(str(csv_dir_with_files))
        df = extractor.extract_schema_info()
        assert df is not None
        assert len(df) == 2

    def test_extract_missing_file_returns_none(self, csv_dir):
        """A file that doesn't exist returns None and leaves the cache empty."""
        extractor = CSVExtractor(str(csv_dir))
        df = extractor.extract_database_info()
        assert df is None
        assert extractor.database_info.empty

    def test_extract_missing_required_column_raises(self, tmp_path):
        """A file present but missing required columns raises ValueError."""
        (tmp_path / "schema_info.csv").write_text(
            "schema_name,description\nsales,Sales\n"  # missing database_name
        )
        extractor = CSVExtractor(str(tmp_path))
        with pytest.raises(ValueError, match="missing required columns"):
            extractor.extract_schema_info()

    def test_null_string_values_normalised(self, tmp_path):
        """'NULL', 'null', and 'NaN' string values in optional columns are treated as null."""
        import pandas as pd

        (tmp_path / "database_info.csv").write_text(
            "database_name,description\ndb1,NULL\ndb2,null\ndb3,NaN\ndb4,real description\n"
        )
        extractor = CSVExtractor(str(tmp_path))
        df = extractor.extract_database_info()
        assert pd.isna(df["description"].iloc[0])
        assert pd.isna(df["description"].iloc[1])
        assert pd.isna(df["description"].iloc[2])
        assert df["description"].iloc[3] == "real description"


# ---------------------------------------------------------------------------
# ID column computation
# ---------------------------------------------------------------------------


class TestIdComputation:
    """
    Verify that extraction computes *_id columns from name columns when absent,
    and preserves user-supplied *_id values when present.
    """

    # --- database ---

    def test_database_id_auto_generated(self, tmp_path):
        (tmp_path / "database_info.csv").write_text("database_name\nmy_db\n")
        df = CSVExtractor(str(tmp_path)).extract_database_info()
        assert "database_id" in df.columns
        assert df["database_id"].iloc[0] == generate_database_id("my_db")

    def test_database_id_explicit_preserved(self, tmp_path):
        (tmp_path / "database_info.csv").write_text(
            "database_name,database_id\nmy_db,custom-db-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_database_info()
        assert df["database_id"].iloc[0] == "custom-db-id"

    # --- schema ---

    def test_schema_id_auto_generated(self, tmp_path):
        (tmp_path / "schema_info.csv").write_text("database_name,schema_name\nmy_db,sales\n")
        df = CSVExtractor(str(tmp_path)).extract_schema_info()
        assert df["schema_id"].iloc[0] == generate_schema_id("my_db", "sales")

    def test_schema_id_explicit_preserved(self, tmp_path):
        (tmp_path / "schema_info.csv").write_text(
            "database_name,schema_name,schema_id\nmy_db,sales,custom-schema-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_schema_info()
        assert df["schema_id"].iloc[0] == "custom-schema-id"

    def test_schema_database_id_auto_generated(self, tmp_path):
        """database_id (parent FK) is also computed on schema_info for relationship use."""
        (tmp_path / "schema_info.csv").write_text("database_name,schema_name\nmy_db,sales\n")
        df = CSVExtractor(str(tmp_path)).extract_schema_info()
        assert df["database_id"].iloc[0] == generate_database_id("my_db")

    def test_schema_database_id_explicit_preserved(self, tmp_path):
        (tmp_path / "schema_info.csv").write_text(
            "database_name,schema_name,database_id\nmy_db,sales,custom-db-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_schema_info()
        assert df["database_id"].iloc[0] == "custom-db-id"

    # --- table ---

    def test_table_id_auto_generated(self, tmp_path):
        (tmp_path / "table_info.csv").write_text(
            "database_name,schema_name,table_name\nmy_db,sales,orders\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_table_info()
        assert df["table_id"].iloc[0] == generate_table_id("my_db", "sales", "orders")

    def test_table_id_explicit_preserved(self, tmp_path):
        (tmp_path / "table_info.csv").write_text(
            "database_name,schema_name,table_name,table_id\nmy_db,sales,orders,custom-table-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_table_info()
        assert df["table_id"].iloc[0] == "custom-table-id"

    def test_table_schema_id_auto_generated(self, tmp_path):
        """schema_id (parent FK) is computed on table_info for relationship use."""
        (tmp_path / "table_info.csv").write_text(
            "database_name,schema_name,table_name\nmy_db,sales,orders\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_table_info()
        assert df["schema_id"].iloc[0] == generate_schema_id("my_db", "sales")

    # --- column ---

    def test_column_id_auto_generated(self, tmp_path):
        (tmp_path / "column_info.csv").write_text(
            "database_name,schema_name,table_name,column_name\nmy_db,sales,orders,order_id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_column_info()
        assert df["column_id"].iloc[0] == generate_column_id("my_db", "sales", "orders", "order_id")

    def test_column_id_explicit_preserved(self, tmp_path):
        (tmp_path / "column_info.csv").write_text(
            "database_name,schema_name,table_name,column_name,column_id\n"
            "my_db,sales,orders,order_id,custom-col-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_column_info()
        assert df["column_id"].iloc[0] == "custom-col-id"

    def test_column_table_id_auto_generated(self, tmp_path):
        """table_id (parent FK) is computed on column_info for relationship use."""
        (tmp_path / "column_info.csv").write_text(
            "database_name,schema_name,table_name,column_name\nmy_db,sales,orders,order_id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_column_info()
        assert df["table_id"].iloc[0] == generate_table_id("my_db", "sales", "orders")

    # --- value ---

    def test_value_id_auto_generated(self, tmp_path):
        (tmp_path / "value_info.csv").write_text(
            "database_name,schema_name,table_name,column_name,value\n"
            "my_db,sales,orders,status,active\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_value_info()
        assert df["value_id"].iloc[0] == generate_value_id(
            "my_db", "sales", "orders", "status", "active"
        )

    def test_value_id_explicit_preserved(self, tmp_path):
        (tmp_path / "value_info.csv").write_text(
            "database_name,schema_name,table_name,column_name,value,value_id\n"
            "my_db,sales,orders,status,active,custom-val-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_value_info()
        assert df["value_id"].iloc[0] == "custom-val-id"

    def test_value_column_id_auto_generated(self, tmp_path):
        """column_id (parent FK) is computed on value_info for relationship use."""
        (tmp_path / "value_info.csv").write_text(
            "database_name,schema_name,table_name,column_name,value\n"
            "my_db,sales,orders,status,active\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_value_info()
        assert df["column_id"].iloc[0] == generate_column_id("my_db", "sales", "orders", "status")

    # --- column references ---

    def test_references_source_column_id_auto_generated(self, tmp_path):
        (tmp_path / "column_references_info.csv").write_text(
            "source_database_name,source_schema_name,source_table_name,source_column_name,"
            "target_database_name,target_schema_name,target_table_name,target_column_name\n"
            "my_db,sales,orders,customer_id,my_db,sales,customers,customer_id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_column_references_info()
        assert df["source_column_id"].iloc[0] == generate_column_id(
            "my_db", "sales", "orders", "customer_id"
        )
        assert df["target_column_id"].iloc[0] == generate_column_id(
            "my_db", "sales", "customers", "customer_id"
        )

    def test_references_explicit_ids_preserved(self, tmp_path):
        (tmp_path / "column_references_info.csv").write_text(
            "source_database_name,source_schema_name,source_table_name,source_column_name,"
            "target_database_name,target_schema_name,target_table_name,target_column_name,"
            "source_column_id,target_column_id\n"
            "my_db,sales,orders,customer_id,my_db,sales,customers,customer_id,"
            "custom-src-id,custom-tgt-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_column_references_info()
        assert df["source_column_id"].iloc[0] == "custom-src-id"
        assert df["target_column_id"].iloc[0] == "custom-tgt-id"

    # --- glossary ---

    def test_glossary_id_auto_generated(self, tmp_path):
        (tmp_path / "glossary_info.csv").write_text("glossary_name\necommerce_glossary\n")
        df = CSVExtractor(str(tmp_path)).extract_glossary_info()
        assert df["glossary_id"].iloc[0] == generate_glossary_id("ecommerce_glossary")

    def test_glossary_id_explicit_preserved(self, tmp_path):
        (tmp_path / "glossary_info.csv").write_text(
            "glossary_name,glossary_id\necommerce_glossary,custom-gloss-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_glossary_info()
        assert df["glossary_id"].iloc[0] == "custom-gloss-id"

    # --- category ---

    def test_category_id_auto_generated(self, tmp_path):
        (tmp_path / "category_info.csv").write_text(
            "glossary_name,category_name\necommerce_glossary,revenue_metrics\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_category_info()
        assert df["category_id"].iloc[0] == generate_category_id(
            "ecommerce_glossary", "revenue_metrics"
        )

    def test_category_glossary_id_auto_generated(self, tmp_path):
        """glossary_id (parent FK) is computed on category_info for relationship use."""
        (tmp_path / "category_info.csv").write_text(
            "glossary_name,category_name\necommerce_glossary,revenue_metrics\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_category_info()
        assert df["glossary_id"].iloc[0] == generate_glossary_id("ecommerce_glossary")

    def test_category_id_explicit_preserved(self, tmp_path):
        (tmp_path / "category_info.csv").write_text(
            "glossary_name,category_name,category_id\necommerce_glossary,revenue_metrics,custom-cat-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_category_info()
        assert df["category_id"].iloc[0] == "custom-cat-id"

    # --- business term ---

    def test_business_term_id_auto_generated(self, tmp_path):
        (tmp_path / "business_term_info.csv").write_text(
            "glossary_name,category_name,term_name\necommerce_glossary,revenue_metrics,gmv\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_business_term_info()
        assert df["business_term_id"].iloc[0] == generate_business_term_id(
            "ecommerce_glossary", "revenue_metrics", "gmv"
        )

    def test_business_term_category_id_auto_generated(self, tmp_path):
        """category_id (parent FK) is computed on business_term_info for relationship use."""
        (tmp_path / "business_term_info.csv").write_text(
            "glossary_name,category_name,term_name\necommerce_glossary,revenue_metrics,gmv\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_business_term_info()
        assert df["category_id"].iloc[0] == generate_category_id(
            "ecommerce_glossary", "revenue_metrics"
        )

    def test_business_term_id_explicit_preserved(self, tmp_path):
        (tmp_path / "business_term_info.csv").write_text(
            "glossary_name,category_name,term_name,business_term_id\n"
            "ecommerce_glossary,revenue_metrics,gmv,custom-term-id\n"
        )
        df = CSVExtractor(str(tmp_path)).extract_business_term_info()
        assert df["business_term_id"].iloc[0] == "custom-term-id"
