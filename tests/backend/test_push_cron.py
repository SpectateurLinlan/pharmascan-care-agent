"""Release guard for operator SQL; never connect to a database or enable Cron."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_cron_creation_stays_inactive_and_refuses_replacing_a_named_job():
    sql = (ROOT / "deploy/dispatcher/push-cron.sql").read_text(encoding="utf-8")
    before, command, after = sql.split("$command$")
    assert "BEGIN;" in before
    assert "IF EXISTS(SELECT 1 FROM cron.job WHERE jobname='medithread-push-minute')" in before
    assert "RAISE EXCEPTION 'Named dispatcher job already exists" in before
    assert "cron.schedule('medithread-push-minute','* * * * *'," in before
    assert "PERFORM cron.alter_job(job_id,active:=false)" in after
    assert after.index("active:=false") < after.index("COMMIT;")
    assert "active:=true" not in sql
    assert "INTO STRICT signing_key" in command
    assert "RAISE NOTICE 'Dispatcher request ID: %', request_id" in command
    assert "RAISE NOTICE 'Dispatcher request ID: %', signing_key" not in command


def test_scheduled_dispatch_uses_fixed_signed_endpoint_without_bearer_auth():
    sql = (ROOT / "deploy/dispatcher/push-cron.sql").read_text(encoding="utf-8")
    scheduled = sql.split("$command$")[1].strip()
    assert "https://medithread-push-worker.vercel.app/internal/notifications/dispatch" in scheduled
    assert "'X-Dispatch-Timestamp',stamp,'X-Dispatch-Signature',signature" in scheduled
    assert "'Authorization'" not in scheduled
    assert "timeout_milliseconds := 45000" in scheduled
