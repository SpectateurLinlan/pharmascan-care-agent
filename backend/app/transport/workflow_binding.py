"""Optional paired headers for native patient actions."""

from typing import Annotated
from uuid import UUID

from fastapi import Header

from ..domain.errors import ValidationError


def native_binding(
    task: Annotated[UUID | None, Header(alias="X-Assistant-Task")] = None,
    revision: Annotated[int | None, Header(alias="X-Assistant-Revision", ge=1)] = None,
    confirmed: Annotated[bool, Header(alias="X-Patient-Confirmed")] = False,
):
    if (task is None) != (revision is None):
        raise ValidationError("Use a complete current task binding")
    return (task, revision, confirmed) if task else None
