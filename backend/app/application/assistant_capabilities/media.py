"""Pure owned media metadata projections; bytes remain behind native patient APIs."""

from pydantic import BaseModel

from ...contracts.assistant_workflows import (
    AttachmentRef,
    BusinessRef,
    ChoiceAction,
    ChoiceOption,
    DownloadAction,
    OperationResult,
    Preparation,
    WorkflowContext,
)
from ...contracts.media_workflow import MEDIA_READ_SCHEMAS
from ...domain.errors import NotFoundError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..library_files import MedicationLibraryFileService
from ..personal_gallery import PersonalGalleryService


class MediaAdapter:
    def __init__(
        self,
        *,
        enrollment: MedicationEnrollmentService,
        gallery: PersonalGalleryService | None,
        library: MedicationLibraryFileService | None,
    ):
        self.enrollment, self.gallery, self.library = enrollment, gallery, library
        self.capability_ids = frozenset(
            name for name in MEDIA_READ_SCHEMAS
            if (gallery is not None if name.startswith("gallery.") else library is not None)
        )

    @staticmethod
    def _page(rows, page):
        count = max(1, (len(rows) + 9) // 10)
        page = page if page < count else 0
        return {"records": rows[page * 10 : (page + 1) * 10], "page": page,
                "page_count": count, "total": len(rows)}

    @staticmethod
    def _photo(row):
        return {
            "id": str(row.id), "medication_id": str(row.medication_id),
            "image_kind": row.image_kind, "source_description": row.source_description,
            "reviewed": row.reviewed, "eligibility": row.eligibility,
            "eligibility_reason": row.eligibility_reason, "metadata_version": row.metadata_version,
            "created_at": row.created_at.isoformat(),
        }

    @staticmethod
    def _file(row):
        return {
            "id": str(row.id), "medication_id": str(row.medication_id),
            "display_title": row.display_title, "original_filename": row.original_filename,
            "category": row.category, "description": row.description, "byte_size": row.byte_size,
            "version": row.version, "uploaded_at": row.uploaded_at.isoformat(),
        }

    @staticmethod
    def _choices(inputs, rows, *, page, field, action, name, visible=None):
        paged = MediaAdapter._page(rows, page)
        return Preparation(
            input_fields=inputs, missing_fields=(field,), prompt_key="assistant.media.choose_" + field,
            view_fields={**(visible or {}), **paged},
            actions=(ChoiceAction(action_id=action, options=tuple(
                ChoiceOption(value=row["id"], label_key="assistant.media.select", label_text=str(row[name])[:200])
                for row in paged["records"]
            )),) if rows else (),
        )

    def prepare(
        self,
        context: WorkflowContext,
        values: BaseModel,
        assets: tuple[AttachmentRef, ...],
        results: tuple[BusinessRef, ...] = (),
    ) -> Preparation:
        capability = context.capability_id
        if assets or results or capability not in self.capability_ids:
            raise ValidationError("Media queries do not accept attachments or business results")
        if not isinstance(values, MEDIA_READ_SCHEMAS[capability]):
            raise ValidationError("Use the typed media selection")
        inputs = values.model_dump(mode="json", exclude_none=True)
        med = self.enrollment.get_medication(context.owner, values.medication_id) if values.medication_id else None
        if values.medication_id and med is None:
            raise NotFoundError("Medication not found for this patient")
        if capability != "gallery.list" and med is None:
            rows = [{"id": str(row.id), "name": row.display_name}
                    for row in self.enrollment.list_medications(context.owner)]
            return self._choices(inputs, rows, page=values.page, field="medication_id",
                                 action="media.medication", name="name")
        visible = {"medication_name": med.display_name} if med else {}
        if capability == "gallery.list":
            rows = [
                {"medication_id": str(row["medication"].id), "name": row["medication"].display_name,
                 "status": row["status"], "photo_count": len(row["images"]), "eligible_count": row["eligible_count"]}
                for row in self.gallery.list(context.owner)
                if med is None or row["medication"].id == med.id
            ]
            visible.update(self._page(rows, values.page))
        elif capability == "gallery.photo.view":
            rows = [self._photo(image) for group in self.gallery.list(context.owner)
                    if group["medication"].id == med.id for image in group["images"]]
            if values.image_id is None:
                return self._choices(inputs, rows, page=values.page, field="image_id", action="media.image",
                                     name="source_description", visible=visible)
            photo = next((row for row in rows if row["id"] == str(values.image_id)), None)
            if photo is None:
                raise NotFoundError("Photo not found for this medication")
            visible["photo"] = photo
        else:
            rows = [self._file(row) for row in self.library.list(context.owner, med.id)]
            if capability == "library.list":
                visible.update(self._page(rows, values.page))
            else:
                if values.file_id is None:
                    return self._choices(inputs, rows, page=values.page, field="file_id", action="media.file",
                                         name="display_title", visible=visible)
                file = next((row for row in rows if row["id"] == str(values.file_id)), None)
                if file is None:
                    raise NotFoundError("PDF not found for this medication")
                visible["file"] = file
        return Preparation(
            input_fields=inputs, prompt_key="assistant.media.read", view_fields=visible,
            actions=(DownloadAction(capability_id=capability, owned_ref=BusinessRef(kind="file", id=values.file_id)),)
            if capability == "library.pdf.download" else (),
        )

    def observe(self, context: WorkflowContext, result_ref: BusinessRef) -> OperationResult:
        raise ValidationError("Viewing media is not a patient business write")
