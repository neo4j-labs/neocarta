"""Salesforce Connector: ETL from Salesforce schema into Neo4j."""

from collections.abc import Generator
from pathlib import Path

from neo4j import Driver, RoutingControl

from ...ingest.rdbms import Neo4jRDBMSLoader
from ..csv.transform import CSVTransformer
from .extract import SalesforceExtractor
from .models import SalesforceObjectDict

# ─── Supplementary Cypher (Salesforce-specific properties) ────────────────────
#
# These properties are outside neocarta's core schema and must be set after the
# standard loader has created the nodes.
#
# Two variants per query mirror the overwrite_existing flag used by the standard
# loader: the _OVERWRITE variants always SET; the _MERGE variants use coalesce()
# so existing values are preserved and only NULL properties are filled in.

_SET_TABLE_SFDC_PROPS_OVERWRITE = """
UNWIND $rows AS row
MATCH (t:Table {id: row.id})
SET t.label        = row.label,
    t.labelPlural  = row.labelPlural,
    t.keyPrefix    = row.keyPrefix,
    t.namespace    = row.namespace,
    t.isCustom     = row.isCustom,
    t.isQueryable  = row.isQueryable,
    t.isCreateable = row.isCreateable,
    t.isUpdateable = row.isUpdateable,
    t.isDeletable  = row.isDeletable
RETURN count(*) AS updated
"""

_SET_TABLE_SFDC_PROPS_MERGE = """
UNWIND $rows AS row
MATCH (t:Table {id: row.id})
SET t.label        = coalesce(t.label,        row.label),
    t.labelPlural  = coalesce(t.labelPlural,  row.labelPlural),
    t.keyPrefix    = coalesce(t.keyPrefix,    row.keyPrefix),
    t.namespace    = coalesce(t.namespace,    row.namespace),
    t.isCustom     = coalesce(t.isCustom,     row.isCustom),
    t.isQueryable  = coalesce(t.isQueryable,  row.isQueryable),
    t.isCreateable = coalesce(t.isCreateable, row.isCreateable),
    t.isUpdateable = coalesce(t.isUpdateable, row.isUpdateable),
    t.isDeletable  = coalesce(t.isDeletable,  row.isDeletable)
RETURN count(*) AS updated
"""

_SET_COLUMN_SFDC_PROPS_OVERWRITE = """
UNWIND $rows AS row
MATCH (c:Column {id: row.id})
SET c.label          = row.label,
    c.length         = row.length,
    c.precision      = row.precision,
    c.scale          = row.scale,
    c.isUnique       = row.isUnique,
    c.picklistValues = row.picklistValues
RETURN count(*) AS updated
"""

_SET_COLUMN_SFDC_PROPS_MERGE = """
UNWIND $rows AS row
MATCH (c:Column {id: row.id})
SET c.label          = coalesce(c.label,          row.label),
    c.length         = coalesce(c.length,          row.length),
    c.precision      = coalesce(c.precision,       row.precision),
    c.scale          = coalesce(c.scale,           row.scale),
    c.isUnique       = coalesce(c.isUnique,        row.isUnique),
    c.picklistValues = coalesce(c.picklistValues,  row.picklistValues)
RETURN count(*) AS updated
"""

# Uses MERGE on the target Column so that references to system objects not in
# the described set (RecordType, Profile, Group, …) create stub Column nodes
# rather than being silently dropped.
# overwrite_existing=True  → SET r.criteria (always update)
# overwrite_existing=False → ON CREATE SET r.criteria (only on new edges)
_MERGE_REFERENCES_OVERWRITE = """
UNWIND $rows AS row
MATCH (src:Column {id: row.source_column_id})
MERGE (tgt:Column {id: row.target_column_id})
MERGE (src)-[r:REFERENCES]->(tgt)
SET r.criteria = row.criteria
RETURN count(*) AS created
"""

_MERGE_REFERENCES_MERGE = """
UNWIND $rows AS row
MATCH (src:Column {id: row.source_column_id})
MERGE (tgt:Column {id: row.target_column_id})
MERGE (src)-[r:REFERENCES]->(tgt)
  ON CREATE SET r.criteria = row.criteria
RETURN count(*) AS created
"""


def _chunk(lst: list, size: int) -> Generator[list, None, None]:
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


