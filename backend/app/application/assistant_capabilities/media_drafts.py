"""Owned lifecycle drafts and explicit native payloads; no binary reads or writes."""

from ...contracts.assistant_workflows import ChoiceAction, ChoiceOption, Preparation, WorkflowContext
from ...contracts.library_files import LibraryFileDTO
from ...contracts.media_workflow import PdfChangeFields, PhotoChangeFields
from ...contracts.medication_evidence import MedicationImage
from ...domain.errors import NotFoundError, StaleVersionError, ValidationError
from ..enrollment import MedicationEnrollmentService
from ..library_files import MedicationLibraryFileService
from ..personal_gallery import PersonalGalleryService


class MediaDrafts:
    def __init__(self, *, enrollment: MedicationEnrollmentService, gallery: PersonalGalleryService | None,
                 library: MedicationLibraryFileService | None):
        self.enrollment, self.gallery, self.library = enrollment, gallery, library

    @staticmethod
    def photo(capability):
        return capability.startswith("gallery.")

    def target(self, context: WorkflowContext, values: PhotoChangeFields | PdfChangeFields, *, current_version=True,
               include_deleted=False) -> MedicationImage | LibraryFileDTO:
        med = self.enrollment.get_medication(context.owner, values.medication_id) if values.medication_id else None
        if med is None:
            raise NotFoundError("Medication not found for this patient")
        row = (self.gallery.metadata(context.owner, values.image_id, include_deleted=include_deleted)
               if self.photo(context.capability_id)
               else self.library.metadata(context.owner, values.file_id, include_deleted=include_deleted))
        if row.medication_id != med.id:
            raise NotFoundError("File not found for this medication")
        if current_version and self.version(row) != values.expected_version:
            raise StaleVersionError("The file changed; prepare a new patient review")
        return row

    @staticmethod
    def version(row):
        return getattr(row, "metadata_version", None) or row.version

    def visible(self, row):
        photo = hasattr(row, "image_kind")
        data = row.model_dump(mode="json", include={
            "id", "medication_id", "image_kind", "source_description", "eligibility", "eligibility_reason",
            "display_title", "original_filename", "category", "description", "byte_size", "gallery_removed",
        })
        return {**data, "version": self.version(row), "deleted": row.deleted_at is not None,
                "cleanup_pending": row.cleanup_pending, "media_kind": "photo" if photo else "pdf"}

    def payload(self, context, values):
        capability = context.capability_id
        action = capability.rsplit(".", 1)[1]
        if capability.startswith("gallery."):
            if action == "retire":
                return {}
            return {"action": action, "expected_version": values.expected_version,
                    "image_kind": values.image_kind if action == "edit" else None,
                    "source_description": values.source_description if action == "edit" else None,
                    "confirmed": True}
        if action == "delete":
            return {}
        return {"expected_version": values.expected_version, "title": values.title, "category": values.category,
                "description": (values.description or "").strip()}

    def validate_target_action(self, context, row):
        if context.capability_id in {"gallery.photo.remove", "gallery.photo.delete"} and row.source_id is not None:
            raise ValidationError("Source-linked evidence cannot be removed or deleted")
        if context.capability_id == "library.pdf.delete" and (row.source_document_id or row.regimen_version_id):
            raise ValidationError("This file is linked to a protected source or regimen")
        if self.photo(context.capability_id) and row.gallery_removed:
            raise ValidationError("The photo was removed from the gallery; recheck its native file record")

    def review(self, context, values, *, partial_cleanup=False):
        row = self.target(context, values, current_version=not partial_cleanup, include_deleted=partial_cleanup)
        self.validate_target_action(context, row)
        return {"target_id": str(row.id), "target": self.visible(row), "payload": self.payload(context, values),
                "cleanup_retry": partial_cleanup,
                "medication_name": self.enrollment.get_medication(context.owner, row.medication_id).display_name}

    def collect(self, context, values):
        inputs = values.model_dump(mode="json", exclude_none=True)
        if values.medication_id is None:
            rows = [{"id": str(row.id), "label": row.display_name}
                    for row in self.enrollment.list_medications(context.owner)]
            return self.choices(inputs, rows, values.page, "medication_id", "media.medication")
        if self.enrollment.get_medication(context.owner, values.medication_id) is None:
            raise NotFoundError("Medication not found for this patient")
        photo = self.photo(context.capability_id)
        target_id = values.image_id if photo else values.file_id
        if target_id is None:
            rows = ([{"id": f"{image.id}:{image.metadata_version}", "label": image.source_description}
                     for group in self.gallery.list(context.owner) if group["medication"].id == values.medication_id
                     for image in group["images"]]
                    if photo else [{"id": f"{row.id}:{row.version}", "label": row.display_title}
                                   for row in self.library.list(context.owner, values.medication_id)])
            return self.choices(inputs, rows, values.page, "image_id" if photo else "file_id",
                                "media.photo_target" if photo else "media.pdf_target")
        row = self.target(context, values)
        self.validate_target_action(context, row)
        missing = ()
        if context.capability_id.endswith("edit"):
            names = ("image_kind", "source_description") if photo else ("title", "category", "description")
            missing = tuple(name for name in names if getattr(values, name) is None)
        return Preparation(input_fields=inputs, missing_fields=missing,
                           workflow_state="collecting" if missing else "ready_for_review",
                           prompt_key="assistant.media.collect" if missing else "assistant.media.ready",
                           view_fields={"media_target": self.visible(row),
                                        "medication_name": self.enrollment.get_medication(
                                            context.owner, values.medication_id).display_name})

    @staticmethod
    def choices(inputs, rows, page, field, action):
        pages = max(1, (len(rows) + 9) // 10)
        page = page if page < pages else 0
        return Preparation(input_fields=inputs, missing_fields=(field,), prompt_key="assistant.media.choose_" + field,
                           view_fields={"page": page, "page_count": pages, "total": len(rows)},
                           actions=(ChoiceAction(action_id=action, options=tuple(
                               ChoiceOption(value=row["id"], label_key="assistant.media.select",
                                            label_text=row["label"][:200])
                               for row in rows[page * 10:(page + 1) * 10])),) if rows else ())
