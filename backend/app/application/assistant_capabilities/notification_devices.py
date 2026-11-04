"""Device intent opens a safe page; no credentials or model write authority."""

from collections.abc import Callable

from ...contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    DeviceAction,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.reminder_workflow import NOTIFICATION_DEVICE_SCHEMAS, NotificationDeviceFields
from ...domain.errors import ValidationError


class NotificationDeviceAdapter:
    capability_ids = frozenset(NOTIFICATION_DEVICE_SCHEMAS)

    def __init__(self, *, send_allowed: Callable[[], bool]):
        self.send_allowed = send_allowed

    def prepare(self, context: WorkflowContext, values: NotificationDeviceFields, assets: tuple[AttachmentRef, ...],
                results: tuple[BusinessRef, ...] = ()) -> Preparation:
        if assets or results or context.capability_id not in self.capability_ids:
            raise ValidationError("Device actions accept only a page-owned notification intent")
        return Preparation(input_fields={}, prompt_key="assistant.notification.device",
            view_fields={"operation": context.capability_id.rsplit(".", 1)[1],
                         "test_send_allowed": self.send_allowed()},
            actions=(DeviceAction(action="notification_permission"),))

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        return OperationResult(state="failed", reason="device_result_stays_on_patient_page")
