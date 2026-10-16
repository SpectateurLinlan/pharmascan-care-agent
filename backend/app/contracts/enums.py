"""Explicit status enums mirroring the SQL CHECK constraints in
supabase/migrations/202610130001_core.sql. Never widen these without a
matching reversible migration."""

from __future__ import annotations

from enum import StrEnum


class SourceKind(StrEnum):
    PACKAGE = "package"
    PHARMACY_LABEL = "pharmacy_label"
    PRESCRIPTION = "prescription"
    MOCK_IMPORT = "mock_import"
    USER_MANUAL = "user_manual"


class SourceReviewStatus(StrEnum):
    EXTRACTED = "extracted"
    USER_REVIEWED = "user_reviewed"
    PROFESSIONAL_VERIFIED = "professional_verified"
    REJECTED = "rejected"


REVIEWED_STATUSES = frozenset({SourceReviewStatus.USER_REVIEWED, SourceReviewStatus.PROFESSIONAL_VERIFIED})


class FieldName(StrEnum):
    COURSE_START_DATE = "course_start_date"
    COURSE_END_DATE = "course_end_date"
    MEDICATION_NAME = "medication_name"
    DOSE_AMOUNT = "dose_amount"
    DOSE_UNIT = "dose_unit"
    FREQUENCY_RULE = "frequency_rule"
    IS_PRN = "is_prn"
    ROUTE = "route"
    FOOD_INSTRUCTION = "food_instruction"
    STRENGTH = "strength"
    FORM = "form"


class IdentityStatus(StrEnum):
    UNVERIFIED = "unverified"
    USER_REVIEWED_DOCUMENT = "user_reviewed_document"
    PROFESSIONAL_VERIFIED = "professional_verified"


class RegimenState(StrEnum):
    """Regimen lifecycle states; historical states are immutable (SQL guard)."""

    DRAFT = "draft"
    PENDING_CLARIFICATION = "pending_clarification"
    ACTIVE = "active"
    ENDED = "ended"
    SUPERSEDED = "superseded"


class RuleKind(StrEnum):
    SCHEDULED = "scheduled"
    PRN = "prn"


class OccurrenceStatus(StrEnum):
    SCHEDULED = "scheduled"
    PAST_DUE = "past_due"
    CLOSED = "closed"


class IntakeStatus(StrEnum):
    """Self-reported only. ``reported_taken`` NEVER proves ingestion."""

    REPORTED_TAKEN = "reported_taken"
    REPORTED_NOT_TAKEN = "reported_not_taken"
    UNSURE = "unsure"
    NOT_REPORTED = "not_reported"


class VisualStatus(StrEnum):
    """Visual check outcome, independent from intake status."""

    NOT_CHECKED = "not_checked"
    VISUALLY_CONSISTENT = "visually_consistent"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    IMAGE_UNUSABLE = "image_unusable"


class AgentSessionState(StrEnum):
    COLLECTING = "collecting"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    EXPIRED = "expired"


class AgentIntent(StrEnum):
    REMINDER = "reminder"
    MEDICATION_ENROLLMENT = "medication_enrollment"
    DOSE_SELF_REPORT = "dose_self_report"
    #: "Have I taken my Amlodipine today?" — a read-only question about what
    #: has already been reported. It never records anything.
    DOSE_STATUS_QUERY = "dose_status_query"
    MEDICATION_HISTORY = "medication_history"
    CLARIFICATION = "clarification"


class PolicyRuleId(StrEnum):
    SOURCE_REVIEW_REQUIRED = "SOURCE_REVIEW_REQUIRED"
    COMPLETE_REGIMEN_REQUIRED = "COMPLETE_REGIMEN_REQUIRED"
    CURRENT_VERSION_REQUIRED = "CURRENT_VERSION_REQUIRED"
    EXPLICIT_CONFIRMATION_REQUIRED = "EXPLICIT_CONFIRMATION_REQUIRED"
    NO_DUPLICATE_EVENT = "NO_DUPLICATE_EVENT"
    SELF_REPORT_NOT_INGESTION = "SELF_REPORT_NOT_INGESTION"
    DEMO_ONLY = "DEMO_ONLY"


class ToolName(StrEnum):
    """Allowlisted agent tools; must match agent_tool_calls.tool_name CHECK."""

    RECONCILE_MEDICATION_SOURCES = "reconcile_medication_sources"

    CREATE_REMINDER = "create_reminder"
    GET_LONG_TERM_CARE = "get_long_term_care"
    PREPARE_CARE_ACTION = "prepare_care_action"
    LIST_ACTIVE_MEDICATIONS = "list_active_medications"
    GET_MEDICATION_HISTORY = "get_medication_history"
    #: Read-only lookup of what the patient has *reported* for one medication
    #: on the current local day. It writes nothing and never concludes that an
    #: unreported dose was missed.
    GET_DOSE_STATUS = "get_dose_status"
    ENROLL_MEDICATION_DRAFT = "enroll_medication_draft"
    CONFIRM_REGIMEN_DRAFT = "confirm_regimen_draft"
    CHECK_DUE_DOSE = "check_due_dose"
    RECORD_SELF_REPORT = "record_self_report"


class ToolStatus(StrEnum):
    STARTED = "started"
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    SIMULATED = "simulated"


class ErrorCode(StrEnum):
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    SOURCE_UNREVIEWED = "SOURCE_UNREVIEWED"
    INCOMPLETE_REGIMEN = "INCOMPLETE_REGIMEN"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"
    REGIMEN_OVERLAP = "REGIMEN_OVERLAP"
    STALE_VERSION = "STALE_VERSION"
    POLICY_BLOCKED = "POLICY_BLOCKED"
    INVALID_INPUT = "INVALID_INPUT"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"
