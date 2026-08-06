"""Every connector's production mapping declaration, in one place, for tests to iterate.

Test-side on purpose. No production code enumerates the declarations — each connector reaches its
own, and the S4 cutover wires them one at a time — so a production registry would be a second
owner of a list nothing runtime-reads. What tests *do* need is to sweep them all, so the sweep
lives here.
"""

from dataclasses import dataclass
from importlib import import_module
from typing import Any


@dataclass(frozen=True)
class Declared:
    """One connector's declaration and where it is declared.

    Attributes:
        connector: The connector name, matching ``OFFLINE_EXTRACTORS`` and the golden filename.
        module: The dotted path of the module holding the declaration.
        constant: The declaration's constant name in that module.
        extractor: The dotted path of the extractor class the declaration's sources must resolve
            against.
    """

    connector: str
    module: str
    constant: str
    extractor: str

    @property
    def mapping(self) -> Any:
        """The declaration itself."""
        return getattr(import_module(self.module), self.constant)

    @property
    def extractor_class(self) -> type:
        """The extractor class whose accessors the declaration names."""
        module, _, name = self.extractor.rpartition(".")
        return getattr(import_module(module), name)


DECLARATIONS: tuple[Declared, ...] = (
    Declared(
        "bigquery/schema",
        "neocarta.connectors.bigquery.schema.mapping",
        "BIGQUERY_SCHEMA",
        "neocarta.connectors.bigquery.schema.extract.BigQuerySchemaExtractor",
    ),
    Declared(
        "jdbc/schema",
        "neocarta.connectors.jdbc.schema.mapping",
        "JDBC_SCHEMA",
        "neocarta.connectors.jdbc.schema.extract.JdbcSchemaExtractor",
    ),
    Declared(
        "csv",
        "neocarta.connectors.csv.mapping",
        "CSV",
        "neocarta.connectors.csv.extract.CSVExtractor",
    ),
    Declared(
        "databricks/tags",
        "neocarta.connectors.databricks.tags.mapping",
        "DATABRICKS_TAGS",
        "neocarta.connectors.databricks.tags.extract.DatabricksTagsExtractor",
    ),
    Declared(
        "query_log",
        "neocarta.connectors.query_log.mapping",
        "QUERY_LOG",
        "neocarta.connectors.query_log.extract.QueryLogExtractor",
    ),
)

#: Connector name → its declaration record.
BY_CONNECTOR: dict[str, Declared] = {declared.connector: declared for declared in DECLARATIONS}
