"""Patient-facing input errors around the existing strict image sanitizer."""

from ..contracts.vision import VisionSchemaError
from ..domain.errors import ValidationError
from .stage2_http import sanitize_image, sanitize_reference_image


def patient_source_image(content: bytes) -> bytes:
    try:
        return sanitize_image(content)
    except VisionSchemaError:
        raise ValidationError("Choose a valid PNG or JPEG medication source photo.") from None


def patient_reference_image(content: bytes) -> bytes:
    try:
        return sanitize_reference_image(content)
    except VisionSchemaError:
        raise ValidationError("Choose a clear, nonblank photo of one pill.") from None
