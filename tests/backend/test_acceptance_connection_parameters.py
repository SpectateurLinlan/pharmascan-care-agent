"""Connection safety for opt-in acceptance; no external I/O."""

import pytest

from tests.backend.persistent_workflow_live_support import (
    PersistentProfileRefusal,
    PersistentWorkflowTestProfile,
    sql_connection_parameters,
)


def profile(host="qa.example.invalid"):
    return PersistentWorkflowTestProfile(
        database_url=f"postgresql://postgres:DEMO@{host}:5432/mt_assistant_test_demo"
        "?sslmode=verify-full&sslrootcert=D%3A%2FDEMO%2Fca.crt"
    )


def test_dns_connection_does_not_supply_numeric_address_or_empty_service():
    parameters = sql_connection_parameters(profile(), verifier=False, read_only=True)
    assert parameters["hostaddr"] == ""
    assert "service" not in parameters  # libpq 18 rejects service="".
    assert parameters["sslmode"] == "verify-full"
    assert parameters["sslrootcert"] == "D:/DEMO/ca.crt"
    assert parameters["dbname"] == "mt_assistant_test_demo"


def test_loopback_connection_pins_numeric_address():
    parameters = sql_connection_parameters(profile("127.0.0.1"), verifier=False, read_only=False)
    assert parameters["hostaddr"] == "127.0.0.1"


@pytest.mark.parametrize("name", ["PGSERVICE", "PGSERVICEFILE", "PGHOSTADDR", "PGSSLCERT", "PGSSLKEY"])
def test_ambient_connection_overrides_are_refused(monkeypatch, name):
    monkeypatch.setenv(name, "DEMO-unapproved-override")
    with pytest.raises(PersistentProfileRefusal):
        sql_connection_parameters(profile(), verifier=False, read_only=False)
