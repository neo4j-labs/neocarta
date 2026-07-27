"""Salesforce connector for neocarta."""

from .connector import SalesforceConnector
from .extract import SalesforceExtractor

__all__ = ["SalesforceConnector", "SalesforceExtractor"]
