"""OSI (Open Semantic Interchange) connector."""

from ...warnings import UnsupportedOsiVersionWarning
from .connector import OsiConnector

__all__ = ["OsiConnector", "UnsupportedOsiVersionWarning"]
