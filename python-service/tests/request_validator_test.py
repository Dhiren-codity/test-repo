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
def clear_errors_storage():
    """Ensure validation errors storage is cleared before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Create ValidationError instance with standard timestamp."""
    return ValidationError(field="field", reason="reason")


@pytest.fixture
def validation_error_fixed_timestamp():
    """Create ValidationError instance with a fixed, mocked timestamp."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = "2025-01-01T12:34:56"
        mock_datetime.now.return_value = mock_now
        yield ValidationError(field="test_field", reason="test_reason")


def test_ValidationError___init___sets_fields_and_timestamp(validation_error_fixed_timestamp):
    """Test that ValidationError initializes with correct fields and mocked timestamp."""
    err = validation_error_fixed_timestamp
    assert err.field == "test_field"
    assert err.reason == "test_reason"
    assert err.timestamp == "2025-01-01T12:34:56"


def test_ValidationError___init___allows_empty_strings():
    """Test that ValidationError handles empty strings for field and reason."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = "2000-01-01T00:00:00"
        mock_datetime.now.return_value = mock_now
        err = ValidationError(field="", reason="")
    assert err.field == ""
    assert err.reason == ""
    assert err.timestamp == "2000-01-01T00:00:00"


def test_ValidationError_to_dict_returns_expected_mapping():
    """Test that to_dict returns the correct structure and values."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = "X"
        mock_datetime.now.return_value = mock_now
        err = ValidationError(field="f", reason="r")
    d = err.to_dict()
    assert d == {"field": "f", "reason": "r", "timestamp": "X"}


def test_validate_review_request_missing_content_logs_error_and_returns_list():
    """Test validate_review_request returns error when content is missing and logs it."""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_review_request({"language": "python"})
        assert len(errors) == 1
        assert isinstance(errors[0], ValidationError)
        assert errors[0].field == "content"
        assert "required" in errors[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_review_request_logs_to_global_errors_storage():
    """Test that validate_review_request logs ValidationError into global storage."""
    errors = validate_review_request({})
    assert len(errors) == 1
    assert errors[0].field == "content"
    stored = get_validation_errors()
    assert len(stored) == 1
    assert stored[0]["field"] == "content"
    assert "timestamp" in stored[0]


def test_validate_review_request_valid_input_calls_logger_with_empty_list():
    """Test that validate_review_request with valid input calls logger with empty list."""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_review_request({"content": "hello", "language": "python"})
        assert errors == []
        mock_log.assert_called_once()
        # Ensure it was called with an empty list
        call_args = mock_log.call_args[0][0]
        assert isinstance(call_args, list)
        assert len(call_args) == 0


def test_validate_review_request_content_too_large():
    """Test validate_review_request returns error if content exceeds MAX_CONTENT_SIZE."""
    oversized = "a" * (MAX_CONTENT_SIZE + 1)
    errors = validate_review_request({"content": oversized, "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert str(MAX_CONTENT_SIZE) in errors[0].reason


def test_validate_review_request_content_contains_null_bytes():
    """Test validate_review_request returns error if content contains null bytes."""
    content = "hello\x00world"
    errors = validate_review_request({"content": content, "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "null bytes" in errors[0].reason.lower()


def test_validate_review_request_invalid_language():
    """Test validate_review_request returns error for unsupported language."""
    data = {"content": "print('hi')", "language": "csharp"}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "language"
    for lang in ALLOWED_LANGUAGES:
        assert lang in errors[0].reason


def test_validate_review_request_language_optional():
    """Test that language being absent does not produce an error."""
    errors = validate_review_request({"content": "ok"})
    assert errors == []


def test_validate_statistics_request_missing_files():
    """Test validate_statistics_request returns error when files key is missing."""
    errors = validate_statistics_request({})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason.lower()


def test_validate_statistics_request_files_not_list():
    """Test validate_statistics_request returns error when files is not a list."""
    errors = validate_statistics_request({"files": "not-a-list"})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "array" in errors[0].reason.lower()


def test_validate_statistics_request_files_empty():
    """Test validate_statistics_request returns error when files list is empty."""
    errors = validate_statistics_request({"files": []})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot be empty" in errors[0].reason.lower()


def test_validate_statistics_request_files_too_many():
    """Test validate_statistics_request returns error when more than 1000 files are provided."""
    errors = validate_statistics_request({"files": [str(i) for i in range(1001)]})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000" in errors[0].reason.lower()


def test_validate_statistics_request_valid_calls_logger_with_empty_list():
    """Test validate_statistics_request with valid input calls logger with empty list."""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_statistics_request({"files": ["a", "b", "c"]})
        assert errors == []
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == []


def test_sanitize_input_none_returns_none():
    """Test sanitize_input returns None when given None."""
    assert sanitize_input(None) is None


def test_sanitize_input_non_string_converted_to_string():
    """Test sanitize_input converts non-string input to string."""
    assert sanitize_input(123) == "123"
    assert sanitize_input(True) == "True"


def test_sanitize_input_removes_control_chars_and_preserves_whitespace():
    """Test sanitize_input removes control chars but preserves newline, carriage return, and tab."""
    raw = "A\0B\x01C\x02D\x03E\x04F\x05G\x06H\x07I\x0bJ\x0cK\x0eL\x1fM\x7fN\nO\rP\tQ\u200bR"
    sanitized = sanitize_input(raw)
    assert sanitized == "ABCDEFGHIJKLMN\nO\rP\tQR"


def test_sanitize_input_printable_unchanged():
    """Test sanitize_input leaves printable text unchanged."""
    s = "Hello, World! 123 ~!@#$%^&*()_+[]{}|;:',.<>/?"
    assert sanitize_input(s) == s


def test_sanitize_request_data_sanitizes_expected_fields_only():
    """Test sanitize_request_data sanitizes content, language, and path fields."""
    data = {
        "content": "ok\0val\n",
        "language": "py\x00thon",
        "path": "dir/..\x00/file",
        "other": 42,  # untouched
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "okval\n"
    assert sanitized["language"] == "python"
    # Null byte removed; traversal sequence remains since not removed by sanitize_input
    assert sanitized["path"] == "dir/../file"
    assert sanitized["other"] == 42


def test_contains_null_bytes_behavior():
    """Test contains_null_bytes correctly identifies presence of null bytes."""
    assert contains_null_bytes("abc\x00def") is True
    assert contains_null_bytes("abcdef") is False


def test_contains_path_traversal_behavior():
    """Test contains_path_traversal detects traversal patterns."""
    assert contains_path_traversal("../etc/passwd") is True
    assert contains_path_traversal("some/../../path") is True
    assert contains_path_traversal("~/secrets") is True
    assert contains_path_traversal("/safe/path/file.txt") is False


def test_log_validation_errors_adds_entries_and_trims_to_100():
    """Test log_validation_errors stores only the 100 most recent entries."""
    # Log 105 errors (one per call), resulting in only last 100 kept
    for i in range(105):
        with patch('src.request_validator.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.isoformat.return_value = f"t{i}"
            mock_datetime.now.return_value = mock_now
            err = ValidationError(field=f"f{i}", reason="r")
        log_validation_errors([err])

    stored = get_validation_errors()
    assert len(stored) == 100
    # Expect fields f5..f104 (last 100)
    expected_fields = [f"f{i}" for i in range(5, 105)]
    assert [e["field"] for e in stored] == expected_fields


def test_get_validation_errors_returns_copy():
    """Test get_validation_errors returns a defensive copy."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = "t"
        mock_datetime.now.return_value = mock_now
        err = ValidationError(field="f", reason="r")
    log_validation_errors([err])

    snapshot = get_validation_errors()
    assert len(snapshot) == 1
    snapshot.clear()
    # Original storage remains intact
    assert len(get_validation_errors()) == 1


def test_keep_recent_errors_trims_global_list():
    """Test keep_recent_errors trims the global list when exceeding 100 entries."""
    # Populate >100 entries using the public API
    for i in range(120):
        with patch('src.request_validator.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.isoformat.return_value = f"t{i}"
            mock_datetime.now.return_value = mock_now
            err = ValidationError(field=f"z{i}", reason="r")
        log_validation_errors([err])

    # Explicitly call keep_recent_errors again (no-op expected)
    keep_recent_errors()
    stored = get_validation_errors()
    assert len(stored) == 100
    assert stored[0]["field"] == "z20"
    assert stored[-1]["field"] == "z119"


def test_log_validation_errors_propagates_exception_from_keep_recent_errors():
    """Test that log_validation_errors propagates exceptions thrown by keep_recent_errors."""
    with patch('src.request_validator.keep_recent_errors', side_effect=RuntimeError("boom")):
        with patch('src.request_validator.datetime') as mock_datetime:
            mock_now = Mock()
            mock_now.isoformat.return_value = "t"
            mock_datetime.now.return_value = mock_now
            err = ValidationError(field="exc", reason="r")
        with pytest.raises(RuntimeError):
            log_validation_errors([err])