import pytest
from unittest.mock import patch, MagicMock

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
    validation_errors,
    ALLOWED_LANGUAGES,
    MAX_CONTENT_SIZE,
)


@pytest.fixture(autouse=True)
def reset_validation_errors():
    """Ensure validation error log is clean before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Create a ValidationError instance for testing."""
    return ValidationError(field="content", reason="invalid content")


def test_ValidationError_init_and_to_dict_with_mocked_timestamp():
    """ValidationError should set field, reason, and use datetime.now().isoformat() for timestamp."""
    class FakeNow:
        def isoformat(self):
            return "2020-01-01T00:00:00"

    fake_dt = MagicMock()
    fake_dt.now.return_value = FakeNow()

    with patch("src.request_validator.datetime", fake_dt):
        err = ValidationError(field="path", reason="bad path")
        d = err.to_dict()
        assert d["field"] == "path"
        assert d["reason"] == "bad path"
        assert d["timestamp"] == "2020-01-01T00:00:00"


def test_ValidationError_to_dict_structure(validation_error_instance):
    """ValidationError.to_dict should return a dict with required keys."""
    d = validation_error_instance.to_dict()
    assert d["field"] == "content"
    assert d["reason"] == "invalid content"
    assert isinstance(d["timestamp"], str)
    assert "T" in d["timestamp"]  # ISO-like format


def test_validate_review_request_content_required_and_logged():
    """validate_review_request should require non-empty content and log the error."""
    errors = validate_review_request({})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "cannot be empty" in errors[0].reason

    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "content"
    assert "cannot be empty" in logged[0]["reason"]


def test_validate_review_request_content_too_large():
    """validate_review_request should flag content that exceeds MAX_CONTENT_SIZE."""
    payload = {"content": "a" * (MAX_CONTENT_SIZE + 1)}
    errors = validate_review_request(payload)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "exceeds maximum size" in errors[0].reason


def test_validate_review_request_null_bytes_detected():
    """validate_review_request should reject content with null bytes."""
    payload = {"content": "abc\x00def"}
    errors = validate_review_request(payload)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "null bytes" in errors[0].reason


def test_validate_review_request_invalid_language():
    """validate_review_request should reject languages outside ALLOWED_LANGUAGES."""
    assert "python" in ALLOWED_LANGUAGES
    payload = {"content": "print('ok')", "language": "haskell"}
    errors = validate_review_request(payload)
    assert len(errors) == 1
    assert errors[0].field == "language"
    assert "Language must be one of" in errors[0].reason


def test_validate_review_request_valid_input_no_errors():
    """validate_review_request should return no errors for valid content/language and not log anything."""
    payload = {"content": "print('hello')", "language": "python"}
    errors = validate_review_request(payload)
    assert errors == []
    assert get_validation_errors() == []


def test_validate_statistics_request_files_required():
    """validate_statistics_request should require 'files' field."""
    errors = validate_statistics_request({})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason


def test_validate_statistics_request_files_not_list():
    """validate_statistics_request should require 'files' to be a list."""
    errors = validate_statistics_request({"files": "not-a-list"})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "must be an array" in errors[0].reason


def test_validate_statistics_request_files_empty_list():
    """validate_statistics_request should reject empty 'files' lists."""
    errors = validate_statistics_request({"files": []})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot be empty" in errors[0].reason


def test_validate_statistics_request_files_exceeds_limit():
    """validate_statistics_request should reject lists with more than 1000 entries."""
    errors = validate_statistics_request({"files": list(range(1001))})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000" in errors[0].reason


def test_validate_statistics_request_valid():
    """validate_statistics_request should return no errors for a valid files list."""
    errors = validate_statistics_request({"files": [1, 2, 3]})
    assert errors == []


def test_sanitize_input_none_and_non_str_handling():
    """sanitize_input should return None for None; non-str inputs should be stringified."""
    assert sanitize_input(None) is None
    assert sanitize_input(123) == "123"


def test_sanitize_input_removes_control_chars_but_keeps_whitespace():
    """sanitize_input should remove control characters but keep newline, carriage return, and tab."""
    s = "A\x00B\x01C\nD\tE\rF"
    assert sanitize_input(s) == "ABC\nD\tE\rF"


def test_sanitize_request_data_sanitizes_only_string_fields():
    """sanitize_request_data should only sanitize string types for content/language/path."""
    data = {
        "content": "X\x00Y",
        "language": "py\x07thon",
        "path": "/home/\x00user",
        "other": 123,  # untouched
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "XY"
    assert sanitized["language"] == "python"
    assert sanitized["path"] == "/home/user"
    assert sanitized["other"] == 123


def test_contains_helpers():
    """contains_null_bytes and contains_path_traversal should detect their patterns."""
    assert contains_null_bytes("a\x00b") is True
    assert contains_null_bytes("abc") is False

    assert contains_path_traversal("../etc") is True
    assert contains_path_traversal("x/~/y") is True
    assert contains_path_traversal("normal/path") is False


def test_log_validation_errors_keeps_last_100_entries():
    """log_validation_errors should store only the most recent 100 entries."""
    errs = [ValidationError(field="f", reason=f"r{i}") for i in range(150)]
    log_validation_errors(errs)
    logged = get_validation_errors()
    assert len(logged) == 100
    # Should keep last 100: r50 to r149
    assert logged[0]["reason"] == "r50"
    assert logged[-1]["reason"] == "r149"


def test_log_validation_errors_noop_when_no_errors():
    """log_validation_errors should not change the log when given an empty list."""
    assert get_validation_errors() == []
    log_validation_errors([])
    assert get_validation_errors() == []


def test_keep_recent_errors_trims_when_exceeding_capacity():
    """keep_recent_errors should trim the in-memory log to 100 items."""
    # Directly populate the global log with 120 entries
    for i in range(120):
        validation_errors.append({"field": "f", "reason": f"r{i}", "timestamp": "t"})
    keep_recent_errors()
    logged = get_validation_errors()
    assert len(logged) == 100
    assert logged[0]["reason"] == "r20"
    assert logged[-1]["reason"] == "r119"


def test_log_validation_errors_uses_lock_and_calls_keep_recent_errors():
    """log_validation_errors should acquire the lock and call keep_recent_errors."""
    with patch("src.request_validator.validation_lock") as mock_lock, patch(
        "src.request_validator.keep_recent_errors"
    ) as mock_keep:
        err = ValidationError(field="x", reason="y")
        log_validation_errors([err])
        assert mock_lock.__enter__.called
        assert mock_lock.__exit__.called
        mock_keep.assert_called_once()


def test_log_validation_errors_propagates_exceptions_from_keep_recent_errors():
    """log_validation_errors should propagate exceptions raised by keep_recent_errors."""
    with patch("src.request_validator.keep_recent_errors", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            log_validation_errors([ValidationError(field="a", reason="b")])