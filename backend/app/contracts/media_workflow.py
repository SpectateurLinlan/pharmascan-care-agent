"""Closed read-only media selections; no paths, URLs, consent or write authority."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from .assistant_workflows import WorkflowDTO


class MediaReadFields(WorkflowDTO):
    medication_id: UUID | None = None
    page: int = Field(default=0, strict=True, ge=0, le=100000)


class PhotoReadFields(MediaReadFields):
    image_id: UUID | None = None


class PhotoUploadFields(MediaReadFields):
    source_attachment_id: UUID | None = None
    image_kind: Literal["loose_pill", "package", "blister", "source"] | None = None
    source_description: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("source_description")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Describe the photo and its source")
        return value.strip() if value is not None else None


class PdfReadFields(MediaReadFields):
    file_id: UUID | None = None


class PdfUploadFields(MediaReadFields):
    source_attachment_id: UUID | None = None
    filename: str | None = Field(default=None, min_length=1, max_length=240)
    category: Literal["prescription", "pharmacy_document", "medication_instructions", "other"] | None = None
    description: str = Field(default="", max_length=500)

    @field_validator("filename")
    @classmethod
    def pdf_leaf(cls, value):
        if value is not None and (not value.casefold().endswith(".pdf") or any(
            char in value for char in '/\\<>:"|?*'
        ) or not all(char.isprintable() for char in value)):
            raise ValueError("Choose a PDF filename without directory paths")
        return value

    @field_validator("description")
    @classmethod
    def trim_description(cls, value):
        return value.strip()


MEDIA_READ_SCHEMAS = {
    "gallery.list": MediaReadFields,
    "gallery.photo.view": PhotoReadFields,
    "library.list": MediaReadFields,
    "library.pdf.view": PdfReadFields,
    "library.pdf.download": PdfReadFields,
}


class MediaChangeFields(MediaReadFields):
    expected_version: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def paired_target(self):
        target = getattr(self, "image_id", None) or getattr(self, "file_id", None)
        if (target is None) != (self.expected_version is None):
            raise ValueError("Choose the file and its current version together")
        return self


class PhotoChangeFields(MediaChangeFields):
    image_id: UUID | None = None
    image_kind: Literal["loose_pill", "package", "blister", "source"] | None = None
    source_description: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("source_description")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Describe the photo and its source")
        return value.strip() if value is not None else None


class PdfChangeFields(MediaChangeFields):
    file_id: UUID | None = None
    title: str | None = Field(default=None, min_length=1, max_length=160)
    category: Literal["prescription", "pharmacy_document", "medication_instructions", "other"] | None = None
    description: str | None = Field(default=None, max_length=500)

    @field_validator("title")
    @classmethod
    def nonblank(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Enter a file title")
        return value.strip() if value is not None else None


MEDIA_CHANGE_SCHEMAS = {
    **dict.fromkeys(("gallery.photo.edit", "gallery.photo.remove", "gallery.photo.delete", "gallery.photo.retire"),
                    PhotoChangeFields),
    **dict.fromkeys(("library.pdf.edit", "library.pdf.delete"), PdfChangeFields),
}
