"""Fixed patient routes may opt into current Assistant review checks."""

from ..domain.errors import ValidationError


def bound_care(container, owner, task, revision, allowed, target, payload, write):
    if task is None and revision is None:
        return container.assistant_care.run_unbound(owner, write) if container.assistant_care else write()
    if task is None or revision is None or container.assistant_care is None:
        raise ValidationError("The care review needs its current Assistant task and revision")
    return container.assistant_care.run(owner, task, revision, allowed, target, payload, write)
