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
    keep_recent_errors,
    MAX_CONTENT_SIZE,
    ALLOWED_LANGUAGES,
)


@pytest.fixture
def fixed_timestamp():
    """Patch datetime.now().isoformat() to return a fixed timestamp string."""
    fixed = "2023-01-02T03:04:05"

    class DummyNow:
        def isoformat(self):
            return fixed

    class DummyDatetime:
        @classmethod
        def now(cls):
            return DummyNow()

    with patch("src.request_validator.datetime", DummyDatetime):
        yield fixed


@pytest.fixture
def validation_error_minimal(fixed_timestamp):
    """Create a minimal ValidationError instance with a fixed timestamp."""
    return ValidationError(field="content", reason="Required")


@pytest.fixture(autouse=True)
def clear_validation_store_before_after():
    """Ensure validation_errors store is cleared before and after each test."""
    clear_validation_errors()
    yield
    clear_validation_errors()


def test_validationerror_init_basic(validation_error_minimal, fixed_timestamp):
    """ValidationError __init__ sets field, reason, and timestamp."""
    err = validation_error_minimal
    assert err.field == "content"
    assert err.reason == "Required"
    # Timestamp should match the patched fixed timestamp
    assert err.timestamp == fixed_timestamp


def test_validationerror_to_dict_contains_expected_keys(validation_error_minimal, fixed_timestamp):
    """ValidationError.to_dict returns a dict with field, reason, timestamp."""
    d = validation_error_minimal.to_dict()
    assert d["field"] == "content"
    assert d["reason"] == "Required"
    assert d["timestamp"] == fixed_timestamp
    # Only expected keys should be present
    assert set(d.keys()) == {"field", "reason", "timestamp"}


def test_validationerror_allows_non_string_values(fixed_timestamp):
    """ValidationError can store non-string values and include them in to_dict."""
    err = ValidationError(field=123, reason=None)
    d = err.to_dict()
    assert d["field"] == 123
    assert d["reason"] is None
    assert "timestamp" in d and isinstance(d["timestamp"], str)


def test_validationerror_timestamp_unpatched_format():
    """ValidationError timestamp is a non-empty ISO-like string when not patched."""
    err = ValidationError(field="test", reason="reason")
    ts = err.timestamp
    assert isinstance(ts, str)
    assert "T" in ts  # ISO 8601 usually includes 'T' between date and time


def test_log_validation_errors_appends_and_trims(fixed_timestamp):
    """log_validation_errors appends errors and trims to last 100 entries."""
    # Append 105 errors to trigger trimming
    for i in range(105):
        errs = [ValidationError(field=f"f{i}", reason="r")]
        log_validation_errors(errs)

    stored = get_validation_errors()
    assert len(stored) == 100
    # The first 5 should be trimmed off; start from f5
    assert stored[0]["field"] == "f5"
    assert stored[-1]["field"] == "f104"


def test_get_validation_errors_returns_copy(fixed_timestamp):
    """get_validation_errors returns a copy, not a reference to internal list."""
    log_validation_errors([ValidationError(field="a", reason="b")])
    copy1 = get_validation_errors()
    copy1.clear()
    copy2 = get_validation_errors()
    assert len(copy2) == 1
    assert copy2[0]["field"] == "a"


def test_clear_validation_errors_empties_store(fixed_timestamp):
    """clear_validation_errors empties the error store."""
    log_validation_errors([ValidationError(field="x", reason="y")])
    assert len(get_validation_errors()) == 1
    clear_validation_errors()
    assert len(get_validation_errors()) == 0


def test_validate_review_request_missing_content_calls_logger():
    """validate_review_request returns error when content is missing and calls logger."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_review_request({"language": "python"})
        assert len(errs) == 1
        assert errs[0].field == "content"
        assert "required" in errs[0].reason.lower()
        mock_log.assert_called_once()
        logged = mock_log.call_args[0][0]
        assert len(logged) == 1


def test_validate_review_request_empty_content():
    """validate_review_request treats empty content as invalid."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_review_request({"content": "", "language": "python"})
        assert len(errs) == 1
        assert errs[0].field == "content"
        mock_log.assert_called_once()


def test_validate_review_request_content_too_large():
    """validate_review_request returns error when content exceeds MAX_CONTENT_SIZE."""
    big_content = "a" * (MAX_CONTENT_SIZE + 1)
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_review_request({"content": big_content, "language": "python"})
        assert len(errs) == 1
        assert errs[0].field == "content"
        assert "exceeds maximum size" in errs[0].reason
        mock_log.assert_called_once()


