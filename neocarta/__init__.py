"""Neocarta library root package."""

import logging
from importlib.metadata import version

from .enums import NodeLabel, RelationshipType

# Library code logs under the "neocarta" hierarchy; attach a NullHandler so
# importing neocarta never emits "No handlers could be found" warnings and never
# hijacks logging config. A host (the CLI) opts in via _logging.configure_logging.
logging.getLogger("neocarta").addHandler(logging.NullHandler())

__version__ = version("neocarta")

__all__ = ["NodeLabel", "RelationshipType", "__version__"]
