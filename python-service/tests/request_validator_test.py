import pytest
from unittest.mock import patch

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
)


@pytest.fixture(autouse=True)
def reset_validation_errors():
    """Ensure validation error store is clean before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def fixed_datetime():
    """Patch datetime.now() to return a fixed datetime for deterministic timestamps."""
    from datetime import datetime

    fixed_dt = datetime(2020, 1, 1, 12, 0, 0)
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed_dt
        yield fixed_dt


@pytest.fixture
def validation_error_instance(fixed_datetime):
    """Create a ValidationError with a deterministic timestamp."""
    return ValidationError(field="content", reason="Invalid content")


def test_ValidationError___init___sets_fields_and_timestamp(validation_error_instance, fixed_datetime):
    """ValidationError initialization sets field, reason, and an ISO timestamp."""
    err = validation_error_instance
    assert err.field == "content"
    assert err.reason == "Invalid content"
    assert err.timestamp == fixed_datetime.isoformat()


def test_ValidationError_to_dict_returns_expected_keys(validation_error_instance, fixed_datetime):
    """to_dict should return a dictionary with field, reason, and timestamp."""
    d = validation_error_instance.to_dict()
    assert set(d.keys()) == {"field", "reason", "timestamp"}
    assert d["field"] == "content"
    assert d["reason"] == "Invalid content"
    assert d["timestamp"] == fixed_datetime.isoformat()


def test_validate_review_request_missing_content_and_invalid_language_logged():
    """validate_review_request returns errors for missing content and invalid language and logs them."""
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        errors = validate_review_request({"content": "", "language": "invalid_lang"})
        assert len(errors) == 2
        assert errors[0].field == "content"
        assert "Content is required" in errors[0].reason
        assert errors[1].field == "language"
        assert "Language must be one of" in errors[1].reason

        logged = get_validation_errors()
        assert len(logged) == 2
        assert logged[0]["field"] == "content"
        assert logged[1]["field"] == "language"
        mock_keep.assert_called_once()


def test_validate_review_request_content_too_large():
    """validate_review_request returns an error when content exceeds MAX_CONTENT_SIZE."""
    content = "a" * (MAX_CONTENT_SIZE + 1)
    errors = validate_review_request({"content": content, "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "exceeds maximum size" in errors[0].reason


def test_validate_review_request_content_contains_null_bytes():
    """validate_review_request returns an error when content contains null bytes."""
    errors = validate_review_request({"content": "hello\x00world", "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "invalid null bytes" in errors[0].reason


def test_validate_review_request_valid_data_no_errors_and_not_logged():
    """validate_review_request returns no errors and does not log when data is valid."""
    errors = validate_review_request({"content": "print('hi')", "language": "python"})
    assert errors == []
    assert get_validation_errors() == []


def test_validate_statistics_request_missing_files_key_or_none():
    """validate_statistics_request errors when files key is missing or None."""
    errors_missing = validate_statistics_request({})
    assert len(errors_missing) == 1
    assert errors_missing[0].field == "files"
    assert "Files array is required" in errors_missing[0].reason

    errors_none = validate_statistics_request({"files": None})
    assert len(errors_none) == 1
    assert errors_none[0].field == "files"
    assert "Files array is required" in errors_none[0].reason


def test_validate_statistics_request_files_not_list():
    """validate_statistics_request errors when files is not a list."""
    errors = validate_statistics_request({"files": "not-a-list"})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "Files must be an array" in errors[0].reason


def test_validate_statistics_request_empty_list_current_behavior():
    """validate_statistics_request returns 'required' message for empty list due to truthiness check."""
    errors = validate_statistics_request({"files": []})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "Files array is required" in errors[0].reason


def test_validate_statistics_request_too_many_files():
    """validate_statistics_request errors when files list has more than 1000 entries."""
    errors = validate_statistics_request({"files": list(range(1001))})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000 entries" in errors[0].reason


def test_sanitize_input_none_and_non_string():
    """sanitize_input returns None for None and str(value) for non-string inputs."""
    assert sanitize_input(None) is None
    assert sanitize_input(123) == "123"
    assert sanitize_input(False) == "False"


def test_sanitize_input_removes_control_chars_and_keeps_whitespace():
    """sanitize_input strips control characters except for newlines, carriage returns, and tabs."""
    s = "A\x00B\x01C\x0bD\x0eE\tF\nG\rH\u007FI"
    # Expected: remove 0x00, 0x01, 0x0b, 0x0e, 0x7f; keep \t, \n, \r
    expected = "ABCDE\tF\nG\rHI"
    assert sanitize_input(s) == expected


def test_sanitize_request_data_sanitizes_selected_fields_only():
    """sanitize_request_data sanitizes 'content', 'language', and 'path' but leaves other keys intact."""
    data = {
        "content": "hi\x00",
        "language": "py\u007f",
        "path": "..\x01/tmp",
        "other": "ok\x00",
        "number": 5,
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "hi"
    assert sanitized["language"] == "py"
    assert sanitized["path"] == "../tmp"
    # Other fields unchanged
    assert sanitized["other"] == "ok\x00"
    assert sanitized["number"] == 5


def test_contains_null_bytes_true_and_false():
    """contains_null_bytes detects presence of null bytes."""
    assert contains_null_bytes("abc\x00def") is True
    assert contains_null_bytes("abcdef") is False


def test_contains_path_traversal_true_and_false():
    """contains_path_traversal detects '..' or '~/' sequences."""
    assert contains_path_traversal("../etc/passwd") is True
    assert contains_path_traversal("~/secrets") is True
    assert contains_path_traversal("/safe/path/file.txt") is False


def test_log_validation_errors_caps_to_last_100():
    """log_validation_errors keeps only the last 100 errors."""
    for i in range(105):
        log_validation_errors([ValidationError(field="f", reason=f"r{i}")])

    logged = get_validation_errors()
    assert len(logged) == 100
    # Should contain r5 through r104
    reasons = [e["reason"] for e in logged]
    assert reasons[0] == "r5"
    assert reasons[-1] == "r104"


def test_get_validation_errors_returns_copy_not_reference():
    """get_validation_errors returns a copy; modifying it does not affect the stored list."""
    log_validation_errors([ValidationError(field="a", reason="b")])
    first = get_validation_errors()
    first.append({"field": "x", "reason": "y", "timestamp": "z"})
    second = get_validation_errors()
    assert len(first) == 2
    assert len(second) == 1  # unaffected by modification of copy


def test_sanitize_input_raises_when_str_raises():
    """sanitize_input propagates exceptions if coercion to str fails."""
    class BadStr:
        def __str__(self):
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        sanitize_input(BadStr())