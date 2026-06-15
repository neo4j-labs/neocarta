"""Dataplex connectors: BigQuery catalog schema + business glossary."""

from .glossary import DataplexGlossaryConnector
from .schema import DataplexSchemaConnector

__all__ = ["DataplexGlossaryConnector", "DataplexSchemaConnector"]
