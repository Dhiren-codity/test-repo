import pytest
from unittest.mock import patch, Mock

from src.request_validator import (
    ValidationError,
    validate_review_request,
    validate_statistics_request,
    sanitize_input,
    sanitize_request_data,
    contains_null_bytes,
    contains_path_traversal,
    log_validation_errors,
    get_validation_errors,
    clear_validation_errors,
    MAX_CONTENT_SIZE,
    ALLOWED_LANGUAGES,
)


@pytest.fixture(autouse=True)
def reset_validation_errors():
    """Ensure validation errors global log is cleared before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def fixed_datetime_iso():
    """Return a fixed ISO timestamp string and a patch for datetime.now()."""
    fixed_iso = "2025-01-01T12:34:56"
    fixed_dt = Mock()
    fixed_dt.isoformat.return_value = fixed_iso
    mock_datetime = Mock()
    mock_datetime.now.return_value = fixed_dt
    with patch("src.request_validator.datetime", mock_datetime):
        yield fixed_iso


@pytest.fixture
def make_validation_error():
    """Factory for creating ValidationError instances."""
    def _make(field="field", reason="reason"):
        return ValidationError(field, reason)
    return _make


def test_validationerror_init_and_to_dict_with_timestamp(fixed_datetime_iso):
    """ValidationError.to_dict should include field, reason, and patched timestamp."""
    err = ValidationError("content", "is invalid")
    data = err.to_dict()
    assert data["field"] == "content"
    assert data["reason"] == "is invalid"
    assert data["timestamp"] == fixed_datetime_iso


def test_validationerror_to_dict_structure(make_validation_error):
    """ValidationError.to_dict returns a dict with required keys."""
    err = make_validation_error("language", "unsupported")
    d = err.to_dict()
    assert set(d.keys()) == {"field", "reason", "timestamp"}
    assert d["field"] == "language"
    assert d["reason"] == "unsupported"
    assert isinstance(d["timestamp"], str)


def test_validate_review_request_missing_content_logs_error():
    """validate_review_request should error when content is missing and log the error."""
    errors = validate_review_request({"language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert errors[0].reason == "Content is required and cannot be empty"

    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "content"
    assert logged[0]["reason"] == "Content is required and cannot be empty"
    assert "timestamp" in logged[0]


def test_validate_review_request_content_too_large():
    """validate_review_request should limit content size."""
    content = "a" * (MAX_CONTENT_SIZE + 1)
    errors = validate_review_request({"content": content, "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert errors[0].reason == f"Content exceeds maximum size of {MAX_CONTENT_SIZE} bytes"


def test_validate_review_request_null_bytes_detected():
    """validate_review_request should reject content containing null bytes."""
    errors = validate_review_request({"content": "abc\x00def", "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert errors[0].reason == "Content contains invalid null bytes"


def test_validate_review_request_invalid_language():
    """validate_review_request should error when language is not in allowed list."""
    errors = validate_review_request({"content": "ok", "language": "c++"})
    assert len(errors) == 1
    assert errors[0].field == "language"
    assert "Language must be one of" in errors[0].reason
    for lang in ALLOWED_LANGUAGES:
        assert lang in errors[0].reason


def test_validate_review_request_valid_input_no_errors_and_no_logging():
    """validate_review_request should produce no errors for valid content/language and not log."""
    clear_validation_errors()
    errors = validate_review_request({"content": "hello world", "language": ALLOWED_LANGUAGES[0]})
    assert errors == []
    assert get_validation_errors() == []


def test_validate_statistics_request_missing_files_required():
    """validate_statistics_request should error when 'files' key is missing."""
    errors = validate_statistics_request({})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert errors[0].reason == "Files array is required"

    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "files"
    assert logged[0]["reason"] == "Files array is required"


def test_validate_statistics_request_not_list_type():
    """validate_statistics_request should error when files is not a list."""
    errors = validate_statistics_request({"files": "abc"})
    assert len(errors) == 1
    assert errors[0].reason == "Files must be an array"


def test_validate_statistics_request_empty_list_triggers_required_message():
    """validate_statistics_request current behavior: empty list is treated as 'required'."""
    errors = validate_statistics_request({"files": []})
    assert len(errors) == 1
    assert errors[0].reason == "Files array is required"


def test_validate_statistics_request_too_many_entries():
    """validate_statistics_request should limit list size to 1000 entries."""
    errors = validate_statistics_request({"files": list(range(1001))})
    assert len(errors) == 1
    assert errors[0].reason == "Files array cannot exceed 1000 entries"


def test_validate_statistics_request_valid():
    """validate_statistics_request should accept a non-empty list with <= 1000 entries."""
    errors = validate_statistics_request({"files": [1, 2, 3]})
    assert errors == []


def test_sanitize_input_none_and_non_string():
    """sanitize_input should return None for None, and str() for non-strings."""
    assert sanitize_input(None) is None
    assert sanitize_input(123) == "123"


def test_sanitize_input_removes_control_chars_preserves_whitespace():
    """sanitize_input should strip control/non-printable except newline, carriage return, and tab."""
    raw = "A\x00B\x01C\nD\tE\rF\x7fG"
    sanitized = sanitize_input(raw)
    assert sanitized == "ABC\nD\tE\rFG"


def test_sanitize_request_data_sanitizes_string_fields_only():
    """sanitize_request_data should sanitize 'content', 'language', and 'path' when strings."""
    data = {
        "content": "safe\x00text",
        "language": "py\x01thon",
        "path": "../bad\x00path",
        "other": 42,
    }
    out = sanitize_request_data(data)
    assert out["content"] == "safetext"
    assert out["language"] == "python"
    assert out["path"] == "../badpath"
    assert out["other"] == 42  # unchanged


def test_contains_null_bytes_true_false():
    """contains_null_bytes should detect presence of null byte."""
    assert contains_null_bytes("abc\x00def") is True
    assert contains_null_bytes("abcdef") is False


def test_contains_path_traversal_true_for_dotdot_and_tilde():
    """contains_path_traversal should detect '..' and '~/' patterns."""
    assert contains_path_traversal("../../etc/passwd") is True
    assert contains_path_traversal("~/secrets") is True
    assert contains_path_traversal("/safe/path") is False


def test_log_validation_errors_calls_keep_recent_errors_when_errors_present():
    """log_validation_errors should call keep_recent_errors and append entries when errors present."""
    clear_validation_errors()
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        log_validation_errors([ValidationError("field", "bad")])
        mock_keep.assert_called_once()
    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "field"
    assert logged[0]["reason"] == "bad"


def test_log_validation_errors_noop_with_empty_list():
    """log_validation_errors should do nothing when given empty error list."""
    clear_validation_errors()
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        log_validation_errors([])
        mock_keep.assert_not_called()
    assert get_validation_errors() == []


def test_keep_recent_errors_truncates_to_100():
    """keep_recent_errors should retain only the most recent 100 error records."""
    clear_validation_errors()
    for i in range(105):
        log_validation_errors([ValidationError("f", f"reason-{i}")])
    logged = get_validation_errors()
    assert len(logged) == 100
    assert logged[0]["reason"] == "reason-5"
    assert logged[-1]["reason"] == "reason-104"


def test_get_validation_errors_returns_copy_not_reference():
    """get_validation_errors should return a copy that can be mutated without affecting internal state."""
    log_validation_errors([ValidationError("a", "b")])
    snapshot = get_validation_errors()
    snapshot.append({"field": "x", "reason": "y", "timestamp": "z"})
    assert len(get_validation_errors()) == 1