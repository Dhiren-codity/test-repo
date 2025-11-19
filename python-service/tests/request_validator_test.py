import pytest
from unittest.mock import patch, Mock
from datetime import datetime

from src.request_validator import (
    ValidationError,
    validate_review_request,
    validate_statistics_request,
    sanitize_input,
    sanitize_request_data,
    contains_null_bytes,
    contains_path_traversal,
    log_validation_errors,
    keep_recent_errors,
    get_validation_errors,
    clear_validation_errors,
    MAX_CONTENT_SIZE,
    ALLOWED_LANGUAGES,
)


@pytest.fixture(autouse=True)
def reset_validation_store():
    """Ensure the global validation error store is cleared before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Create a ValidationError instance for testing."""
    return ValidationError(field="test_field", reason="test_reason")


def test_ValidationError___init___sets_fields_and_timestamp(validation_error_instance):
    """Test that ValidationError initializes with correct field, reason, and a valid timestamp."""
    ve = validation_error_instance
    assert ve.field == "test_field"
    assert ve.reason == "test_reason"
    # Ensure timestamp is a valid ISO format and close to now
    ts = datetime.fromisoformat(ve.timestamp)
    assert isinstance(ts, datetime)
    assert abs((datetime.now() - ts).total_seconds()) < 5


def test_ValidationError_to_dict_returns_expected_dict(validation_error_instance):
    """Test that to_dict returns a dictionary with expected keys and values."""
    ve = validation_error_instance
    d = ve.to_dict()
    assert d["field"] == ve.field
    assert d["reason"] == ve.reason
    assert d["timestamp"] == ve.timestamp


def test_validate_review_request_missing_content_and_invalid_language():
    """Test validate_review_request returns errors for missing content and invalid language."""
    data = {"language": "c++"}
    errors = validate_review_request(data)
    assert len(errors) == 2
    fields = sorted([e.field for e in errors])
    assert fields == ["content", "language"]

    # Ensure errors were logged
    logged = get_validation_errors()
    assert len(logged) == 2
    assert sorted([e["field"] for e in logged]) == ["content", "language"]


def test_validate_review_request_content_too_large():
    """Test validate_review_request returns error when content exceeds MAX_CONTENT_SIZE."""
    data = {"content": "a" * (MAX_CONTENT_SIZE + 1), "language": ALLOWED_LANGUAGES[0]}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "exceeds maximum size" in errors[0].reason

    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "content"


def test_validate_review_request_content_contains_null_bytes():
    """Test validate_review_request returns error when content contains null bytes."""
    data = {"content": "hello\x00world", "language": ALLOWED_LANGUAGES[0]}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "null bytes" in errors[0].reason


def test_validate_review_request_valid_input_no_errors_logged():
    """Test validate_review_request returns no errors for valid input and logs nothing."""
    clear_validation_errors()
    data = {"content": "print('hello')", "language": ALLOWED_LANGUAGES[0]}
    errors = validate_review_request(data)
    assert errors == []
    assert get_validation_errors() == []


def test_validate_statistics_request_files_missing():
    """Test validate_statistics_request returns error when 'files' is missing."""
    data = {}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason


def test_validate_statistics_request_files_not_list():
    """Test validate_statistics_request returns error when 'files' is not a list."""
    data = {"files": "not-a-list"}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "must be an array" in errors[0].reason


def test_validate_statistics_request_files_empty_list():
    """Test validate_statistics_request returns error when 'files' list is empty."""
    data = {"files": []}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot be empty" in errors[0].reason


def test_validate_statistics_request_files_too_many_entries():
    """Test validate_statistics_request returns error when 'files' list exceeds 1000 entries."""
    data = {"files": list(range(1001))}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000" in errors[0].reason


def test_validate_statistics_request_valid():
    """Test validate_statistics_request returns no errors for valid list."""
    data = {"files": ["a.py", "b.py"]}
    errors = validate_statistics_request(data)
    assert errors == []


def test_sanitize_input_none():
    """Test sanitize_input returns None when input is None."""
    assert sanitize_input(None) is None


def test_sanitize_input_non_string_converted_to_string():
    """Test sanitize_input converts non-string input to string."""
    assert sanitize_input(12345) == "12345"


def test_sanitize_input_removes_control_chars_and_keeps_whitespace():
    """Test sanitize_input removes control characters but keeps newline, carriage return, and tab."""
    dirty = "A" + "\x00" + "\x01" + "\n" + "\r" + "\t" + "\x07" + "B" + "\x7f" + "\x0e"
    clean = sanitize_input(dirty)
    assert clean == "A\n\r\tB"


def test_sanitize_request_data_sanitizes_specific_fields_only():
    """Test sanitize_request_data sanitizes the 'content', 'language', and 'path' fields."""
    dirty = {
        "content": "ok\x00ay",
        "language": "python\x07",
        "path": "/safe/pa\x00th",
        "other": "untouched",
    }
    sanitized = sanitize_request_data(dirty)
    assert sanitized["content"] == "okay"
    assert sanitized["language"] == "python"
    assert sanitized["path"] == "/safe/path"
    assert sanitized["other"] == "untouched"


def test_contains_null_bytes_true_and_false():
    """Test contains_null_bytes detects null byte presence correctly."""
    assert contains_null_bytes("a\x00b") is True
    assert contains_null_bytes("abc") is False


def test_contains_path_traversal_true_and_false():
    """Test contains_path_traversal detects traversal patterns correctly."""
    assert contains_path_traversal("../etc/passwd") is True
    assert contains_path_traversal("~/secrets") is True
    assert contains_path_traversal("safe/path") is False


def test_log_validation_errors_adds_and_trims_to_100():
    """Test log_validation_errors appends errors and trims the store to the most recent 100."""
    # Create 105 errors
    errors = [ValidationError("f", f"r{i}") for i in range(105)]
    log_validation_errors(errors)
    logged = get_validation_errors()
    assert len(logged) == 100
    # The remaining should be the last 100 of the 105 we created
    expected = [e.to_dict() for e in errors][-100:]
    assert logged == expected


def test_log_validation_errors_noop_on_empty_list():
    """Test log_validation_errors does nothing when given an empty list."""
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        log_validation_errors([])
        mock_keep.assert_not_called()
    assert get_validation_errors() == []


def test_log_validation_errors_propagates_exception_from_keep_recent_errors():
    """Test that exceptions inside log_validation_errors are propagated."""
    errs = [ValidationError("f", "r")]
    with patch("src.request_validator.keep_recent_errors", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError, match="boom"):
            log_validation_errors(errs)


def test_get_validation_errors_returns_copy_not_reference():
    """Test get_validation_errors returns a copy that does not affect the internal store."""
    errs = [ValidationError("f", "r")]
    log_validation_errors(errs)
    copy1 = get_validation_errors()
    assert len(copy1) == 1
    copy1.append({"field": "x", "reason": "y", "timestamp": "z"})
    # Internal store should remain unchanged
    assert len(get_validation_errors()) == 1


def test_keep_recent_errors_trims_when_exceeds_limit():
    """Test keep_recent_errors trims global store when exceeded."""
    # Add 110 individual errors so trimming happens along the way
    for i in range(110):
        log_validation_errors([ValidationError("f", f"r{i}")])
    logged = get_validation_errors()
    assert len(logged) == 100
    # Ensure we have the last 100 reasons from r10 to r109
    reasons = [e["reason"] for e in logged]
    assert reasons[0] == "r10"
    assert reasons[-1] == "r109"