class SalesforceConnector:
    """
    Connector for loading a Salesforce schema into Neo4j.

    Follows an Extract → Transform → Load pattern:

    * **Extract** (`SalesforceExtractor`) — converts sobject describe dicts
      into neocarta-compatible DataFrames plus Salesforce-specific extras.
    * **Transform** (`CSVTransformer`) — reuses the CSV transformer because
      the extractor produces DataFrames with the exact column layout expected
      by that transformer.
    * **Load** (`Neo4jRDBMSLoader`) — writes standard neocarta nodes and
      relationships; then runs supplementary Cypher to attach Salesforce-
      specific properties and create REFERENCES edges with MERGE semantics
      (so references to system objects create stub Column nodes rather than
      being silently dropped).

    Parameters
    ----------
    objects : list[SalesforceObjectDict]
        Raw sobject describe dicts, one per Salesforce object.
    org_name : str
        Logical name for this org — becomes the neocarta Database ``name``.
    neo4j_driver : Driver
        Connected Neo4j driver instance.
    database_name : str
        Neo4j database to write into (default ``"neo4j"``).
    output_dir : Path | None
        When provided, the extractor writes each DataFrame as a CSV file to
        this directory so the intermediate data is inspectable.
    batch_size : int
        Rows per Cypher batch for supplementary writes (default 500).
    """

    def __init__(
        self,
        objects: list[SalesforceObjectDict],
        org_name: str,
        neo4j_driver: Driver,
        database_name: str = "neo4j",
        output_dir: Path | None = None,
        batch_size: int = 500,
    ) -> None:
        """Initialise extractor, transformer, and loader for the given org."""
        self.extractor = SalesforceExtractor(objects, org_name, output_dir)
        self.transformer = CSVTransformer()
        self.loader = Neo4jRDBMSLoader(neo4j_driver, database_name)
        self._driver = neo4j_driver
        self._db = database_name
        self._batch_size = batch_size

    # ------------------------------------------------------------------
    # ETL steps
    # ------------------------------------------------------------------

    def extract_metadata(self) -> None:
        """Run all extraction steps (populates the extractor cache)."""
        self.extractor.extract_all()

    def transform_metadata(self) -> None:
        """Convert extracted DataFrames into typed neocarta model objects."""
        e = self.extractor
        t = self.transformer

        t.transform_to_database_nodes(e.database_info)
        t.transform_to_schema_nodes(e.schema_info)
        t.transform_to_table_nodes(e.table_info)
        t.transform_to_column_nodes(e.column_info)

        t.transform_to_has_schema_relationships(e.schema_info)
        t.transform_to_has_table_relationships(e.table_info)
        t.transform_to_has_column_relationships(e.column_info)
        # References are handled by supplementary MERGE Cypher in load_metadata(),
        # not by the standard loader, so we do NOT call transform_to_references here.

    def load_metadata(self, overwrite_existing: bool = False) -> None:
        """Write transformed objects to Neo4j plus Salesforce-specific extras.

        Parameters
        ----------
        overwrite_existing : bool
            When True, SET all node properties (overwrite existing values).
            When False, MERGE only creates new nodes / sets properties on
            CREATE — existing data is left untouched.
        """
        t = self.transformer

        # ── Standard neocarta nodes ──────────────────────────────────────
        if t.database_nodes:
            self.loader.load_database_nodes(
                t.database_nodes,
                properties_list=t.get_properties("database_nodes"),
                overwrite_existing=overwrite_existing,
            )
        if t.schema_nodes:
            self.loader.load_schema_nodes(
                t.schema_nodes,
                properties_list=t.get_properties("schema_nodes"),
                overwrite_existing=overwrite_existing,
            )
        if t.table_nodes:
            self.loader.load_table_nodes(
                t.table_nodes,
                properties_list=t.get_properties("table_nodes"),
                overwrite_existing=overwrite_existing,
            )
        if t.column_nodes:
            self.loader.load_column_nodes(
                t.column_nodes,
                properties_list=t.get_properties("column_nodes"),
                overwrite_existing=overwrite_existing,
            )

        # ── Standard neocarta relationships ─────────────────────────────
        if t.has_schema_relationships:
            self.loader.load_has_schema_relationships(
                t.has_schema_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_table_relationships:
            self.loader.load_has_table_relationships(
                t.has_table_relationships, overwrite_existing=overwrite_existing
            )
        if t.has_column_relationships:
            self.loader.load_has_column_relationships(
                t.has_column_relationships, overwrite_existing=overwrite_existing
            )

        table_q = _SET_TABLE_SFDC_PROPS_OVERWRITE if overwrite_existing else _SET_TABLE_SFDC_PROPS_MERGE
        col_q = _SET_COLUMN_SFDC_PROPS_OVERWRITE if overwrite_existing else _SET_COLUMN_SFDC_PROPS_MERGE
        ref_q = _MERGE_REFERENCES_OVERWRITE if overwrite_existing else _MERGE_REFERENCES_MERGE

        # ── Salesforce-specific Table properties ─────────────────────────
        sfdc_tables = self.extractor.table_sfdc_props
        if not sfdc_tables.empty:
            rows = sfdc_tables.where(sfdc_tables.notna(), None).to_dict("records")
            for batch in _chunk(rows, self._batch_size):
                self._driver.execute_query(
                    table_q,
                    parameters_={"rows": batch},
                    routing_=RoutingControl.WRITE,
                    database_=self._db,
                )

        # ── Salesforce-specific Column properties ────────────────────────
        sfdc_cols = self.extractor.column_sfdc_props
        if not sfdc_cols.empty:
            rows = sfdc_cols.where(sfdc_cols.notna(), None).to_dict("records")
            for batch in _chunk(rows, self._batch_size):
                self._driver.execute_query(
                    col_q,
                    parameters_={"rows": batch},
                    routing_=RoutingControl.WRITE,
                    database_=self._db,
                )

        # ── References (MERGE — handles unknown target objects) ──────────
        refs = self.extractor.column_references_info
        if not refs.empty:
            ref_rows = refs[["source_column_id", "target_column_id", "criteria"]].to_dict("records")
            for batch in _chunk(ref_rows, self._batch_size):
                self._driver.execute_query(
                    ref_q,
                    parameters_={"rows": batch},
                    routing_=RoutingControl.WRITE,
                    database_=self._db,
                )
            n_system = (
                (
                    refs["target_database_name"].notna() & (refs["target_schema_name"] == "system")
                ).sum()
                if "target_schema_name" in refs.columns
                else 0
            )
            if n_system:
                print(f"  ⚠ {n_system} references to system objects (stub Column nodes created)")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, overwrite_existing: bool = False) -> None:
        """Run the full Extract → Transform → Load pipeline.

        Parameters
        ----------
        overwrite_existing : bool
            Passed through to ``load_metadata()``.
        """
        self.extract_metadata()
        self.transform_metadata()
        self.load_metadata(overwrite_existing=overwrite_existing)
