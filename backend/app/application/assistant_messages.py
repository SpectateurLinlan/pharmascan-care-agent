"""Single application entry for legacy and versioned Assistant messages."""

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import replace
from typing import Protocol
from uuid import UUID, uuid5

from pydantic import ValidationError as SchemaValidationError

from ..agent.knowledge_intent import medication_question
from ..agent.orchestrator import AgentOrchestrator, AgentReply, AgentTurn
from ..contracts.assistant_workflows import (
    EphemeralPayload,
    WorkflowEvent,
    WorkflowMessageInput,
    WorkflowMessageResult,
    WorkflowView,
)
from ..contracts.conversation_threads import ConversationMessage
from ..contracts.enums import AgentIntent
from ..contracts.ports import Clock
from ..contracts.workflow_messages import ConversationPersistencePort, ConversationWriteScope
from ..domain.errors import DomainError, NotFoundError, ValidationError
from ..domain.health_safety import needs_urgent_help_notice
from .assistant_navigation import resolve_navigation
from .assistant_workflows import WorkflowService
from .conversation_history import ConversationHistoryService
from .conversation_threads import ConversationThreadService
from .dosing import SelfReportService
from .enrollment import MedicationEnrollmentService
from .enrollment_collection import collect_enrollment_message, collection_control, outside_collection
from .media_collection import media_entry
from .preferences import PreferenceService
from .record_collection import record_entry
from .workflow_message_policy import DEFAULT_PERSISTENCE, MessagePersistencePolicy, retention_command


def _mark_failed(service, patient_id, turn_id, *, policy=DEFAULT_PERSISTENCE):
    try:
        service.fail(patient_id, turn_id, policy=policy)
    except DomainError as error:
        logging.getLogger("pharmascan.history").warning("Claim update unavailable: %s", type(error).__name__)


class MessageHandler(Protocol):
    def handle_turn(self, *, patient_id: UUID, session_id: UUID, turn: AgentTurn) -> AgentReply: ...


