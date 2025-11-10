import pytest
from unittest.mock import patch
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
    get_validation_errors,
    clear_validation_errors,
    MAX_CONTENT_SIZE,
    ALLOWED_LANGUAGES,
)


@pytest.fixture(autouse=True)
def reset_validation_errors():
    """Ensure validation error storage is clean before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def fixed_datetime():
    """Provide a fixed datetime for deterministic timestamp testing."""
    return datetime(2023, 1, 1, 12, 34, 56, 789000)


@pytest.fixture
def error_instance(monkeypatch, fixed_datetime):
    """Create a ValidationError with a patched datetime.now for predictable timestamp."""
    monkeypatch.setattr('src.request_validator.datetime', 'now', lambda: fixed_datetime)
    return ValidationError(field="content", reason="Invalid content")


def test_validationerror_init_sets_fields_and_timestamp(monkeypatch, fixed_datetime):
    """Test ValidationError initialization sets field, reason, and a correct ISO timestamp."""
    monkeypatch.setattr('src.request_validator.datetime', 'now', lambda: fixed_datetime)
    err = ValidationError(field="language", reason="Not allowed")
    assert err.field == "language"
    assert err.reason == "Not allowed"
    assert err.timestamp == fixed_datetime.isoformat()


def test_validationerror_to_dict_returns_expected_keys(error_instance, fixed_datetime):
    """Test ValidationError.to_dict returns a dictionary with expected keys and values."""
    payload = error_instance.to_dict()
    assert set(payload.keys()) == {"field", "reason", "timestamp"}
    assert payload["field"] == "content"
    assert payload["reason"] == "Invalid content"
    assert payload["timestamp"] == fixed_datetime.isoformat()


def test_validationerror_timestamp_changes_between_instances():
    """Test different ValidationError instances get different timestamps (using mock side_effect)."""
    times = [
        datetime(2024, 1, 1, 0, 0, 0),
        datetime(2024, 1, 1, 0, 0, 1),
    ]
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.side_effect = times
        # Ensure isoformat is called on returned datetime
        mock_datetime.now.return_value.isoformat = datetime.now().isoformat  # not used due to side_effect
        e1 = ValidationError(field="f1", reason="r1")
        e2 = ValidationError(field="f2", reason="r2")
    assert e1.timestamp == times[0].isoformat()
    assert e2.timestamp == times[1].isoformat()
    assert e1.timestamp != e2.timestamp


def test_validate_review_request_missing_content_logs_error():
    """Test validate_review_request returns error for missing content and logs it."""
    data = {"language": "python"}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "cannot be empty" in errors[0].reason.lower()

    logged = get_validation_errors()
    assert len(logged) == 1
    assert logged[0]["field"] == "content"


def test_validate_review_request_oversized_content():
    """Test validate_review_request rejects content exceeding MAX_CONTENT_SIZE."""
    data = {"content": "a" * (MAX_CONTENT_SIZE + 1), "language": "python"}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert str(MAX_CONTENT_SIZE) in errors[0].reason


def test_validate_review_request_null_bytes_in_content():
    """Test validate_review_request rejects content containing null bytes."""
    data = {"content": "hello\x00world", "language": "python"}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "null bytes" in errors[0].reason.lower()


def test_validate_review_request_invalid_language_only():
    """Test validate_review_request returns error for invalid language and no other errors when content is OK."""
    data = {"content": "ok", "language": "rust"}
    errors = validate_review_request(data)
    assert len(errors) == 1
    assert errors[0].field == "language"
    # Should mention allowed languages
    for lang in ALLOWED_LANGUAGES:
        assert lang in errors[0].reason


def test_validate_review_request_valid_data_no_errors_and_no_logging():
    """Test validate_review_request with valid data returns no errors and does not log."""
    data = {"content": "print('hello')", "language": "python"}
    errors = validate_review_request(data)
    assert errors == []
    assert get_validation_errors() == []


def test_validate_statistics_request_missing_files_none():
    """Test validate_statistics_request returns error when 'files' is missing."""
    data = {}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason.lower()


def test_validate_statistics_request_files_not_list():
    """Test validate_statistics_request returns error when 'files' is not a list."""
    data = {"files": "not-a-list"}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "must be an array" in errors[0].reason.lower()


def test_validate_statistics_request_empty_list_is_required_error():
    """Test validate_statistics_request treats empty list as required error due to falsy check."""
    data = {"files": []}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "required" in errors[0].reason.lower()


def test_validate_statistics_request_too_many_files():
    """Test validate_statistics_request rejects arrays with more than 1000 entries."""
    data = {"files": list(range(1001))}
    errors = validate_statistics_request(data)
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000" in errors[0].reason.lower()


def test_validate_statistics_request_valid_small_list():
    """Test validate_statistics_request accepts a small valid list."""
    data = {"files": [1, 2, 3]}
    errors = validate_statistics_request(data)
    assert errors == []


def test_sanitize_input_removes_disallowed_control_chars():
    """Test sanitize_input removes disallowed control characters but keeps newline, carriage return, and tab."""
    dirty = "A\x00B\x01C\x07D\x0bE\x0cF\x0eG\x1fH\x7fI\nJ\rK\tL"
    # Expected to remove: 0,1,7,11,12,14,31,127 controls; keep \n, \r, \t and normal chars
    expected = "ABCDEFGHI\nJ\rK\tL"
    assert sanitize_input(dirty) == expected


def test_sanitize_input_non_string_is_coerced_to_string():
    """Test sanitize_input coerces non-string inputs to string."""
    assert sanitize_input(123) == "123"


def test_sanitize_input_none_returns_none():
    """Test sanitize_input returns None unchanged when input is None."""
    assert sanitize_input(None) is None


def test_sanitize_request_data_sanitizes_specific_fields():
    """Test sanitize_request_data only sanitizes 'content', 'language', and 'path' when they are strings."""
    data = {
        "content": "ok\x00ay",
        "language": "py\x01thon",
        "path": "../bad/\x7fpath",
        "other": "left\x00alone",  # not sanitized since not in target keys
        "count": 5,  # not string, remains unchanged
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "okay"
    assert sanitized["language"] == "python"
    assert sanitized["path"] == "../bad/path"
    assert sanitized["other"] == "left\x00alone"
    assert sanitized["count"] == 5


def test_contains_null_bytes_true_and_false():
    """Test contains_null_bytes returns True when null bytes present, False otherwise."""
    assert contains_null_bytes("abc\x00def") is True
    assert contains_null_bytes("abcdef") is False


def test_contains_null_bytes_raises_typeerror_with_bytes():
    """Test contains_null_bytes raises TypeError when provided non-string input (bytes)."""
    with pytest.raises(TypeError):
        contains_null_bytes(b"\x00\x01")  # type: ignore[arg-type]


def test_contains_path_traversal_detection():
    """Test contains_path_traversal detects '..' and '~/' patterns."""
    assert contains_path_traversal("../etc/passwd") is True
    assert contains_path_traversal("~/config") is True
    assert contains_path_traversal("/safe/path/file.txt") is False
    assert contains_path_traversal("folder/..hidden") is True  # substring '..' present


def test_log_validation_errors_appends_and_keep_recent():
    """Test log_validation_errors appends errors and keep_recent caps at 100 most recent."""
    # Add 105 errors
    for i in range(105):
        log_validation_errors([ValidationError(field=f"f{i}", reason=f"r{i}")])
    logged = get_validation_errors()
    assert len(logged) == 100
    # Ensure they are the most recent 100 (i from 5..104)
    fields = [e["field"] for e in logged]
    assert fields[0] == "f5"
    assert fields[-1] == "f104"


def test_clear_validation_errors_empties_log():
    """Test clear_validation_errors empties the global validation error log."""
    log_validation_errors([ValidationError(field="x", reason="y")])
    assert len(get_validation_errors()) == 1
    clear_validation_errors()
    assert get_validation_errors() == []


def test_validate_review_request_language_skipped_when_empty():
    """Test validate_review_request does not validate language when not provided or empty."""
    # no language
    errors = validate_review_request({"content": "ok"})
    assert errors == []
    # empty language string
    errors = validate_review_request({"content": "ok", "language": ""})
    assert errors == []


def test_validate_review_request_combined_content_and_language_errors():
    """Test validate_review_request can return both content and language errors when applicable."""
    data = {"content": "", "language": "not-allowed"}
    errors = validate_review_request(data)
    # For empty content, we should get content error; language is still validated since provided
    # but language validation only occurs if content passes earlier checks? No, language check is independent.
    # However, content empty triggers error; language invalid also triggers error.
    assert len(errors) == 2
    fields = sorted([e.field for e in errors])
    assert fields == ["content", "language"]