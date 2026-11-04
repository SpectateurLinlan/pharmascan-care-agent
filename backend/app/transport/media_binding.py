"""Paired task headers opt native patient requests into current media review guards."""

from ..domain.errors import ValidationError


def bound_media(container, owner, task, revision, allowed, target, payload, confirmed, write):
    service = container.assistant_media
    if task is None and revision is None:
        return service.run_unbound(owner, write) if service else write()
    if task is None or revision is None or service is None:
        raise ValidationError("The media review needs its current Assistant task and revision")
    return service.run(owner, task, revision, allowed, target, payload, confirmed, write)