class AssistantMessageService:
    def __init__(
        self,
        *,
        orchestrator: AgentOrchestrator,
        handler: MessageHandler | None,
        enrollment: MedicationEnrollmentService,
        self_report: SelfReportService,
        preferences: PreferenceService,
        conversation_threads: ConversationThreadService,
        conversation_history: ConversationHistoryService,
        clock: Clock,
        workflows: WorkflowService | None,
        message_persistence: ConversationPersistencePort | None = None,
    ):
        self.orchestrator, self.ai_agent = orchestrator, handler
        self.enrollment, self.self_report, self.preferences = enrollment, self_report, preferences
        self.conversation_threads, self.conversation_history = conversation_threads, conversation_history
        self.clock, self.workflows = clock, workflows
        self.message_persistence = message_persistence

    def _guard(self, policy: MessagePersistencePolicy, owner: UUID, workflow: WorkflowView) -> MessagePersistencePolicy:
        if policy.messages is not None:
            return replace(policy, scope=ConversationWriteScope(task_id=workflow.task_id, revision=workflow.revision),
                           guard=lambda write: False)
        return replace(
            policy,
            guard=lambda write: self.workflows.guarded_write(
                owner,
                workflow.task_id,
                workflow.revision,
                write,
            ),
        )

    @staticmethod
    def _task_conversation(owner: UUID, task_id: UUID) -> UUID:
        return uuid5(owner, f"workflow-conversation:{task_id}")

    @staticmethod
    def _new_enrollment(payload: WorkflowMessageInput) -> bool:
        if (
            payload.workspace_id is None
            or payload.photo_context
            or payload.name_selection
            or payload.medication_selection
        ):
            return False
        text = unicodedata.normalize("NFKC", payload.text).strip().casefold()
        if needs_urgent_help_notice(text) or any(char in text for char in ('"', "“", "”", "?", "？")):
            return False
        return bool(
            re.fullmatch(
                r"(?:我(?:想|要|想要)?|请(?:帮我)?|帮我)?(?:添加|新增|登记)(?:一(?:种|个))?(?:药物|药品|药)[。！!]?"
                r"|(?:(?:i (?:want|would like) to|please) )?(?:add|register|enroll) "
                r"(?:a |a new |new )?(?:medicine|medication)[.!]?",
                text,
            )
        )

    @classmethod
    def _new_capability(cls, payload: WorkflowMessageInput) -> str | None:
        if cls._new_enrollment(payload):
            return "medication.enroll"
        if (
            payload.workspace_id is None
            or payload.photo_context
            or payload.name_selection
            or payload.medication_selection
            or needs_urgent_help_notice(payload.text)
        ):
            return None
        text = unicodedata.normalize("NFKC", payload.text).strip().casefold().rstrip("。.!！")
        records = media_entry(text) or record_entry(text)
        if records:
            return records
        if re.fullmatch(
            r"(?:请)?(?:修改|更改|调整)(?:用药|药物)计划|(?:please )?(?:change|edit|update) (?:a |my )?medication plan",
            text,
        ):
            return "medication.plan.change"
        if re.fullmatch(r"(?:请)?(?:添加|补充)药物来源|(?:please )?add (?:a )?medication source", text):
            return "medication.source.add"
        if re.fullmatch(r"(?:请)?(?:核对|查看|继续核对)药物来源|(?:please )?review medication sources?", text):
            return "medication.source.review"
        if re.fullmatch(r"(?:请)?(?:继续|恢复)(?:药物)?草稿|(?:please )?resume (?:a )?medication draft", text):
            return "medication.draft.resume"
        if re.fullmatch(r"(?:请)?删除(?:药物)?草稿|(?:please )?delete (?:a )?medication draft", text):
            return "medication.draft.delete"
        if re.fullmatch(r"(?:请)?停止追踪(?:用药计划|药物)|(?:please )?stop tracking (?:a )?medication", text):
            return "medication.plan.end"
        if re.fullmatch(
            r"(?:请)?(?:查看|查询)(?:我的)?(?:用药|药物)计划|(?:show|view|list)(?: my)? medication plans", text
        ):
            return "medication.plan.view"
        if re.fullmatch(
            r"(?:请)?(?:查看|查询)(?:未完成的?药物登记|未完成登记|药物草稿)"
            r"|(?:show|list|view)(?: my)? unfinished medication setup",
            text,
        ):
            return "medication.setup.list"
        return None

    @staticmethod
    def _event_id(value: str) -> UUID:
        # IDs are metadata, never a content hash in no-save mode.
        try:
            return UUID(value.removeprefix("turn-"))
        except ValueError:
            raise ValidationError("Workflow messages require a random UUID client turn ID") from None

    def _policy(
        self,
        owner: UUID,
        payload: WorkflowMessageInput,
    ) -> tuple[MessagePersistencePolicy, WorkflowView | None]:
        command = retention_command(payload.text)
        no_save = payload.save_mode == "ephemeral" or command == "cancel_save"
        workflow = None
        if payload.task_id is not None:
            if self.workflows is None:
                raise ValidationError("Assistant workflows are unavailable")
            control = self.workflows.control(owner, payload.task_id)
            canonical_retry = (
                payload.threaded
                and payload.conversation_id is None
                and control.conversation_id == self._task_conversation(owner, payload.task_id)
            )
            if control.workspace_id != payload.workspace_id or (
                control.conversation_id != payload.conversation_id and not canonical_retry
            ):
                raise ValidationError("Workflow belongs to another workspace or conversation")
            no_save = no_save or control.mode == "ephemeral"
            workflow = self.workflows.view(owner, payload.task_id)
            if control.mode == "ephemeral" and payload.ephemeral is not None:
                workflow = self.workflows.preview(owner, payload.task_id, payload.ephemeral)
        if payload.ephemeral is not None and not no_save:
            raise ValidationError("Saved messages do not accept replacement page fields")
        policy = MessagePersistencePolicy(save_history=not no_save, save_context=not no_save, save_task=not no_save,
                    messages=self.message_persistence,
                    guard=(lambda write: False) if self.message_persistence else None)
        return (self._guard(policy, owner, workflow) if workflow else policy), workflow

    def _is_workflow_turn(self, payload: WorkflowMessageInput, workflow: WorkflowView | None = None) -> bool:
        return bool(
            self.workflows
            and (
                self._new_capability(payload)
                or (payload.task_id and (retention_command(payload.text) or collection_control(payload.text)))
            )
            or workflow
            and payload.task_id
            and workflow.capability_id in {"medication.enroll", "medication.draft.resume", "medication.plan.change"}
            and workflow.state not in {"suspended", "cancelled", "completed"}
            and not payload.photo_context
            and not outside_collection(payload.text)
            and (
                not medication_question(payload.text)
                or collect_enrollment_message(
                    payload.text,
                    workflow.visible_fields,
                    workflow.missing_fields,
                    replace_recorded_times=workflow.capability_id == "medication.plan.change",
                )
            )
        )

    def _workflow_turn(
        self,
        owner: UUID,
        payload: WorkflowMessageInput,
        workflow: WorkflowView | None,
        policy: MessagePersistencePolicy,
        conversation_id: UUID | None,
    ) -> WorkflowView | None:
        if self.workflows is None:
            return workflow
        if payload.task_id and workflow and collection_control(payload.text):
            if payload.expected_revision is None:
                raise ValidationError("Task controls need the current revision")
            return self.workflows.advance(
                owner,
                payload.task_id,
                WorkflowEvent(
                    event_id=self._event_id(payload.client_turn_id),
                    expected_revision=payload.expected_revision,
                    kind=collection_control(payload.text),
                ),
                ephemeral=payload.ephemeral.model_dump(mode="json") if payload.ephemeral else None,
            )
        if payload.task_id and retention_command(payload.text):
            if payload.expected_revision is None:
                raise ValidationError("A workflow event needs its current revision")
            return self.workflows.advance(
                owner,
                payload.task_id,
                WorkflowEvent(
                    event_id=self._event_id(payload.client_turn_id),
                    expected_revision=payload.expected_revision,
                    kind=retention_command(payload.text),
                ),
                ephemeral=payload.ephemeral.model_dump(mode="json") if payload.ephemeral else None,
            )
        if capability := self._new_capability(payload):
            return self.workflows.start(
                owner,
                capability,
                payload.workspace_id,
                conversation_id,
                {},
                "allowed" if policy.can_save_task else "ephemeral",
                client_event_id=self._event_id(payload.client_turn_id),
            )
        if (
            payload.task_id
            and workflow
            and workflow.capability_id in {"medication.enroll", "medication.draft.resume", "medication.plan.change"}
            and workflow.state in {"choose_method", "collecting", "ready_for_review", "failed_recoverable"}
            and not payload.photo_context
            and not needs_urgent_help_notice(payload.text)
            and not outside_collection(payload.text)
        ):
            values = collect_enrollment_message(
                payload.text,
                workflow.visible_fields,
                workflow.missing_fields,
                replace_recorded_times=workflow.capability_id == "medication.plan.change",
            )
            if values and workflow.capability_id == "medication.plan.change":
                from ..contracts.medication_plan_changes import PlanChangeDetails

                if any(key not in PlanChangeDetails.model_fields for key in values):
                    raise ValidationError(
                        "Product identity cannot change here. Use medication sources for product changes"
                    )
                current = workflow.visible_fields.get("change_inputs")
                values = {"details": {**current, **values}} if isinstance(current, dict) else {}
            if values and workflow.capability_id == "medication.draft.resume":
                current = workflow.visible_fields.get("recovery_inputs")
                values = {"details": {**current, **values}} if isinstance(current, dict) else {}
            if values:
                if payload.expected_revision is None:
                    raise ValidationError("Providing workflow details needs the current revision")
                return self.workflows.advance(
                    owner,
                    payload.task_id,
                    WorkflowEvent(
                        event_id=self._event_id(payload.client_turn_id),
                        expected_revision=payload.expected_revision,
                        kind="provide_fields",
                        values=values,
                    ),
                    ephemeral=payload.ephemeral.model_dump(mode="json") if payload.ephemeral else None,
                )
        if (
            payload.task_id
            and workflow
            and workflow.state not in {"suspended", "cancelled", "completed"}
            and (medication_question(payload.text) or outside_collection(payload.text))
        ):
            if payload.expected_revision is None:
                raise ValidationError("Switching topics needs the current workflow revision")
            return self.workflows.advance(
                owner,
                payload.task_id,
                WorkflowEvent(
                    event_id=self._event_id(payload.client_turn_id),
                    expected_revision=payload.expected_revision,
                    kind="pause",
                ),
                ephemeral=payload.ephemeral.model_dump(mode="json") if payload.ephemeral else None,
            )
        return workflow

    @staticmethod
    def _workflow_text(workflow: WorkflowView, language: str) -> str:
        from ..contracts.care_workflow import CARE_READ_IDS, CARE_SCHEMAS
        from ..contracts.media_workflow import MEDIA_CHANGE_SCHEMAS, MEDIA_READ_SCHEMAS

        if workflow.capability_id.startswith("conversation."):
            return ("请在下方查看或选择会话。切换与清除需要单独确认；已保存草稿和药物记录会保留，旧确认不会恢复。"
                    if language == "zh" else "View or select a conversation below. Switching or clearing needs "
                    "separate confirmation. Saved drafts and medication records remain; "
                    "old confirmations are not restored.")
        if workflow.capability_id == "assistant.usage":
            return ("以下显示当前可读取的助手用量。服务不可用不表示额度为零。" if language == "zh"
                    else "Current assistant usage is shown below when available. "
                    "Unavailability does not mean zero quota.")
        if workflow.capability_id.startswith("speech."):
            return ("请手动开启语音输入或朗读。转写进入消息框后可修改，仍需您手动发送；使用现有语音设置。"
                    if language == "zh" else "Start voice input or playback explicitly. Transcripts remain editable "
                    "in the message box until you press Send. Your existing voice settings apply.")
        if workflow.capability_id == "feedback.submit":
            return ("请填写应用反馈，再独立核对确认保存。保存不表示已发送邮件或已获审阅。" if language == "zh"
                    else "Enter app feedback, then review and confirm separately. "
                    "Saving does not mean it was emailed or reviewed.")
        if workflow.capability_id in {"help.open", "guide.start", "navigation.open"}:
            return ("请在下方明确打开帮助、应用导览或选择的应用页面。" if language == "zh"
                    else "Explicitly open help, the app guide or the selected app page below.")

        if workflow.capability_id.startswith("account."):
            return ("请打开安全账户表单继续。密码和验证码只交给原有账户服务，不进入 Assistant 办理记录。"
                    if language == "zh" else "Open the secure account form to continue. Passwords and verification "
                    "codes go only to the existing account service, not the Assistant task.")
        if workflow.capability_id in {"profile.view", "caregiver.list"}:
            return ("以下显示您当前保存的个人资料或关怀联系人。联系人尚未独立验证，也未开启共享权限。"
                    if language == "zh" else "Your current saved profile or care contacts are shown below. "
                    "Contacts are not independently verified and have no record-sharing access.")
        if workflow.capability_id.startswith("preference.") or workflow.capability_id in {
                "profile.edit", "caregiver.add", "caregiver.edit", "caregiver.delete"}:
            return ("请在下方填写变更，再独立核对确认后保存。提交联系人资料前需要明确同意存储。"
                    if language == "zh" else "Enter the changes below, then review and confirm separately before "
                    "saving. Contact details require explicit storage permission before submission.")
        if workflow.capability_id in {"notification.subscribe", "notification.unsubscribe", "notification.test"}:
            return ("请在下方打开当前设备的通知操作，核查状态后再明确确认。浏览器权限、订阅和实际送达会分别显示。"
                    if language == "zh" else "Open the current-device notification action below, check its status "
                    "and confirm explicitly. Browser permission, subscription and actual delivery are separate.")
        if workflow.capability_id in {"reminder.snooze", "reminder.settings"}:
            return ("请在下方选择提醒并填写变更，再通过独立核对确认保存。稍后提醒不会修改用药计划或记录服药。"
                    if language == "zh" else "Choose the reminder and enter changes below, then review and confirm "
                    "separately. Snoozing does not change the medication plan or record a dose.")
        if workflow.capability_id in {"reminder.list", "reminder.calendar.export", "notification.status"}:
            return ("请在下方查看提醒、选择日历导出选项或手动核查设备状态。这不会记录服药或发送通知。"
                    if language == "zh" else "Review reminders, choose calendar options or explicitly check "
                    "device status "
                    "below. This does not record a dose or send a notification.")
        if workflow.capability_id == "source.preview":
            return ("请选择来源类型和照片，并明确同意后预览提取内容。预览仍需与原文核对，不会保存药物或修改用药计划。"
                    if language == "zh" else "Choose the source type and image, then explicitly allow a preview. "
                    "Check the extraction against the original; this does not save a medication or change a plan.")
        if workflow.capability_id == "image.compare":
            return ("请选择比对方式和照片，确认处理同意后再开始。外观结果不确认药物身份、剂量或已经服药。"
                    if language == "zh" else "Choose the photo check and image below, "
                    "then explicitly allow processing. "
                    "Visual evidence does not confirm medication identity, dosage or ingestion.")
        if workflow.capability_id == "library.pdf.add":
            return ("请选择药物和 PDF 文件，原文件按本次保存设置保留。加入资料库仍需单独确认，不会读取或更改用药计划。"
                    if language == "zh" else "Choose the medication and PDF below. The original follows this task's "
                    "saving preference. Confirm separately to add it to the library; no medication instructions "
                    "are extracted or changed.")
        if workflow.capability_id == "gallery.photo.add":
            return ("请先选择药物和照片，原图会按本次保存设置保留。添加到图库仍需您核对并单独确认。"
                    if language == "zh" else "Choose the medication and photo below. The original follows this task's "
                    "saving preference. Review and confirm separately before adding it to the gallery.")
        if workflow.capability_id in MEDIA_CHANGE_SCHEMAS:
            return ("请在下方选择照片或文件并核对操作，保存仍需您单独确认。" if language == "zh"
                    else "Choose the photo or document below, review the action and confirm separately before saving.")

        if workflow.capability_id in MEDIA_READ_SCHEMAS and workflow.state not in {
            "suspended", "cancelled", "outcome_unknown",
        }:
            if workflow.capability_id == "gallery.list":
                return ("已查询您已保存的药物照片，结果见下方。" if language == "zh"
                        else "I checked your saved medication photos; the results appear below.")
            return ("请在下方选择药物和原件。本次只查看已保存文件，不会修改您的药物记录。" if language == "zh"
                    else "Choose the medication and original file below. "
                    "This only views saved files and does not change your medication records.")
        if workflow.capability_id in CARE_SCHEMAS:
            if workflow.capability_id in CARE_READ_IDS:
                return ("已查询您的关怀记录，结果见下方。" if language == "zh"
                        else "I checked your recorded care information; the results appear below.")
            return ("请补充下方资料并核对，保存仍需您单独确认。" if language == "zh"
                    else "Complete the details below, review them and confirm separately before saving.")
        if workflow.capability_id == "medication.knowledge":
            return (
                "请在下方填写药物名称，确认相似药名后点击查询公开来源。此入口只查一般用途，不会修改您的药物记录。"
                if language == "zh"
                else "Enter the medicine name below, confirm any similar-name suggestion, "
                "then choose to search public sources. This checks general uses and does not change medication records."
            )
        if workflow.capability_id in {"dose.late.review", "dose.correction.review"}:
            return (
                "请选择已有登记剂次，通过下方患者表单补记或更正，核对后单独确认。原始记录会保留。"
                if language == "zh"
                else "Choose an existing occurrence, then use the patient form below to review "
                "and independently confirm your report. Original records are retained."
            )
        if workflow.capability_id in {"dose.report", "dose.prn.report"}:
            if workflow.state == "completed":
                return (
                    "已确认保存您的服药自述，记录的是您的陈述。"
                    if language == "zh"
                    else "Your patient dose report was saved after your confirmation."
                )
            return (
                "请选择登记计划，再通过下方自述按钮核对并单独确认。当前尚未保存服药自述。"
                if language == "zh"
                else "Choose a recorded plan, then review and confirm your patient response below. "
                "No dose report has been saved yet."
            )
        from ..contracts.medication_records import RECORD_READ_SCHEMAS

        if workflow.capability_id in RECORD_READ_SCHEMAS:
            if "medication_id" in workflow.missing_fields:
                return (
                    "已读取您的药物登记，请在下方选择要查询的药物。"
                    if language == "zh"
                    else "I checked your medication registrations. Choose a medicine to query below."
                )
            if "regimen_id" in workflow.missing_fields:
                return (
                    "请选择要统计的已登记疗程。"
                    if language == "zh"
                    else "Choose the recorded course to summarize below."
                )
            if workflow.capability_id == "medication.source.view":
                return (
                    "已读取这项药物的原始登记来源及核对状态，详情见下方。"
                    if language == "zh"
                    else "I read this medicine's original registration sources and review states, shown below."
                )
            if workflow.capability_id == "medication.instructions":
                return (
                    "已查询这项药物当前有效且已核对的个人服用说明，结果见下方。"
                    if language == "zh"
                    else "I checked the current patient-reviewed instructions for this medicine, shown below."
                )
            if workflow.capability_id in {"record.summary", "record.visit.prepare"}:
                return (
                    "已根据现有计划与患者自述生成统计。查询时段、覆盖范围和复诊问题见下方。"
                    if language == "zh"
                    else "I summarized your stored plans and patient reports. "
                    "The window, coverage and visit questions appear below."
                )
            return (
                "已查询登记计划与已存的患者自述。具体药物、时间、状态及查询范围见下方。"
                if language == "zh"
                else "I queried your recorded plans and stored patient reports. "
                "Medicines, times, states and query scope appear below."
            )
        if workflow.state == "choose_method":
            return (
                "您希望手动录入，还是拍照识别药物资料？"
                if language == "zh"
                else ("How would you like to add this medication: enter the details manually or use a photo?")
            )
        if workflow.storage_state == "save_failed":
            return (
                "尚未保存，请核对输入后重试。"
                if language == "zh"
                else "Saving did not finish. Review the input and retry."
            )
        prefix = (
            ("本次不保存，资料仅保留在当前页面。" if language == "zh" else "Details stay on this page without saving. ")
            if workflow.save_mode == "ephemeral"
            else ""
        )
        if workflow.capability_id == "medication.draft.delete":
            if workflow.prompt_key == "assistant.medication.deletion_unknown":
                return prefix + (
                    "删除结果尚未确认，请核查办理状态；记录暂时不可见不代表已删除。"
                    if language == "zh"
                    else "The deletion result is unknown. Check task status; "
                    "a missing record does not confirm deletion."
                )
            if workflow.visible_fields.get("deleted") is True:
                if workflow.visible_fields.get("cleanup_pending") is True:
                    return prefix + (
                        "草稿已删除，照片清理仍需重试。"
                        if language == "zh"
                        else "The draft was deleted. Photo cleanup still needs a retry."
                    )
                return prefix + (
                    "草稿已删除，已确认的历史记录已保留。"
                    if language == "zh"
                    else "The draft was deleted. Confirmed history is retained."
                )
            if workflow.prompt_key == "assistant.medication.no_drafts":
                return prefix + (
                    "没有找到未完成的药物草稿。" if language == "zh" else "No unfinished medication drafts were found."
                )
            return prefix + (
                "请选择并核对要删除的未完成登记，删除需要您单独确认。"
                if language == "zh"
                else "Choose and review the unfinished registration to delete. Deletion requires separate confirmation."
            )
        if workflow.capability_id == "medication.plan.end":
            if workflow.prompt_key == "assistant.medication.no_active":
                return prefix + (
                    "当前没有可停止追踪的已启用计划。"
                    if language == "zh"
                    else "There are no active recorded plans to stop tracking."
                )
            if workflow.state == "completed":
                return prefix + (
                    "这项记录中的计划已结束，历史记录已保留。"
                    if language == "zh"
                    else "This recorded plan has ended. Past records are retained."
                )
            return prefix + (
                "请选择并核对要停止追踪的计划，仍需您单独确认；这不会建议您改变实际用药。"
                if language == "zh"
                else "Choose and review the recorded plan to stop tracking. "
                "Separate confirmation is required; this does not advise changing your medication."
            )
        if workflow.capability_id in {"medication.plan.view", "medication.setup.list"}:
            if workflow.missing_fields:
                return prefix + (
                    "已查询您账户里的药物，请选择要查看的记录。"
                    if language == "zh"
                    else "I checked the medication records in your account. Choose a record to view."
                )
            return prefix + (
                "已查询您账户里的用药计划与登记进度，结果见下方。计划状态以记录中显示为准。"
                if language == "zh"
                else "I checked your recorded medication plans and setup progress. "
                "The current results and plan states appear below."
            )
        if workflow.capability_id == "medication.plan.change":
            if workflow.state == "completed":
                return prefix + (
                    "新计划已启用，旧计划及其历史记录已保留。"
                    if language == "zh"
                    else "The new plan is active. The previous version and its history are retained."
                )
            if "regimen_id" in workflow.missing_fields:
                return prefix + (
                    "请在下方选择说明发生变化的已登记计划。"
                    if language == "zh"
                    else "Choose the recorded plan whose instructions changed below."
                )
            return prefix + (
                "请按原标签或医护人员的说明填写变更。药物身份保持不变；核对并单独确认新版本之前，原计划不会被替换。"
                if language == "zh"
                else "Enter the changed instructions from your original label or clinician. "
                "Product identity stays fixed. "
                "The original plan is replaced only after separate review and confirmation."
            )
        if workflow.capability_id == "medication.draft.resume":
            if workflow.prompt_key == "assistant.medication.resume_source":
                return prefix + (
                    "这份草稿需要先核对原来源登记，Assistant 暂无法办理这类来源核对。"
                    if language == "zh"
                    else "This draft belongs to a source registration and needs evidence reconciliation. "
                    "This review is currently unavailable in Assistant."
                )
            if workflow.prompt_key == "assistant.medication.resume_original":
                return prefix + (
                    "已找到原来的登记任务。请点击下方继续，原图与核对进度将保留。"
                    if language == "zh"
                    else "I found the original saved enrollment. "
                    "Continue it below to retain its photos and review progress."
                )
            if workflow.prompt_key == "assistant.medication.original_unavailable":
                return prefix + (
                    "无法恢复原登记任务，请核查其保存许可和当前状态；不会将它转移到新任务。"
                    if language == "zh"
                    else "The original enrollment cannot be resumed. Check its saving permission and status."
                )
            if workflow.missing_fields == ("regimen_id",):
                return prefix + (
                    "已查询未完成的用药计划，请选择要继续的草稿。"
                    if language == "zh"
                    else "I checked unfinished medication plans. Choose the draft to continue."
                )
        if workflow.state == "outcome_unknown":
            return prefix + (
                "上次请求的结果尚未确认，请先核查原图或识别结果。"
                if language == "zh"
                else "The previous result is not confirmed. Check the original or recognition status first."
            )
        if workflow.state == "suspended":
            return prefix + (
                "已暂停办理，您可以稍后继续补充资料。"
                if language == "zh"
                else "This task is paused. You can resume it later."
            )
        questions = {
            "medication_name": (
                "请按药袋或处方输入药物名称。",
                "Enter the medication name from its label or prescription.",
            ),
            "dose_amount": (
                "请按原始说明输入每次用量；我不会替您推测。",
                "Enter the amount per dose from the original instructions; I will not guess it.",
            ),
            "dose_unit": (
                "每次用量使用什么单位，例如片、粒、毫克或毫升？",
                "Which unit accompanies each dose: tablets, capsules, mg or mL?",
            ),
            "frequency_rule": (
                "请按原始说明输入服用频率，例如每日几次、每隔几小时或按需服用。",
                "Enter the recorded frequency, such as times per day, hours between doses, or as needed.",
            ),
            "frequency_local_times": (
                "请按原始说明补充服用的具体时间（HH:MM，可输入多个）。",
                "Enter the recorded dose times in HH:MM format; you can enter several times together.",
            ),
            "frequency_days_of_week": (
                "请补充原始说明指定的星期。",
                "Enter the weekdays specified in the original instructions.",
            ),
            "frequency_every_hours": (
                "原始说明写的是每隔多少小时服用？",
                "How many hours between doses are recorded in the instructions?",
            ),
            "course_start_date": (
                "请填写首次服用或疗程开始的日期（YYYY-MM-DD）。",
                "Enter the first-dose or course start date in YYYY-MM-DD format.",
            ),
            "food_instruction": (
                "请按原始说明补充按需服用的条件或指示。",
                "Enter the recorded condition or guidance for taking it as needed.",
            ),
            "source_image": (
                "请上传药物标签或处方原图，也可以明确选择改为手动录入。",
                "Upload the original label or prescription photo, or choose manual entry.",
            ),
            "source_extraction": (
                "原图已保存，但暂时无法识别资料。您可以核查原图、重试识别或改为手动补充。",
                "The original is saved, but recognition failed. "
                "Check the photo, retry recognition, or switch to manual entry.",
            ),
            "processing_consent": (
                "原图已保存，如需识别请单独同意图片处理。",
                "The original is saved. Allow photo processing separately if you want recognition.",
            ),
            "source_product_limit": (
                "原图已保存，但一张图识别出超过20个产品，无法完整列出。请改为手动录入这项药物。",
                "The original is saved, but it contains more than 20 products. "
                "Switch to manual entry for this medication.",
            ),
            "existing_medication_choice": (
                "找到同名药物，请选择已有记录；若是另一种产品，请重填包含规格的名称。",
                "Choose the matching existing record, or enter a different product name including its strength.",
            ),
        }
        if workflow.missing_fields and workflow.missing_fields[0] in questions:
            return prefix + questions[workflow.missing_fields[0]][0 if language == "zh" else 1]
        if workflow.prompt_key == "assistant.enrollment.interval_default":
            return prefix + (
                "未填写首次时间，应用将按原流程使用08:00，并标明这是默认值。请对照原始说明核对，仍需单独确认。"
                if language == "zh"
                else "The first time was not supplied. The app will use its existing 08:00 default "
                "and label it as a default. "
                "Review the original instructions before separate confirmation."
            )
        return prefix + (
            "资料已整理，请对照原始说明核对；尚未启用用药计划。"
            if language == "zh"
            else "The details are ready for review against the original instructions. "
            "The medication plan has not been activated."
        )

    def handle(self, owner: UUID, payload: WorkflowMessageInput) -> WorkflowMessageResult:
        patient_id = owner
        policy, workflow = self._policy(owner, payload)
        navigation = (
            resolve_navigation(self.enrollment, patient_id, payload.navigation_context)
            if payload.navigation_context
            else None
        )
        threaded = payload.threaded
        thread_service = self.conversation_threads
        saving = bool(self.preferences.get(patient_id).conversation_history_enabled) and policy.save_history
        conversation_id = payload.conversation_id if threaded else None
        operation_payload = payload
        if threaded and payload.task_id and conversation_id is None:
            conversation_id = self.workflows.control(owner, payload.task_id).conversation_id
        if conversation_id:
            thread_service.require(patient_id, conversation_id)
        if threaded and saving and conversation_id is None:
            conversation_id = (
                self._task_conversation(owner, payload.task_id)
                if payload.task_id
                else uuid5(patient_id, "conversation:" + payload.client_turn_id)
            )
            created = thread_service.create(
                patient_id, conversation_id, payload.text, bool(payload.photo_context), policy=policy
            )
            if not created:
                saving, conversation_id = False, None
            elif payload.task_id:
                workflow = self.workflows.bind_conversation(owner, payload.task_id, workflow.revision, conversation_id)
                policy = self._guard(policy, owner, workflow)
                operation_payload = payload.model_copy(update={"expected_revision": workflow.revision})
        key = str(payload.slots.get("idempotency_key", f"turn-{payload.client_turn_id}"))
        prior = self.self_report.find_confirmation(patient_id=patient_id, idempotency_key=key)
        session_id: UUID = payload.session_id or (
            prior.session_id
            if prior is not None and prior.action == "record_self_report"
            else self.orchestrator.start_session(patient_id=patient_id, persistence=policy).id
        )
        if threaded and conversation_id:
            session = self.orchestrator.get_session(patient_id=patient_id, session_id=session_id)
            if session is None or session.state == "expired" or session.expires_at <= self.clock.now():
                session = self.orchestrator.start_session(patient_id=patient_id, persistence=policy)
                session_id = session.id
            if session.conversation_id is None:
                # Never bind an existing executable confirmation from another context.
                if session.state != "collecting" or session.context.recent_turns:
                    session = self.orchestrator.start_session(patient_id=patient_id, persistence=policy)
                    session_id = session.id
                thread_service.bind(patient_id, conversation_id, session_id, restore=True, policy=policy)
            elif session.conversation_id != conversation_id:
                raise ValidationError("Session belongs to another conversation")
        turn_id = uuid5(conversation_id, payload.client_turn_id) if threaded and conversation_id else None
        if turn_id and saving:
            digest = hashlib.sha256(
                json.dumps(
                    payload.model_dump(mode="json", exclude={"session_id", "client_id", "conversation_id"}),
                    sort_keys=True,
                ).encode()
            ).hexdigest()
            claimed = thread_service.claim(patient_id, conversation_id, turn_id, digest, policy=policy)
            if claimed == "completed":
                saved = thread_service.message(patient_id, turn_id)
                if saved is None:
                    raise NotFoundError("Saved message unavailable for this patient")
                if self.workflows is not None and self._new_capability(payload):
                    workflow = self.workflows.started(
                        owner, payload.workspace_id, self._event_id(payload.client_turn_id)
                    )
                return WorkflowMessageResult(
                    conversation_id=conversation_id,
                    history_saved=True,
                    workflow=workflow,
                    reply=AgentReply(
                        message=saved.assistant_text,
                        intent=AgentIntent.CLARIFICATION,
                        session_id=session_id,
                        session_state="collecting",
                        mode="records_only",
                    ),
                )
            if claimed == "revoked":
                saving = False
            elif claimed != "new":
                raise ValidationError(
                    "This message is already processing or failed. Check the conversation before sending again."
                )

        turn = AgentTurn(
            text=payload.text,
            language=self.preferences.get(patient_id).preferred_language if self.preferences else payload.language,
            slots={**payload.slots, "client_turn_id": payload.client_turn_id},
            photo_context=payload.photo_context,
            navigation_context=navigation,
            medication_selection=payload.medication_selection,
            name_selection=payload.name_selection,
            persistence=policy,
        )
        handler = self.ai_agent or self.orchestrator
        try:
            previous_workflow = workflow
            workflow = self._workflow_turn(owner, operation_payload, workflow, policy, conversation_id)
            if workflow is not None and workflow is not previous_workflow:
                policy = self._guard(policy, owner, workflow)
                turn = replace(turn, persistence=policy)
            if (
                workflow is not None
                and self._is_workflow_turn(payload, workflow)
                and not needs_urgent_help_notice(payload.text)
            ):
                reply = AgentReply(
                    message=self._workflow_text(workflow, turn.language),
                    intent=AgentIntent.MEDICATION_ENROLLMENT,
                    session_id=session_id,
                    session_state="collecting",
                    mode="workflow",
                )
            else:
                reply = handler.handle_turn(patient_id=patient_id, session_id=session_id, turn=turn)
        except Exception:
            if turn_id and saving:
                _mark_failed(thread_service, patient_id, turn_id, policy=policy)
            raise
        history_saved = None
        if threaded and saving:
            try:
                history_saved = thread_service.append(
                    patient_id,
                    reply.session_id,
                    ConversationMessage(
                        id=turn_id,
                        conversation_id=conversation_id,
                        user_text=payload.text,
                        assistant_text=reply.message,
                        photo_attached=bool(payload.photo_context),
                        created_at=self.clock.now(),
                    ),
                    policy=policy,
                )
            except (DomainError, SchemaValidationError) as error:
                logging.getLogger("pharmascan.history").warning("Thread save unavailable: %s", type(error).__name__)
                _mark_failed(thread_service, patient_id, turn_id, policy=policy)
                history_saved = False
        elif not threaded and self.conversation_history and saving:
            try:
                history_saved = self.conversation_history.append(
                    patient_id,
                    reply.session_id,
                    payload.client_turn_id,
                    turn.patient_text,
                    reply.message,
                    policy=policy,
                )
            except DomainError as error:
                # The actual reply/confirmation must survive a history-storage failure.
                logging.getLogger("pharmascan.history").warning("History unavailable: %s", type(error).__name__)
                history_saved = False
        if workflow is not None:
            control = self.workflows.control(owner, workflow.task_id)
            if control.revision != workflow.revision:
                workflow = (
                    self.workflows.preview(
                        owner,
                        workflow.task_id,
                        EphemeralPayload(
                            capability_id=workflow.capability_id,
                            fields=workflow.visible_fields,
                        ),
                    )
                    if control.mode == "ephemeral"
                    else self.workflows.view(owner, workflow.task_id)
                )
        return WorkflowMessageResult(
            reply=reply, conversation_id=conversation_id, history_saved=history_saved, workflow=workflow
        )
