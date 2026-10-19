"""Administrative scheduler adapter, never injected into patient HTTP.

Jobs derive from application plans. SQL rechecks live regimen, rule, event,
preference and subscription before claim; patients have read-only delivery RLS.
"""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import ValidationError

from ..application.reminder_plan import PlannedReminder
from ..contracts.notifications import Delivery, DeliveryResult
from ..contracts.push import PushSubscriptionInput
from .postgres_db import PostgresDatabase


class PostgresNotificationJobs:
    def __init__(
        self,
        database: PostgresDatabase,
        *,
        patient_scope: UUID | None = None,
        include_late_reports: bool = False,
        extended_tasks: bool = False,
        multiple_reminders: bool = False,
    ):
        self._database = database
        self._scope = patient_scope
        if multiple_reminders and not extended_tasks:
            raise ValueError("Multiple reminders require extended task support")
        # Fixed allowlisted relations, selected only by injected release capabilities.
        self._event_table = "public.effective_dose_events" if include_late_reports else "public.dose_events"
        self._task_table = (
            "public.medication_care_tasks"
            if extended_tasks
            else (
                "(SELECT patient_id,id,medication_id,regimen_id,due_at,status,source,version, "
                "0 AS reminder_minutes FROM public.medication_care_tasks)"
            )
        )

        if multiple_reminders:
            self._task_table = """(SELECT t.patient_id,t.id,t.medication_id,t.regimen_id,t.due_at,
                t.status,t.source,t.version,
                offsets.reminder_minutes FROM public.medication_care_tasks t CROSS JOIN LATERAL
                (SELECT DISTINCT unnest(coalesce(t.reminder_offsets,CASE WHEN t.reminder_minutes IS NULL
                    THEN '{}'::integer[] ELSE ARRAY[t.reminder_minutes] END)) AS reminder_minutes) offsets)"""

    def patients(self) -> list[dict]:
        with self._database.transaction() as conn:
            return conn.execute("""SELECT p.* FROM public.patient_profiles p WHERE p.reminders_enabled
                AND EXISTS(SELECT 1 FROM public.push_subscriptions s WHERE s.patient_id=p.user_id AND s.enabled)
                ORDER BY p.user_id LIMIT 500""").fetchall()

    def sync(self, patient_id: UUID, rows: list[PlannedReminder], now: datetime) -> None:
        with self._database.transaction() as conn:
            # One worker instance materializes this patient's projection at a time.
            conn.execute("SELECT 1 FROM public.patient_profiles WHERE user_id=%s FOR UPDATE", (patient_id,))
            conn.execute(
                """UPDATE public.notification_deliveries SET status='cancelled'
                WHERE patient_id=%s AND status='pending' AND task_id IS NULL""",
                (patient_id,),
            )
            for row in rows:
                conn.execute(
                    """INSERT INTO public.notification_deliveries
                    (patient_id,occurrence_id,regimen_id,rule_id,subscription_id,slot,remind_at,next_attempt_at)
                    SELECT %s,%s,%s,%s,s.id,%s,%s,%s FROM public.push_subscriptions s
                    WHERE s.patient_id=%s AND s.enabled
                    ON CONFLICT(occurrence_id,subscription_id,slot) DO UPDATE SET
                        remind_at=EXCLUDED.remind_at,
                        next_attempt_at=CASE WHEN notification_deliveries.attempts=0 THEN EXCLUDED.next_attempt_at
                            ELSE notification_deliveries.next_attempt_at END,
                        status='pending'
                    WHERE notification_deliveries.status IN ('cancelled','pending')
                        AND notification_deliveries.attempts<3""",
                    (
                        patient_id,
                        row.occurrence_id,
                        row.regimen_id,
                        row.rule_id,
                        row.slot,
                        row.remind_at,
                        row.remind_at,
                        patient_id,
                    ),
                )

    def sync_tasks(self, patient_id: UUID, now: datetime) -> None:
        """Materialize confirmed care tasks into the same delivery queue.

        No Gemini polling, no new scheduler and no patient-facing admin access.
        Task dates are explicitly supplied/confirmed, never clinical targets.
        """
        with self._database.transaction() as conn:
            conn.execute("SELECT 1 FROM public.patient_profiles WHERE user_id=%s FOR UPDATE", (patient_id,))
            conn.execute(
                """UPDATE public.notification_deliveries SET status='cancelled'
                WHERE patient_id=%s AND task_id IS NOT NULL AND status='pending'""",
                (patient_id,),
            )
            conn.execute(
                f"""INSERT INTO public.notification_deliveries
                (patient_id,task_id,subscription_id,slot,remind_at,next_attempt_at)
                SELECT t.patient_id,t.id,s.id,
                    coalesce((SELECT old.slot FROM public.notification_deliveries old
                        WHERE old.patient_id=t.patient_id AND old.task_id=t.id AND old.subscription_id=s.id
                        AND old.remind_at=t.due_at-make_interval(mins=>t.reminder_minutes)
                        ORDER BY CASE WHEN old.status IN ('sent','sending','failed') THEN 0 ELSE 1 END,
                            old.attempts DESC,old.id LIMIT 1),
                        'task:'||extract(epoch FROM (t.due_at-make_interval(mins=>t.reminder_minutes)))::text),
                    t.due_at-make_interval(mins=>t.reminder_minutes),t.due_at-make_interval(mins=>t.reminder_minutes)
                FROM {self._task_table} t
                JOIN public.push_subscriptions s ON s.patient_id=t.patient_id AND s.enabled
                JOIN public.patient_profiles p ON p.user_id=t.patient_id AND p.reminders_enabled
                WHERE t.patient_id=%s AND t.status IN ('open','contacted','deferred')
                AND t.reminder_minutes IS NOT NULL
                AND t.due_at-make_interval(mins=>t.reminder_minutes) BETWEEN %s AND %s
                AND (t.source<>'stock_estimate' OR EXISTS(SELECT 1 FROM public.regimen_versions r
                    WHERE r.patient_id=t.patient_id AND r.patient_medication_id=t.medication_id
                    AND r.state='active' AND NOT r.is_prn AND (r.effective_to IS NULL OR r.effective_to>%s)
                    AND (r.course_start_date IS NULL OR r.course_start_date<=(%s AT TIME ZONE p.timezone)::date)
                    AND (r.course_end_date IS NULL OR r.course_end_date>=(%s AT TIME ZONE p.timezone)::date)))
                ON CONFLICT(task_id,subscription_id,slot) DO UPDATE SET status='pending'
                WHERE notification_deliveries.status IN ('pending','cancelled')
                AND notification_deliveries.attempts<3""",
                (patient_id, now - timedelta(minutes=15), now + timedelta(days=1), now, now, now),
            )

    def claim(self, now: datetime) -> Delivery | None:
        with self._database.transaction() as conn:
            # An interrupted send may already have reached the push provider.
            # Fail closed instead of retrying ambiguous deliveries after a crash.
            conn.execute(
                """UPDATE public.notification_deliveries SET status='failed',error_category='uncertain_delivery'
                WHERE status='sending' AND claimed_at < %s AND (%s::uuid IS NULL OR patient_id=%s)""",
                (now - timedelta(minutes=2), self._scope, self._scope),
            )
            conn.execute(
                f"""UPDATE public.notification_deliveries d SET status='cancelled'
                WHERE d.status='pending' AND d.task_id IS NULL AND (%s::uuid IS NULL OR d.patient_id=%s) AND (
                    d.remind_at<%s OR NOT EXISTS(
                    SELECT 1 FROM public.dose_occurrences o
                    JOIN public.regimen_versions r ON r.patient_id=o.patient_id AND r.id=o.regimen_id
                    JOIN public.dose_rules rule ON rule.patient_id=o.patient_id AND rule.id=o.rule_id
                    JOIN public.patient_profiles p ON p.user_id=o.patient_id
                    JOIN public.push_subscriptions s ON s.patient_id=o.patient_id AND s.id=d.subscription_id
                    WHERE o.patient_id=d.patient_id AND o.id=d.occurrence_id AND o.status<>'closed'
                    AND r.state='active' AND rule.enabled AND p.reminders_enabled AND s.enabled
                    AND o.due_at>=r.effective_from AND (r.effective_to IS NULL OR o.due_at<r.effective_to)
                    AND %s < LEAST(o.due_at+interval '2 hours',
                    coalesce((SELECT min(n.due_at) FROM public.dose_occurrences n WHERE n.patient_id=o.patient_id
                     AND n.regimen_id=o.regimen_id AND n.status<>'closed' AND n.due_at>o.due_at),
                     o.due_at+interval '2 hours'),
                    ((o.due_at AT TIME ZONE p.timezone)::date+1)::timestamp AT TIME ZONE p.timezone)
                    AND (r.course_end_date IS NULL OR (o.due_at AT TIME ZONE rule.timezone)::date<=r.course_end_date)
                    AND NOT EXISTS(SELECT 1 FROM {self._event_table} e
                        WHERE e.patient_id=o.patient_id AND e.occurrence_id=o.id)))""",
                (self._scope, self._scope, now - timedelta(minutes=15), now),
            )
            row = conn.execute(
                f"""SELECT d.id,d.subscription_id,d.attempts,s.endpoint,s.keys,p.language
                FROM public.notification_deliveries d
                JOIN public.push_subscriptions s ON s.id=d.subscription_id AND s.patient_id=d.patient_id
                JOIN public.patient_profiles p ON p.user_id=d.patient_id
                JOIN public.dose_occurrences o ON o.id=d.occurrence_id AND o.patient_id=d.patient_id
                JOIN public.regimen_versions r ON r.id=o.regimen_id AND r.patient_id=o.patient_id
                JOIN public.dose_rules rule ON rule.id=o.rule_id AND rule.patient_id=o.patient_id
                LEFT JOIN public.dose_reminders snooze ON snooze.patient_id=o.patient_id AND snooze.occurrence_id=o.id
                WHERE d.status='pending' AND d.attempts<3 AND d.next_attempt_at<=%s
                AND (%s::uuid IS NULL OR d.patient_id=%s)
                AND d.remind_at BETWEEN %s AND %s AND s.enabled AND p.reminders_enabled
                AND r.state='active' AND NOT r.is_prn AND rule.enabled AND o.status<>'closed'
                AND %s < LEAST(o.due_at+interval '2 hours',
                    coalesce((SELECT min(n.due_at) FROM public.dose_occurrences n WHERE n.patient_id=o.patient_id
                     AND n.regimen_id=o.regimen_id AND n.status<>'closed' AND n.due_at>o.due_at),
                     o.due_at+interval '2 hours'),
                    ((o.due_at AT TIME ZONE p.timezone)::date+1)::timestamp AT TIME ZONE p.timezone)
                AND d.regimen_id=o.regimen_id AND d.rule_id=o.rule_id
                AND (r.effective_to IS NULL OR o.due_at<r.effective_to)
                AND (r.course_end_date IS NULL OR (o.due_at AT TIME ZONE rule.timezone)::date<=r.course_end_date)
                AND d.remind_at=COALESCE(snooze.remind_at,o.due_at-make_interval(mins=>p.reminder_lead_minutes))
                AND NOT EXISTS(SELECT 1 FROM {self._event_table} e
                    WHERE e.patient_id=o.patient_id AND e.occurrence_id=o.id)
                ORDER BY d.next_attempt_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT 1""",
                (now, self._scope, self._scope, now - timedelta(minutes=15), now, now),
            ).fetchone()
            if row is None:
                conn.execute(
                    f"""UPDATE public.notification_deliveries d SET status='cancelled'
                    WHERE d.task_id IS NOT NULL AND d.status='pending'
                    AND (%s::uuid IS NULL OR d.patient_id=%s) AND NOT EXISTS(
                    SELECT 1 FROM {self._task_table} t
                    JOIN public.patient_profiles p ON p.user_id=t.patient_id
                    JOIN public.push_subscriptions s ON s.patient_id=t.patient_id AND s.id=d.subscription_id
                    WHERE t.patient_id=d.patient_id AND t.id=d.task_id AND t.status IN ('open','contacted','deferred')
                    AND t.reminder_minutes IS NOT NULL
                    AND t.due_at-make_interval(mins=>t.reminder_minutes)=d.remind_at
                    AND d.remind_at>=%s AND p.reminders_enabled AND s.enabled
                    AND (t.source<>'stock_estimate' OR EXISTS(SELECT 1 FROM public.regimen_versions r
                        WHERE r.patient_id=t.patient_id AND r.patient_medication_id=t.medication_id
                        AND r.state='active' AND NOT r.is_prn
                        AND (r.effective_to IS NULL OR r.effective_to>%s)
                        AND (r.course_end_date IS NULL OR r.course_end_date>=(%s AT TIME ZONE p.timezone)::date))))""",
                    (self._scope, self._scope, now - timedelta(minutes=15), now, now),
                )
                row = conn.execute(
                    f"""SELECT d.id,d.subscription_id,d.attempts,s.endpoint,s.keys,p.language
                    FROM public.notification_deliveries d
                    JOIN public.push_subscriptions s ON s.id=d.subscription_id AND s.patient_id=d.patient_id
                    JOIN public.patient_profiles p ON p.user_id=d.patient_id
                    JOIN {self._task_table} t ON t.id=d.task_id AND t.patient_id=d.patient_id
                    WHERE d.status='pending' AND d.attempts<3 AND d.next_attempt_at<=%s
                    AND (%s::uuid IS NULL OR d.patient_id=%s)
                    AND d.remind_at BETWEEN %s AND %s AND s.enabled AND p.reminders_enabled
                    AND t.status IN ('open','contacted','deferred') AND t.reminder_minutes IS NOT NULL
                    AND t.due_at-make_interval(mins=>t.reminder_minutes)=d.remind_at
                    ORDER BY d.next_attempt_at,d.id FOR UPDATE OF d SKIP LOCKED LIMIT 1""",
                    (now, self._scope, self._scope, now - timedelta(minutes=15), now),
                ).fetchone()
            if row is None:
                return None
            try:
                subscription = PushSubscriptionInput(endpoint=row["endpoint"], keys=row["keys"])
            except ValidationError:
                conn.execute(
                    "UPDATE public.notification_deliveries SET status='failed',"
                    "error_category='invalid_subscription' WHERE id=%s",
                    (row["id"],),
                )
                return None
            conn.execute(
                "UPDATE public.notification_deliveries SET status='sending',attempts=attempts+1,"
                "claimed_at=%s WHERE id=%s",
                (now, row["id"]),
            )
            return Delivery(
                id=row["id"],
                subscription_id=row["subscription_id"],
                subscription=subscription,
                attempts=row["attempts"] + 1,
                language=row["language"],
            )

    def finish(self, delivery: Delivery, result: DeliveryResult, now: datetime) -> None:
        with self._database.transaction() as conn:
            # Match scheduler lock order: owner/profile before delivery rows.
            if result.status == "expired_subscription":
                conn.execute(
                    "UPDATE public.push_subscriptions SET enabled=false WHERE id=%s", (delivery.subscription_id,)
                )
            status = (
                "sent"
                if result.status == "sent"
                else "pending"
                if result.status == "temporary" and delivery.attempts < 3
                else "failed"
            )
            conn.execute(
                """UPDATE public.notification_deliveries SET status=%s,sent_at=%s,error_category=%s,next_attempt_at=%s
                WHERE id=%s AND status='sending'""",
                (
                    status,
                    now if status == "sent" else None,
                    None if status == "sent" else result.status,
                    now + timedelta(seconds=max(result.retry_seconds, 60 * 2**delivery.attempts)),
                    delivery.id,
                ),
            )


class PostgresWorkerReminders:
    """Read existing explicit snoozes for the administrative worker projection."""

    def __init__(self, database: PostgresDatabase):
        self._database = database

    def list_for_patient(self, patient_id):
        from ..contracts.reminders import ReminderDTO

        with self._database.transaction() as conn:
            rows = conn.execute(
                "SELECT patient_id,occurrence_id,remind_at,demo_only FROM public.dose_reminders WHERE patient_id=%s",
                (patient_id,),
            ).fetchall()
        return [ReminderDTO.model_validate(row) for row in rows]

    def save(self, reminder):
        # Scheduler never creates patient snoozes or modifies clinical instructions.
        raise NotImplementedError("Worker reminders are read-only")
