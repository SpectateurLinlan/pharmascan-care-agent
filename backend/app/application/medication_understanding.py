"""Explain general label uses separately from current patient-reviewed instructions."""

from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from ..contracts.enums import IdentityStatus, SourceReviewStatus
from ..contracts.medication_knowledge import (
    KnowledgeProduct,
    MedicationKnowledgeProvider,
    MedicationUnderstanding,
    ReviewedInstructions,
)
from ..contracts.ports import Clock
from ..domain.errors import NotFoundError
from .enrollment import MedicationEnrollmentService
from .medication_presentation import general_use_text, knowledge_scope

REVIEWED = {SourceReviewStatus.USER_REVIEWED, SourceReviewStatus.PROFESSIONAL_VERIFIED}


class MedicationUnderstandingService:
    def __init__(self, enrollment: MedicationEnrollmentService, provider: MedicationKnowledgeProvider, clock: Clock):
        self._enrollment, self._provider, self._clock = enrollment, provider, clock

    def explain(
        self,
        *,
        patient_id: UUID,
        medication_id: UUID | None = None,
        medication_name: str | None = None,
        question: Literal["general_use", "personal_instructions", "personal_reason"] = "general_use",
        language: str = "en",
        timezone: str = "Asia/Singapore",
    ) -> MedicationUnderstanding:
        """Patient scope is server supplied. This service has no mutation capability.

        Personal-instructions questions never call the general knowledge provider.
        A reviewed label indication does not prove the prescriber's personal reason.
        """
        medication = self._enrollment.get_medication(patient_id, medication_id) if medication_id else None
        if medication_id and medication is None:
            raise NotFoundError("Medication not found for this patient")
        if medication is None and medication_name:
            needle = medication_name.strip().casefold()
            rows = self._enrollment.list_medications(patient_id)
            exact = [row for row in rows if row.display_name.casefold() == needle]
            found = exact or [row for row in rows if needle in row.display_name.casefold()]
            if len(found) == 1:
                medication = found[0]
            elif len(found) > 1 and question != "general_use":
                return MedicationUnderstanding(
                    clarification_required=True,
                    question=question,
                    medication_name=medication_name,
                    patient_safe_summary="有多项用药符合这个名称，请选择具体药物、规格和剂型。"
                    if language == "zh"
                    else "More than one medicine matches. Please choose the product, strength and form.",
                )
        name = medication.display_name if medication else medication_name
        regimen = self._enrollment.find_active_regimen(patient_id, medication.id) if medication else None
        source_id = (regimen.source_id if regimen else medication.source_id) if medication else None
        source = self._enrollment.get_source(patient_id, source_id) if source_id else None
        reviewed = (
            source is not None
            and source.review_status in REVIEWED
            and medication is not None
            and medication.identity_status
            in {IdentityStatus.USER_REVIEWED_DOCUMENT, IdentityStatus.PROFESSIONAL_VERIFIED}
        )
        now = self._clock.now()
        local_date = now.astimezone(ZoneInfo(timezone)).date()
        current = (
            regimen is not None
            and medication.archived_at is None
            and (
                (regimen.effective_from is None or regimen.effective_from <= now)
                and (regimen.effective_to is None or regimen.effective_to > now)
                and (regimen.course_start_date is None or regimen.course_start_date <= local_date)
                and (regimen.course_end_date is None or regimen.course_end_date >= local_date)
            )
        )
        instructions = None
        candidate = None
        if reviewed and source.extraction_evidence and len(source.extraction_evidence.candidates) == 1:
            candidate = source.extraction_evidence.candidates[0]
        if (
            current
            and reviewed
            and regimen.dose_amount is not None
            and regimen.dose_unit
            and (regimen.is_prn or regimen.frequency_rule)
        ):
            printed = candidate.regimen_evidence.instructions if candidate else None
            basis = source.dose_basis
            instructions = ReviewedInstructions(
                regimen_id=regimen.id,
                version=regimen.version_no,
                source_document_id=source.id,
                review_status=source.review_status.value,
                source_kind=source.source_kind.value,
                dose_amount=regimen.dose_amount,
                dose_unit=regimen.dose_unit,
                frequency_rule=regimen.frequency_rule,
                is_prn=regimen.is_prn,
                route=regimen.route,
                food_instruction=regimen.food_instruction,
                course_start_date=regimen.course_start_date.isoformat() if regimen.course_start_date else None,
                course_end_date=regimen.course_end_date.isoformat() if regimen.course_end_date else None,
                original_instructions=printed.text
                if printed
                else (basis.instructions_text if basis and basis.patient_checked else None),
                original_line=printed.line if printed else None,
            )
        result = MedicationUnderstanding(
            medication_id=medication.id if current else None,
            regimen_id=regimen.id if current else None,
            question=question,
            medication_name=name,
            personal_instructions=instructions if question == "personal_instructions" else None,
            patient_safe_summary="",
        )
        if question == "personal_instructions":
            summary = self._instructions_summary(name, instructions, language)
            return result.model_copy(update={"patient_safe_summary": summary})
        if not name:
            return result.model_copy(
                update={
                    "patient_safe_summary": "请选择或说出具体药物。"
                    if language == "zh"
                    else "Please name or choose the medication."
                }
            )
        basis = source.dose_basis if reviewed else None
        product = candidate.product if candidate else None
        query = KnowledgeProduct(
            scope="ingredient" if question == "general_use" else "product",
            name=product.name if product else name,
            rxcui=product.rxcui if product else None,
            ingredients=[row.name for row in product.ingredients] if product else [],
            form=basis.form
            if basis and basis.patient_checked
            else (product.dose_form.value.lower().removesuffix("s") if product and product.dose_form else None),
            route=regimen.route if reviewed and regimen else None,
            strength=product.strength
            if product
            else (basis.strength_text if basis and basis.patient_checked else None),
            release=(
                "modified_release"
                if product.release == "ER"
                else "enteric"
                if product.release == "DR"
                else basis.formulation
                if basis and basis.patient_checked
                else "unknown"
            )
            if product
            else (basis.formulation if basis and basis.patient_checked else "unknown"),
        )
        knowledge = self._provider.lookup(query)
        if knowledge.status == "matched":
            explanation = general_use_text(knowledge, language)
        else:
            explanation = (
                "暂时无法从来源可靠确认一般用途，可能存在成分不匹配、来源冲突或服务不可用；请核对原标签或咨询药剂师。"
                if language == "zh"
                else "I could not reliably confirm a general use: the ingredient may not match, sources may conflict, "
                "or the service may be unavailable. Check the original label with your pharmacist."
            )
        summary = f"{name}{'：' if language == 'zh' else ': '}{explanation}"
        if knowledge.status == "matched":
            summary += "\n\n" + knowledge_scope(language)
        if question == "personal_reason":
            summary = (
                "记录尚未确认医生为您开药的个人原因。 "
                if language == "zh"
                else "Your record does not establish why your prescriber chose this medicine for you. "
            ) + summary
        return result.model_copy(update={"general_knowledge": knowledge, "patient_safe_summary": summary})

    @staticmethod
    def _instructions_summary(name: str | None, instructions: ReviewedInstructions | None, language: str) -> str:
        if instructions is None:
            return (
                "没有找到当前有效且已核对的完整服药指示。请上传或核对药房标签/处方；不会从一般标签推算剂量。"
                if language == "zh"
                else "I could not find complete, current patient-reviewed instructions. "
                "Please review your pharmacy label or prescription; I will not infer a dose from a general label."
            )
        frequency = instructions.frequency_rule or {}
        kind = frequency.get("kind")
        times = ", ".join(str(value) for value in frequency.get("local_times", []))
        if instructions.is_prn:
            schedule = (
                "按已核对指示在需要时使用" if language == "zh" else "as needed, according to the reviewed instructions"
            )
        elif kind == "interval":
            schedule = (
                f"每 {frequency.get('every_hours')} 小时"
                if language == "zh"
                else f"every {frequency.get('every_hours')} hours"
            )
        elif kind == "weekly":
            weekdays = (
                ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
                if language == "zh"
                else ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
            )
            days = "、".join(weekdays[int(day) - 1] for day in frequency.get("days_of_week", []) if 1 <= int(day) <= 7)
            schedule = f"{days} {times}"
        else:
            schedule = ("每天 " if language == "zh" else "daily at ") + times
        unit = (
            {"tablet": "片", "tablets": "片", "capsule": "粒", "capsules": "粒", "mg": "毫克", "ml": "毫升"}.get(
                str(instructions.dose_unit), instructions.dose_unit
            )
            if language == "zh"
            else instructions.dose_unit
        )
        summary = (
            f"已核对的当前计划：{name}，每次服用 {instructions.dose_amount:g} {unit}；{schedule}。"
            if language == "zh"
            else f"Your current reviewed plan: {name}, {instructions.dose_amount:g} "
            f"{instructions.dose_unit} per dose; {schedule}."
        )
        if instructions.food_instruction:
            food = instructions.food_instruction
            if language == "zh":
                food = {
                    "with_food": "随餐服用",
                    "with food": "随餐服用",
                    "after_food": "餐后服用",
                    "before_food": "餐前服用",
                    "empty_stomach": "空腹服用",
                    "with_or_without_food": "随餐或空腹均可",
                }.get(food, food)
            summary += f" 用餐要求：{food}。" if language == "zh" else f" Food: {food}."
        if instructions.route:
            route = (
                {"oral": "口服", "topical": "外用", "inhalation": "吸入"}.get(instructions.route, instructions.route)
                if language == "zh"
                else instructions.route
            )
            summary += f" {route}。" if language == "zh" else f" Route: {route}."
        if instructions.course_start_date and instructions.course_end_date:
            summary += (
                f" 疗程：{instructions.course_start_date} 至 {instructions.course_end_date}。"
                if language == "zh"
                else f" Course: {instructions.course_start_date} to {instructions.course_end_date}."
            )
        elif instructions.course_start_date:
            summary += (
                f" 开始日期：{instructions.course_start_date}。"
                if language == "zh"
                else f" Starts: {instructions.course_start_date}."
            )
        elif instructions.course_end_date:
            summary += (
                f" 结束日期：{instructions.course_end_date}。"
                if language == "zh"
                else f" Ends: {instructions.course_end_date}."
            )
        return summary
