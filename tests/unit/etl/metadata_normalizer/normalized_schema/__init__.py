"""Unit tests for the normalized structural-core contract."""

from __future__ import annotations

from pydantic import AliasChoices, BaseModel


def _accepted_input_names(model: type[BaseModel]) -> set[str]:
    """Every input key ``model`` accepts: field names plus all validation aliases.

    Shared by the structural-core and facet suites, which both assert alias coverage. One copy so
    that a change in pydantic's ``validation_alias`` shape cannot leave one suite's guards passing
    while the other's silently stop meaning what they say.
    """
    names: set[str] = set()
    for field_name, info in model.model_fields.items():
        names.add(field_name)
        alias = info.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(choice for choice in alias.choices if isinstance(choice, str))
        elif isinstance(alias, str):
            names.add(alias)
    return names
