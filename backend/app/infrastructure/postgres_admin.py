"""Privileged administrative provisioning (admin setup only).

This module exists because of one specific trust-boundary rule
(docs/ARCHITECTURE.md, Session 3D):

    the privileged connection is used for migrations, schema verification,
    maintenance and **admin setup** — never as the normal patient CRUD path.

A synthetic demo patient needs two rows that a patient request must never be
able to create for itself: an ``auth.users`` identity and the
``patient_profiles`` owner row that every patient-owned table references. Both
are therefore created here, over the privileged connection, *before* the
patient path takes over under RLS.

Nothing in this module reads or writes patient data. It creates no medication,
regimen, dose or report, and it never accepts a caller-supplied owner for an
existing row.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from .postgres_db import PostgresDatabase

#: Supabase's single-instance id for a local/dev project; matches the value the
#: evidence harness uses so both paths create identical synthetic identities.
DEFAULT_AUTH_INSTANCE_ID = "00000000-0000-0000-0000-000000000000"

DEFAULT_PATIENT_TIMEZONE = "Asia/Singapore"


@dataclass(frozen=True)
class ProvisioningResult:
    """What admin setup actually did (safe to log: no secrets, no health data)."""

    patient_id: UUID
    auth_user_created: bool
    profile_created: bool

    @property
    def created_anything(self) -> bool:
        return self.auth_user_created or self.profile_created


class PostgresAdminProvisioner:
    """Idempotent synthetic-identity provisioning over the privileged role.

    Every insert is ``ON CONFLICT DO NOTHING``, so provisioning is safe to call
    on every demo start: the first call creates the identity and a later call
    can never rewrite an existing patient's timezone or email.
    """

    def __init__(self, database: PostgresDatabase) -> None:
        self._db = database

    def ensure_identity(self, *, patient_id: UUID, timezone: str = DEFAULT_PATIENT_TIMEZONE) -> ProvisioningResult:
        """Create the synthetic ``auth.users`` + ``patient_profiles`` rows."""
        with self._db.transaction() as conn, conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO auth.users
                    (id, instance_id, aud, role, email, encrypted_password,
                     email_confirmed_at, created_at, updated_at)
                VALUES (%s, %s, 'authenticated', 'authenticated', %s,
                        'synthetic-no-login', now(), now(), now())
                ON CONFLICT (id) DO NOTHING
                """,
                (str(patient_id), DEFAULT_AUTH_INSTANCE_ID, self._synthetic_email(patient_id)),
            )
            auth_created = cursor.rowcount == 1

            cursor.execute(
                """
                INSERT INTO public.patient_profiles (user_id, timezone, demo_only)
                VALUES (%s, %s, true)
                ON CONFLICT (user_id) DO NOTHING
                """,
                (patient_id, timezone),
            )
            profile_created = cursor.rowcount == 1

        return ProvisioningResult(
            patient_id=patient_id,
            auth_user_created=auth_created,
            profile_created=profile_created,
        )

    @staticmethod
    def _synthetic_email(patient_id: UUID) -> str:
        """A reserved-TLD address so a synthetic identity can never be mailed."""
        return f"synthetic-{patient_id}@pharmascan.invalid"
