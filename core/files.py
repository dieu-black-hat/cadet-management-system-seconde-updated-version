"""Upload validation: extension allow-list, real content sniffing, size limit, hashing."""
import hashlib
from pathlib import Path

import filetype
from django.conf import settings
from django.core.exceptions import ValidationError

ALLOWED_DOCUMENTS = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/zip"},
}
ALLOWED_IMAGES = {".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"}}


def validate_upload(uploaded, allowed=None, max_mb=None):
    """Return (content_type, size, sha256) or raise ValidationError."""
    allowed = allowed or ALLOWED_DOCUMENTS
    max_mb = max_mb or settings.MAX_UPLOAD_SIZE_MB
    name = Path(uploaded.name or "").name
    ext = Path(name).suffix.lower()
    if ext not in allowed:
        raise ValidationError(f"File type '{ext or 'unknown'}' is not allowed. Allowed: {', '.join(sorted(allowed))}.")
    if uploaded.size > max_mb * 1024 * 1024:
        raise ValidationError(f"File is too large (maximum {max_mb} MB).")
    if uploaded.size == 0:
        raise ValidationError("File is empty.")
    head = uploaded.read(8192)
    uploaded.seek(0)
    kind = filetype.guess(head)
    detected = kind.mime if kind else None
    if detected not in allowed[ext]:
        raise ValidationError("File content does not match its extension.")
    digest = hashlib.sha256()
    for chunk in uploaded.chunks():
        digest.update(chunk)
    uploaded.seek(0)
    content_type = sorted(allowed[ext])[0] if ext != ".docx" else \
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return content_type, uploaded.size, digest.hexdigest()


def safe_display_name(name: str) -> str:
    name = Path(name or "file").name
    cleaned = "".join(ch for ch in name if ch.isalnum() or ch in "._- ")[:120]
    return cleaned or "file"
