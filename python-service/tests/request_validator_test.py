import re
import pytest
from unittest.mock import Mock, patch

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
    keep_recent_errors,
    MAX_CONTENT_SIZE,
    ALLOWED_LANGUAGES,
)


@pytest.fixture(autouse=True)
def clear_errors_before_each_test():
    """Automatically clear global validation errors before each test to avoid cross-test pollution"""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Provide a ValidationError instance for testing"""
    return ValidationError(field="content", reason="Invalid content")


def test_ValidationError___init___sets_fields_and_timestamp(validation_error_instance):
    """Test that ValidationError initializes with correct field, reason and a valid ISO timestamp"""
    ve = validation_error_instance
    assert ve.field == "content"
    assert ve.reason == "Invalid content"
    # Timestamp should be ISO-like
    assert isinstance(ve.timestamp, str)
    # Should parse as ISO format
    from datetime import datetime as _dt

    _dt.fromisoformat(ve.timestamp)


def test_ValidationError_to_dict_returns_expected_dict(validation_error_instance):
    """Test that ValidationError.to_dict returns the correct dictionary representation"""
    ve = validation_error_instance
    d = ve.to_dict()
    assert d["field"] == "content"
    assert d["reason"] == "Invalid content"
    assert d["timestamp"] == ve.timestamp


def test_validate_review_request_missing_content_and_invalid_language():
    """Test validate_review_request returns errors when content is missing and language is invalid"""
    data = {"language": "c++"}  # invalid language
    errors = validate_review_request(data)
    assert len(errors) == 2
    fields = {e.field for e in errors}
    assert "content" in fields
    assert "language" in fields


def test_validate_review_request_content_too_large():
    """Test validate_review_request returns error when content exceeds MAX_CONTENT_SIZE"""
    data = {"content": "a" * (MAX_CONTENT_SIZE + 1), "language": ALLOWED_LANGUAGES[0]}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "exceeds maximum size" in errors[0].reason


def test_validate_review_request_content_contains_null_bytes():
    """Test validate_review_request returns error when content contains null bytes"""
    data = {"content": "hello\x00world", "language": ALLOWED_LANGUAGES[0]}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "null bytes" in errors[0].reason


def test_validate_review_request_invalid_language_only():
    """Test validate_review_request returns error for invalid language when content is valid"""
    data = {"content": "print('hello')", "language": "invalid_lang"}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "language"
    assert "Language must be one of" in errors[0].reason


def test_validate_review_request_valid_payload_no_errors():
    """Test validate_review_request returns no errors for a valid payload"""
    data = {"content": "print('hello')", "language": "python"}
    errors = validate_review_request(data)
    assert errors == []


def test_validate_review_request_calls_keep_recent_errors_when_errors_present():
    """Test log_validation_errors is called by validate_review_request and triggers keep_recent_errors"""
    data = {"language": "invalid"}  # content missing triggers error
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        errors = validate_review_request(data)
        assert len(errors) >= 1
        mock_keep.assert_called_once()


def test_log_validation_errors_does_not_call_keep_recent_errors_for_empty_list():
    """Test that log_validation_errors does nothing with empty errors list"""
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        log_validation_errors([])
        mock_keep.assert_not_called()
    # Ensure global errors remain empty
    assert get_validation_errors() == []


def test_validate_statistics_request_no_files_key():
    """Test validate_statistics_request returns error when 'files' is missing"""
    data = {}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason.lower()


def test_validate_statistics_request_files_not_list():
    """Test validate_statistics_request returns error when 'files' is not a list"""
    data = {"files": "not-a-list"}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "array" in errors[0].reason.lower()


def test_validate_statistics_request_empty_list_triggers_required_message():
    """Test validate_statistics_request returns 'required' message for empty list due to falsy check"""
    data = {"files": []}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert "required" in errors[0].reason.lower()


def test_validate_statistics_request_list_too_large():
    """Test validate_statistics_request returns error when files list has more than 1000 entries"""
    data = {"files": [f"file_{i}" for i in range(1001)]}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert "cannot exceed 1000 entries" in errors[0].reason


def test_validate_statistics_request_valid_list_no_errors():
    """Test validate_statistics_request returns no errors for valid files list"""
    data = {"files": ["a.py", "b.py", "c.py"]}
    errors = validate_statistics_request(data)
    assert errors == []


def test_sanitize_input_none():
    """Test sanitize_input returns None when input is None"""
    assert sanitize_input(None) is None


def test_sanitize_input_non_string_cast_to_string():
    """Test sanitize_input casts non-string inputs to string"""
    class X:
        def __str__(self):
            return "X_str"
    assert sanitize_input(X()) == "X_str"


def test_sanitize_input_removes_control_and_preserves_whitespace():
    """Test sanitize_input removes control characters and preserves \\n, \\r, \\t"""
    s = "A\x00B\x01C\tD\nE\rF\x7fG"
    # \x00, \x01, \x7f are removed; \t, \n, \r preserved
    result = sanitize_input(s)
    assert result == "AB" + "\t" + "D" + "\n" + "E" + "\r" + "FG"


def test_sanitize_input_filters_non_printable_non_whitespace():
    """Test sanitize_input filters non-printable characters except allowed whitespace"""
    # Include a non-printable char: \x0e (14), should be removed
    s = "Hello\x0eWorld"
    assert sanitize_input(s) == "HelloWorld"


def test_sanitize_request_data_sanitizes_fields():
    """Test sanitize_request_data sanitizes content, language, and path fields"""
    data = {
        "content": "ok\x00",
        "language": "py\x7fthon",
        "path": "s\x00rc/file.py",
        "other": 123,  # untouched
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "ok"
    assert sanitized["language"] == "python"
    assert sanitized["path"] == "src/file.py"
    assert sanitized["other"] == 123


def test_sanitize_request_data_non_string_values_preserved():
    """Test sanitize_request_data leaves non-string values unchanged"""
    data = {"content": 123, "language": ["python"], "path": {"p": "x"}}
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "123"
    assert sanitized["language"] == ["python"]
    assert sanitized["path"] == {"p": "x"}


def test_contains_null_bytes_true_and_false():
    """Test contains_null_bytes identifies null bytes correctly"""
    assert contains_null_bytes("abc\x00def") is True
    assert contains_null_bytes("abcdef") is False


def test_contains_path_traversal_detection():
    """Test contains_path_traversal returns True for '..' and '~/' patterns"""
    assert contains_path_traversal("../etc/passwd") is True
    assert contains_path_traversal("~/secrets") is True
    assert contains_path_traversal("/safe/path/file.txt") is False


def test_log_validation_errors_appends_and_get_validation_errors_returns_copy():
    """Test that log_validation_errors appends errors and get_validation_errors returns a copy"""
    ve = ValidationError("field1", "reason1")
    log_validation_errors([ve])
    errs1 = get_validation_errors()
    assert isinstance(errs1, list)
    assert len(errs1) == 1
    assert errs1[0]["field"] == "field1"
    # Modify local copy; original should not change
    errs1.append({"field": "hijack"})
    errs2 = get_validation_errors()
    assert len(errs2) == 1


def test_keep_recent_errors_trims_to_last_100():
    """Test keep_recent_errors trims the stored errors to the last 100 entries"""
    # Populate more than 100 errors
    for i in range(105):
        log_validation_errors([ValidationError(f"f{i}", "r")])
    errors_before = get_validation_errors()
    assert len(errors_before) == 105
    keep_recent_errors()
    errors_after = get_validation_errors()
    assert len(errors_after) == 100
    # Ensure we kept the last 100 (i from 5..104)
    kept_fields = [e["field"] for e in errors_after]
    assert kept_fields[0] == "f5"
    assert kept_fields[-1] == "f104"


def test_validate_review_request_uses_contains_null_bytes_mocked():
    """Test validate_review_request path when contains_null_bytes returns True using a mock"""
    data = {"content": "safe-string", "language": ALLOWED_LANGUAGES[0]}
    with patch("src.request_validator.contains_null_bytes", return_value=True) as mock_cnb:
        errors = validate_review_request(data)
        mock_cnb.assert_called_once_with("safe-string")
        assert len(errors) == 1
        assert errors[0].field == "content"
        assert "null bytes" in errors[0].reason


def test_sanitize_input_exception_propagation_when_str_raises():
    """Test that sanitize_input propagates exception when str() of a non-string raises"""
    class BadStr:
        def __str__(self):
            raise ValueError("boom")
    with pytest.raises(ValueError):
        sanitize_input(BadStr())