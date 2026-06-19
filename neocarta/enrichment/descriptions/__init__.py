"""Description generation functions."""

from .base import BaseDescriptionConnector
from .litellm_description import LiteLLMDescriptionConnector

__all__ = [
    "BaseDescriptionConnector",
    "LiteLLMDescriptionConnector",
]
