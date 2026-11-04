"""Optional current-task binding for native calendar reads, with no patient write."""

from collections.abc import Callable
from typing import TypeVar
from uuid import UUID

from ..contracts.assistant_workflows import EphemeralPayload
from ..contracts.reminder_workflow import CalendarFields
from ..domain.errors import StaleVersionError

T = TypeVar("T")


class WorkflowReminderReadService:
    def __init__(self, *, workflows, clinical):
        self.workflows, self.clinical = workflows, clinical

    def calendar(self, owner: UUID, task_id: UUID, revision: int, options: CalendarFields,
                 read: Callable[[], T]) -> T:
        control = self.workflows.control(owner, task_id)
        ephemeral = EphemeralPayload(capability_id="reminder.calendar.export",
                                    fields=options.model_dump(mode="json")) if control.mode == "ephemeral" else None
        current = self.workflows.read_only_input(owner, task_id, revision, "reminder.calendar.export", ephemeral)
        if current[1] != options:
            raise StaleVersionError("The calendar options differ from the current task")
        clinical_revision = self.clinical.revision(owner)
        result = read()
        checked = self.workflows.read_only_input(owner, task_id, revision, "reminder.calendar.export", ephemeral)
        if current != checked or clinical_revision != self.clinical.revision(owner):
            raise StaleVersionError("The calendar changed while reading; export the current task again")
        return result
