import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_PHOTO_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB

DOCUMENT_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".doc", ".docx"}
DOCUMENT_MIME_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png"}
PHOTO_MIME_TYPES = {"image/jpeg", "image/png"}

# Deliberately NOT under static/ - uploaded files must only be reachable through
# authenticated download endpoints, never served directly by StaticFiles.
UPLOAD_ROOT = Path("uploads")


@dataclass
class SavedUpload:
    file_path: str
    file_name: str
    file_size: int
    mime_type: str


def _persist_upload(
    company_id: int,
    employee_id: int,
    upload_file: UploadFile,
    *,
    allowed_extensions: set[str],
    allowed_mime_types: set[str],
    max_size_bytes: int,
    subdir: str,
) -> SavedUpload:
    original_name = Path(upload_file.filename or "unnamed").name
    extension = Path(original_name).suffix.lower()

    if extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File type '{extension}' is not allowed. Allowed types: {sorted(allowed_extensions)}",
        )

    if upload_file.content_type not in allowed_mime_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content type '{upload_file.content_type}' is not allowed.",
        )

    contents = upload_file.file.read()
    if len(contents) > max_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File exceeds maximum allowed size of {max_size_bytes // (1024 * 1024)} MB.",
        )
    if len(contents) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")

    target_dir = UPLOAD_ROOT / subdir / str(company_id) / str(employee_id)
    target_dir.mkdir(parents=True, exist_ok=True)

    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    target_path = target_dir / stored_name
    target_path.write_bytes(contents)

    return SavedUpload(
        file_path=str(target_path),
        file_name=original_name,
        file_size=len(contents),
        mime_type=upload_file.content_type or "application/octet-stream",
    )


def save_upload(company_id: int, employee_id: int, upload_file: UploadFile) -> SavedUpload:
    return _persist_upload(
        company_id,
        employee_id,
        upload_file,
        allowed_extensions=DOCUMENT_EXTENSIONS,
        allowed_mime_types=DOCUMENT_MIME_TYPES,
        max_size_bytes=MAX_FILE_SIZE_BYTES,
        subdir="documents",
    )


def save_profile_photo(company_id: int, employee_id: int, upload_file: UploadFile) -> SavedUpload:
    return _persist_upload(
        company_id,
        employee_id,
        upload_file,
        allowed_extensions=PHOTO_EXTENSIONS,
        allowed_mime_types=PHOTO_MIME_TYPES,
        max_size_bytes=MAX_PHOTO_SIZE_BYTES,
        subdir="photos",
    )


def save_leave_attachment(company_id: int, employee_id: int, upload_file: UploadFile) -> SavedUpload:
    return _persist_upload(
        company_id,
        employee_id,
        upload_file,
        allowed_extensions=DOCUMENT_EXTENSIONS,
        allowed_mime_types=DOCUMENT_MIME_TYPES,
        max_size_bytes=MAX_FILE_SIZE_BYTES,
        subdir="leave_attachments",
    )


def delete_file_if_exists(file_path: str | None) -> None:
    if not file_path:
        return
    path = Path(file_path)
    if path.exists():
        path.unlink()
