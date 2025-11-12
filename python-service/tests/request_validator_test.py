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
    get_validation_errors,
    clear_validation_errors,
    log_validation_errors,
    keep_recent_errors,
    MAX_CONTENT_SIZE,
)


@pytest.fixture(autouse=True)
def clear_errors_before_after():
    """Ensure global validation error store is cleared before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Create a ValidationError instance for testing."""
    return ValidationError(field="content", reason="Content is required and cannot be empty")


def test_ValidationError___init___sets_attributes(validation_error_instance):
    """ValidationError.__init__ should set field, reason and create an ISO8601 timestamp."""
    assert validation_error_instance.field == "content"
    assert validation_error_instance.reason == "Content is required and cannot be empty"

    # Ensure timestamp appears to be ISO8601 parseable
    from datetime import datetime

    # Should not raise
    parsed = datetime.fromisoformat(validation_error_instance.timestamp)
    assert isinstance(parsed, datetime)


def test_ValidationError___init___uses_datetime_now_isoformat():
    """ValidationError.__init__ should use datetime.now().isoformat() for timestamp."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = "2020-01-01T00:00:00"
        mock_datetime.now.return_value = mock_now

        ve = ValidationError(field="language", reason="Invalid language")
        assert ve.timestamp == "2020-01-01T00:00:00"


def test_ValidationError_to_dict_includes_all_fields(validation_error_instance):
    """ValidationError.to_dict should include field, reason, and timestamp with correct values."""
    d = validation_error_instance.to_dict()
    assert d["field"] == "content"
    assert d["reason"] == "Content is required and cannot be empty"
    assert isinstance(d["timestamp"], str)
    assert "T" in d["timestamp"]  # basic ISO-8601 shape check


def test_ValidationError_to_dict_preserves_timestamp():
    """ValidationError.to_dict should return the same timestamp set at initialization."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = "2021-05-05T12:34:56"
        mock_datetime.now.return_value = mock_now

        ve = ValidationError(field="path", reason="Invalid path")
        d = ve.to_dict()
        assert d["timestamp"] == "2021-05-05T12:34:56"


def test_validate_review_request_missing_content_logs_error():
    """validate_review_request should return and log an error when content is missing."""
    errors = validate_review_request({})
    assert len(errors) == 1
    err = errors[0]
    assert err.field == "content"
    assert "Content is required" in err.reason

    # Ensure it's logged
    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "content"
    assert "Content is required" in logged[0]["reason"]


def test_validate_review_request_invalid_language():
    """validate_review_request should return error when language is not in allowed list."""
    errors = validate_review_request({"content": "print('hello')", "language": "c++"})
    assert len(errors) == 1
    assert errors[0].field == "language"
    assert "Language must be one of" in errors[0].reason


def test_validate_review_request_content_too_large():
    """validate_review_request should reject content larger than MAX_CONTENT_SIZE."""
    big_content = "a" * (MAX_CONTENT_SIZE + 1)
    errors = validate_review_request({"content": big_content, "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "exceeds maximum size" in errors[0].reason


def test_validate_review_request_content_contains_null_bytes():
    """validate_review_request should reject content containing null bytes."""
    errors = validate_review_request({"content": "abc\x00def", "language": "python"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "null bytes" in errors[0].reason


def test_validate_review_request_no_errors_no_log():
    """validate_review_request should not log when there are no validation errors."""
    assert len(get_validation_errors()) == 0
    errors = validate_review_request({"content": "ok", "language": "python"})
    assert errors == []
    assert len(get_validation_errors()) == 0


def test_validate_statistics_request_files_missing():
    """validate_statistics_request should error if 'files' is missing."""
    errors = validate_statistics_request({})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason


def test_validate_statistics_request_files_not_list():
    """validate_statistics_request should error if 'files' is not a list."""
    errors = validate_statistics_request({"files": "not-a-list"})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "must be an array" in errors[0].reason


def test_validate_statistics_request_files_empty_list():
    """validate_statistics_request should error if 'files' is an empty list."""
    errors = validate_statistics_request({"files": []})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot be empty" in errors[0].reason


def test_validate_statistics_request_files_too_many():
    """validate_statistics_request should error if 'files' has more than 1000 entries."""
    files = [f"f{i}" for i in range(1001)]
    errors = validate_statistics_request({"files": files})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000" in errors[0].reason


def test_validate_statistics_request_valid():
    """validate_statistics_request should succeed with a valid files list."""
    errors = validate_statistics_request({"files": ["a", "b", "c"]})
    assert errors == []


@pytest.mark.parametrize(
    "input_value,expected",
    [
        (None, None),
        (123, "123"),
        ("abc", "abc"),
        ("abc\x00def", "abcdef"),
        ("a\x07b\x1Fc", "abc"),  # remove bell and unit separator
        ("line1\nline2\tend\r", "line1\nline2\tend\r"),  # keep \n, \t, \r
    ],
)
def test_sanitize_input_various_cases(input_value, expected):
    """sanitize_input should handle None, non-strings, control chars, and preserve allowed whitespace."""
    assert sanitize_input(input_value) == expected


def test_sanitize_request_data_fields():
    """sanitize_request_data should sanitize content, language, and path fields if present."""
    data = {
        "content": "ok\x00bad\n",
        "language": "pyt\x07hon",
        "path": "/tmp/\x00file.txt",
        "ignored": {"a": 1},  # should remain untouched
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "okbad\n"
    assert sanitized["language"] == "python"
    assert sanitized["path"] == "/tmp/file.txt"
    assert sanitized["ignored"] == {"a": 1}


@pytest.mark.parametrize(
    "content,expected",
    [
        ("abc", False),
        ("abc\x00def", True),
        ("\x00", True),
        ("", False),
    ],
)
def test_contains_null_bytes(content, expected):
    """contains_null_bytes should detect presence of null byte in string."""
    assert contains_null_bytes(content) is expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/safe/path/file.txt", False),
        ("../../etc/passwd", True),
        ("~/secrets.txt", True),
        ("./relative/path", False),
    ],
)
def test_contains_path_traversal(path, expected):
    """contains_path_traversal should detect '..' and '~/' in paths."""
    assert contains_path_traversal(path) is expected


def test_log_validation_errors_accumulates_and_crops():
    """log_validation_errors should store errors and keep only the most recent 100."""
    # Add 105 errors and ensure only last 100 remain
    errors = [ValidationError(field=f"f{i}", reason=f"r{i}") for i in range(105)]
    log_validation_errors(errors)

    logged = get_validation_errors()
    assert len(logged) == 100

    # Verify they are the most recent 100 (i.e., from index 5 to 104)
    expected_fields = [f"f{i}" for i in range(5, 105)]
    actual_fields = [e["field"] for e in logged]
    assert actual_fields == expected_fields


def test_keep_recent_errors_within_limit_noop():
    """keep_recent_errors should not alter the list when size is under or equal to 100."""
    # Log 3 errors
    errs = [ValidationError(field=f"a{i}", reason="x") for i in range(3)]
    log_validation_errors(errs)
    before = get_validation_errors()
    keep_recent_errors()
    after = get_validation_errors()
    assert before == after