from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Public constants
MAX_CONTENT_SIZE = 10000
ALLOWED_LANGUAGES = ["python", "javascript", "ruby", "go", "java", "csharp", "typescript"]

# Internal in-memory store for validation errors
_validation_error_store: List[Dict[str, str]] = []


@dataclass
class ValidationError:
    field: str
    reason: str
    timestamp: str = dataclass_field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "reason": self.reason, "timestamp": self.timestamp}


def sanitize_input(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        value = str(value)
    # Keep printable chars, and explicitly allow \n, \r, \t. Remove other control chars.
    allowed_ws = {"\n", "\r", "\t"}
    cleaned_chars = []
    for ch in value:
        oc = ord(ch)
        if ch in allowed_ws:
            cleaned_chars.append(ch)
        elif 32 <= oc <= 126:
            cleaned_chars.append(ch)
        else:
            # Control or non-printable -> drop
            continue
    return "".join(cleaned_chars)


def sanitize_request_data(data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return data  # Defensive: if not dict, just return as-is
    sanitized = dict(data)
    for key in ("content", "language", "path"):
        if key in sanitized:
            sanitized[key] = sanitize_input(sanitized[key])
    return sanitized


def contains_null_bytes(s: str) -> bool:
    if s is None:
        return False
    return "\x00" in s


def contains_path_traversal(path: str) -> bool:
    if not isinstance(path, str):
        return False
    # Detect ../ or ..\ segments and home-dir shortcuts like ~/
    if re.search(r"(^|[\\/])\.\.([\\/]|$)", path):
        return True
    if path.startswith("~"):
        return True
    return False


def keep_recent_errors(limit: int = 100) -> None:
    global _validation_error_store
    if len(_validation_error_store) > limit:
        _validation_error_store = _validation_error_store[-limit:]


def log_validation_errors(errors: List[ValidationError]) -> None:
    if not errors:
        # Explicitly no-op to satisfy tests that patch keep_recent_errors
        return
    for err in errors:
        _validation_error_store.append(err.to_dict())
    keep_recent_errors()


def get_validation_errors() -> List[Dict[str, str]]:
    # Return a shallow copy to prevent external mutation
    return list(_validation_error_store)


def clear_validation_errors() -> None:
    _validation_error_store.clear()


def validate_review_request(data: Dict[str, Any]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    payload = sanitize_request_data(data or {})

    content = payload.get("content")
    language = payload.get("language")

    # Validate content
    if "content" not in payload:
        errs.append(ValidationError(field="content", reason="Content is required"))
    else:
        if isinstance(content, str):
            if len(content) > MAX_CONTENT_SIZE:
                errs.append(
                    ValidationError(
                        field="content",
                        reason=f"Content exceeds maximum size of {MAX_CONTENT_SIZE} characters",
                    )
                )
            elif contains_null_bytes(content):
                errs.append(ValidationError(field="content", reason="Content contains null bytes"))
        else:
            errs.append(ValidationError(field="content", reason="Content must be a string"))

    # Validate language
    if language is None:
        errs.append(ValidationError(field="language", reason="Language is required"))
    elif not isinstance(language, str) or language.strip() == "":
        errs.append(ValidationError(field="language", reason="Language must be a non-empty string"))
    elif language not in ALLOWED_LANGUAGES:
        errs.append(ValidationError(field="language", reason="Unsupported language"))

    if errs:
        log_validation_errors(errs)

    return errs


def validate_statistics_request(data: Dict[str, Any]) -> List[ValidationError]:
    errs: List[ValidationError] = []
    payload = data or {}

    if "files" not in payload:
        errs.append(ValidationError(field="files", reason="Files array is required"))
        return errs

    files = payload.get("files")
    if not isinstance(files, list):
        errs.append(ValidationError(field="files", reason="Files must be an array"))
        return errs

    if len(files) == 0:
        errs.append(ValidationError(field="files", reason="Files cannot be empty"))
        return errs

    if len(files) > 1000:
        errs.append(ValidationError(field="files", reason="Files cannot exceed 1000 entries"))
        return errs

    return []