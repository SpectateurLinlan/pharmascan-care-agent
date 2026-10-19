"""Administrative composition root. Never imported by patient app/container."""

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from ..application.dosing import DoseScheduleService
from ..application.notification_dispatch import NotificationDispatchService
from ..application.notification_worker import NotificationWorker
from ..application.reminder_plan import ReminderPlanService
from ..application.reminders import ReminderService
from ..application.timezone import FixedTzProvider
from ..config import Settings
from ..infrastructure.identifiers import RandomIdGenerator
from ..infrastructure.memory_repos import SystemClock
from ..infrastructure.notification_jobs import PostgresNotificationJobs, PostgresWorkerReminders
from ..infrastructure.postgres_db import PostgresDatabase
from ..infrastructure.postgres_repos import build_postgres_repositories
from ..infrastructure.web_push import WebPushProvider, validate_vapid


def build_worker_dispatch(settings: Settings) -> NotificationDispatchService:
    """Only this worker root reads privileged DB credentials; adapters are injected."""
    if not settings.enable_web_push:
        raise ValueError("Web Push disabled")
    validate_vapid(settings.vapid_public_key, settings.vapid_private_key, settings.vapid_subject)
    database = PostgresDatabase(
        dsn=settings.require_database_url(),
        application_name="pharmascan-reminder-worker",
        statement_timeout_ms=2000,
        connect_timeout_s=3,
    )
    if database.target.port == 6543:
        # A transaction pool can switch backend sessions between statements,
        # invalidating a session-held advisory lease. Supabase session pool uses5432.
        raise ValueError("Worker lease requires a direct or session-pooled DATABASE_URL, not transaction pool6543")
    clock = SystemClock()
    jobs = PostgresNotificationJobs(
        database,
        include_late_reports=settings.enable_late_dose_reports,
        extended_tasks=settings.enable_care_task_followups,
    )
    repos = build_postgres_repositories(database, include_late_reports=settings.enable_late_dose_reports)

    @contextmanager
    def lease() -> Iterator[bool]:
        # Session advisory lock spans projection AND sends, across CLI/HTTP/processes.
        # A hard-killed worker releases this connection/lock through PostgreSQL.
        with database.connect(autocommit=True) as connection:
            acquired = connection.execute("SELECT pg_try_advisory_lock(7348261045) AS acquired").fetchone()["acquired"]
            try:
                yield acquired
            finally:
                if acquired:
                    connection.execute("SELECT pg_advisory_unlock(7348261045)")

    def project(available: Callable[[], bool]) -> int:
        count = 0
        for profile in jobs.patients():
            if not available():
                break
            timezone = FixedTzProvider(profile["timezone"])
            schedule = DoseScheduleService(
                regimens=repos.regimens,
                rules=repos.dose_rules,
                occurrences=repos.occurrences,
                clock=clock,
                ids=RandomIdGenerator(),
                tz_provider=timezone,
            )
            reminders = ReminderService(
                repository=PostgresWorkerReminders(database),
                occurrences=repos.occurrences,
                regimens=repos.regimens,
                clock=clock,
                tz_provider=timezone,
            )
            plan = ReminderPlanService(
                medications=repos.medications,
                regimens=repos.regimens,
                schedule=schedule,
                events=repos.events,
                reminders=reminders,
                clock=clock,
            )
            rows = plan.upcoming(profile["user_id"], lead_minutes=profile["reminder_lead_minutes"])
            if not available():
                break
            jobs.sync(profile["user_id"], rows, clock.now())
            jobs.sync_tasks(profile["user_id"], clock.now())
            count += 1
        return count

    return NotificationDispatchService(
        worker=NotificationWorker(
            jobs, WebPushProvider(private_key=settings.vapid_private_key, subject=settings.vapid_subject), clock
        ),
        project=project,
        lease=lease,
        monotonic=time.monotonic,
    )
