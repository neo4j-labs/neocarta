"""Unit tests for SalesforceExtractor."""

from neocarta.connectors.salesforce.extract import SalesforceExtractor, _get_namespace

from .conftest import ORG_NAME

# ─── Namespace derivation ────────────────────────────────────────────────────


class TestGetNamespace:
    def test_standard_object(self):
        assert _get_namespace("Account", False) == "core"

    def test_unmanaged_custom(self):
        assert _get_namespace("Project__c", True) == "custom"

    def test_managed_package(self):
        assert _get_namespace("Acme__Widget__c", True) == "acme"

    def test_ambiguous_underscored_prefix(self):
        # CPP_CC_Entry__c has an underscore in its "prefix" — not a real namespace
        assert _get_namespace("CPP_CC_Entry__c", True) == "custom"

    def test_managed_event_object(self):
        assert _get_namespace("NS__MyEvent__e", True) == "ns"

    def test_managed_mdt_object(self):
        assert _get_namespace("NS__Config__mdt", True) == "ns"


# ─── Database extraction ─────────────────────────────────────────────────────


class TestExtractDatabaseInfo:
    def test_single_row(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        df = e.extract_database_info()
        assert len(df) == 1
        assert df.iloc[0]["database_name"] == ORG_NAME
        assert df.iloc[0]["platform"] == "Salesforce"
        assert "database_id" in df.columns

    def test_database_id_normalizes(self, all_objects):
        e = SalesforceExtractor(all_objects, "My Org")
        df = e.extract_database_info()
        assert df.iloc[0]["database_id"] == "my_org"


# ─── Schema extraction ───────────────────────────────────────────────────────


class TestExtractSchemaInfo:
    def test_correct_namespaces(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        df = e.extract_schema_info()
        namespaces = set(df["schema_name"].tolist())
        assert namespaces == {"core", "acme", "custom"}

    def test_schema_ids_populated(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        df = e.extract_schema_info()
        assert df["schema_id"].notna().all()
        assert df["database_id"].notna().all()

    def test_single_namespace_deduplication(self, account_object, contact_object):
        e = SalesforceExtractor([account_object, contact_object], ORG_NAME)
        df = e.extract_schema_info()
        assert len(df) == 1
        assert df.iloc[0]["schema_name"] == "core"


# ─── Table extraction ────────────────────────────────────────────────────────


class TestExtractTableInfo:
    def test_row_count(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        df = e.extract_table_info()
        assert len(df) == 4

    def test_table_names_normalized(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        df = e.extract_table_info()
        names = set(df["table_name"].tolist())
        assert "account" in names
        assert "contact" in names
        # Managed-package object normalized to lowercase
        assert "acme__widget__c" in names

    def test_sfdc_props_captured(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        e.extract_table_info()
        sfdc = e.table_sfdc_props
        row = sfdc.iloc[0]
        assert row["label"] == "Account"
        assert row["labelPlural"] == "Accounts"
        assert row["keyPrefix"] == "001"
        assert row["isCustom"] == False  # noqa: E712 (np.bool_ not `is`-comparable)
        assert row["isDeletable"] == False  # noqa: E712

    def test_schema_assigned_correctly(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        df = e.extract_table_info()
        account_row = df[df["table_name"] == "account"].iloc[0]
        assert account_row["schema_name"] == "core"
        widget_row = df[df["table_name"] == "acme__widget__c"].iloc[0]
        assert widget_row["schema_name"] == "acme"
        project_row = df[df["table_name"] == "project__c"].iloc[0]
        assert project_row["schema_name"] == "custom"


# ─── Column extraction ───────────────────────────────────────────────────────


class TestExtractColumnInfo:
    def test_row_count(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        df = e.extract_column_info()
        assert len(df) == 3  # Id, Name, Industry

    def test_primary_key_detected(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        df = e.extract_column_info()
        id_row = df[df["column_name"] == "id"].iloc[0]
        assert id_row["is_primary_key"] == True  # noqa: E712
        assert id_row["is_foreign_key"] == False  # noqa: E712

    def test_foreign_key_detected(self, contact_object):
        e = SalesforceExtractor([contact_object], ORG_NAME)
        df = e.extract_column_info()
        fk_row = df[df["column_name"] == "accountid"].iloc[0]
        assert fk_row["is_foreign_key"] == True  # noqa: E712

    def test_picklist_values_captured(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        e.extract_column_info()
        sfdc = e.column_sfdc_props
        industry_row = sfdc[sfdc["id"].str.endswith(".industry")].iloc[0]
        # Only active picklist values are included
        assert set(industry_row["picklistValues"]) == {"Technology", "Finance"}

    def test_column_ids_populated(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        df = e.extract_column_info()
        assert df["column_id"].notna().all()

    def test_sfdc_extras_have_matching_ids(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        df = e.extract_column_info()
        sfdc = e.column_sfdc_props
        assert set(sfdc["id"]) == set(df["column_id"])


# ─── References extraction ───────────────────────────────────────────────────


class TestExtractColumnReferencesInfo:
    def test_known_target_resolved(self, account_object, contact_object):
        e = SalesforceExtractor([account_object, contact_object], ORG_NAME)
        e.extract_column_info()  # populates _obj_namespace via __init__
        df = e.extract_column_references_info()
        # contact.accountid → account.id
        fk_row = df[df["source_column_name"] == "accountid"]
        assert len(fk_row) == 1
        assert fk_row.iloc[0]["target_table_name"] == "account"
        assert fk_row.iloc[0]["target_column_name"] == "id"
        assert fk_row.iloc[0]["target_schema_name"] == "core"

    def test_unknown_target_gets_system_schema(self, contact_object):
        # "User" is not in the described set → system schema
        e = SalesforceExtractor([contact_object], ORG_NAME)
        df = e.extract_column_references_info()
        user_ref = df[df["source_column_name"] == "ownerid"]
        assert len(user_ref) == 1
        assert user_ref.iloc[0]["target_schema_name"] == "system"

    def test_no_references_returns_empty_df(self, account_object):
        e = SalesforceExtractor([account_object], ORG_NAME)
        df = e.extract_column_references_info()
        assert df.empty

    def test_cross_namespace_reference(self, account_object, unmanaged_custom_object):
        e = SalesforceExtractor([account_object, unmanaged_custom_object], ORG_NAME)
        df = e.extract_column_references_info()
        ref = df[df["source_table_name"] == "project__c"].iloc[0]
        assert ref["source_schema_name"] == "custom"
        assert ref["target_schema_name"] == "core"


# ─── CSV output ──────────────────────────────────────────────────────────────


class TestCsvOutput:
    def test_writes_csvs_when_output_dir_set(self, all_objects, tmp_path):
        e = SalesforceExtractor(all_objects, ORG_NAME, output_dir=tmp_path)
        e.extract_all()
        expected = {
            "database_info.csv",
            "schema_info.csv",
            "table_info.csv",
            "column_info.csv",
            "column_references_info.csv",
        }
        written = {f.name for f in tmp_path.iterdir()}
        assert expected.issubset(written)

    def test_no_csvs_when_output_dir_none(self, all_objects, tmp_path):
        e = SalesforceExtractor(all_objects, ORG_NAME, output_dir=None)
        e.extract_all()
        # Nothing was written — the caller provided no output dir
        assert list(tmp_path.iterdir()) == []


# ─── extract_all integration ─────────────────────────────────────────────────


class TestExtractAll:
    def test_all_caches_populated(self, all_objects):
        e = SalesforceExtractor(all_objects, ORG_NAME)
        e.extract_all()
        assert not e.database_info.empty
        assert not e.schema_info.empty
        assert not e.table_info.empty
        assert not e.column_info.empty
        assert not e.column_references_info.empty
        assert not e.table_sfdc_props.empty
        assert not e.column_sfdc_props.empty
