"""Native APIs keep their own SQL transaction when Assistant persistence is active."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.application.workflow_care import WorkflowCareService
from app.application.workflow_media import WorkflowMediaService
from app.application.workflow_reminder_writes import WorkflowReminderWriteService
from app.application.workflow_settings import WorkflowSettingsService
from app.domain.errors import ProviderUnavailableError


@pytest.mark.parametrize("service_type", [WorkflowCareService, WorkflowMediaService,
                                         WorkflowReminderWriteService, WorkflowSettingsService])
@pytest.mark.parametrize("persistent", [True, False])
def test_native_unbound_uses_native_transaction_without_generic_persistent_write(service_type, persistent):
    owner = uuid4()
    calls = []

    class Clinical:
        def revision(self, patient):
            assert patient == owner
            calls.append("revision")
            return 3

        def run(self, patient, revision, write):
            if persistent:
                raise ProviderUnavailableError("Use the explicit patient transaction")
            assert patient == owner and revision == 3
            calls.append("memory_fence")
            return write()

    adapter = SimpleNamespace(clinical=Clinical())
    options = {"workflows": None, "preferences": None,
               "transactions": object() if persistent else None}
    options["adapters" if service_type is WorkflowSettingsService else "adapter"] = (
        {"preferences.edit": adapter} if service_type is WorkflowSettingsService else adapter
    )
    service = service_type(**options)
    marker = object()

    def native_write():
        calls.append("native_write")
        return marker

    assert service.run_unbound(owner, native_write) is marker
    assert calls == (["native_write"] if persistent else ["revision", "memory_fence", "native_write"])