def test_validate_review_request_null_bytes_in_content():
    """validate_review_request detects and rejects content containing null bytes."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_review_request({"content": "abc\x00def", "language": "python"})
        assert len(errs) == 1
        assert errs[0].field == "content"
        assert "null bytes" in errs[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_review_request_invalid_language():
    """validate_review_request returns error when language is not allowed."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_review_request({"content": "ok", "language": "php"})
        assert len(errs) == 1
        assert errs[0].field == "language"
        assert all(lang in errs[0].reason for lang in ALLOWED_LANGUAGES)
        mock_log.assert_called_once()


def test_validate_review_request_valid_data_calls_logger_with_empty_list():
    """validate_review_request calls logger with empty list when there are no errors."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_review_request({"content": "ok", "language": ALLOWED_LANGUAGES[0]})
        assert errs == []
        # Even with no errors, the function calls the logger with an empty list
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == []


def test_validate_statistics_request_missing_files():
    """validate_statistics_request returns error when files key is missing."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_statistics_request({})
        assert len(errs) == 1
        assert errs[0].field == "files"
        assert "required" in errs[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_files_not_list():
    """validate_statistics_request returns error when files is not a list."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_statistics_request({"files": "not-a-list"})
        assert len(errs) == 1
        assert errs[0].field == "files"
        assert "array" in errs[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_files_empty():
    """validate_statistics_request returns error when files list is empty."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_statistics_request({"files": []})
        assert len(errs) == 1
        assert errs[0].field == "files"
        assert "cannot be empty" in errs[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_files_too_many():
    """validate_statistics_request returns error when files list exceeds 1000 entries."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_statistics_request({"files": [0] * 1001})
        assert len(errs) == 1
        assert errs[0].field == "files"
        assert "cannot exceed 1000" in errs[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_valid_calls_logger_with_empty_list():
    """validate_statistics_request calls logger with empty list when input is valid."""
    with patch("src.request_validator.log_validation_errors") as mock_log:
        errs = validate_statistics_request({"files": ["a", "b"]})
        assert errs == []
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == []


def test_sanitize_input_removes_control_chars_and_preserves_whitespace():
    """sanitize_input removes disallowed control chars but preserves \\n, \\r, \\t."""
    s = "A\x00B\x01C\x0BD\x0EE\tF\nG\rH\x7fI"
    sanitized = sanitize_input(s)
    assert sanitized == "ABCDE\tF\nG\rHI"


def test_sanitize_input_none_and_non_string():
    """sanitize_input returns None for None and str(value) for non-strings."""
    assert sanitize_input(None) is None
    assert sanitize_input(123) == "123"
    assert sanitize_input(True) == "True"


def test_sanitize_request_data_applies_to_specific_fields():
    """sanitize_request_data only sanitizes content, language, and path fields."""
    data = {
        "content": "Hello\x00World",
        "language": "py\x01thon",
        "path": "~/bad\x7fpath",
        "other": "unchanged\x00",  # Not sanitized because not listed
    }
    sanitized = sanitize_request_data(data)
    assert sanitized["content"] == "HelloWorld"
    assert sanitized["language"] == "python"
    assert sanitized["path"] == "~/badpath"
    assert sanitized["other"] == "unchanged\x00"  # unchanged


def test_contains_null_bytes():
    """contains_null_bytes returns True when string includes null byte."""
    assert contains_null_bytes("abc\x00def") is True
    assert contains_null_bytes("abcdef") is False


def test_contains_path_traversal():
    """contains_path_traversal detects '..' and '~/' substrings."""
    assert contains_path_traversal("../etc/passwd") is True
    assert contains_path_traversal("safe/path") is False
    assert contains_path_traversal("~/file") is True
    assert contains_path_traversal("user~file") is False


def test_keep_recent_errors_trims_when_called_directly(fixed_timestamp):
    """keep_recent_errors trims the global store to last 100 entries when called directly."""
    # Populate internal store directly via logger
    for i in range(120):
        log_validation_errors([ValidationError(field=f"z{i}", reason="r")])

    # Now call keep_recent_errors explicitly and verify it's still <= 100
    keep_recent_errors()
    stored = get_validation_errors()
    assert len(stored) == 100
    assert stored[0]["field"] == "z20"
    assert stored[-1]["field"] == "z119"