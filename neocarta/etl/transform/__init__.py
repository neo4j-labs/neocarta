"""Central transform and generic KeySpec ID builder; populated in S3 (see GUIDE §5).

The transform and the builder are S3's. What is here already is the D6
explicit-ID precedence rule (S1.4), which lands in this package because GUIDE §5
maps ``connectors/utils/generate_id.py`` onto it — so the rule never has to move
once the generic ID builder (#305) arrives to call it.
"""

from .explicit_id import resolve_id

__all__ = ["resolve_id"]
