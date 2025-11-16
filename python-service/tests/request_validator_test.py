import pytest
from unittest.mock import Mock, patch

from src.request_validator import ValidationError
import src.request_validator as rv


@pytest.fixture(autouse=True)
def clear_errors():
    """Automatically clear validation errors before and after each test."""
    rv.clear_validation_errors()
    yield
    rv.clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Create a ValidationError instance with a fixed timestamp."""
    expected_ts = "2023-05-06T07:08:09"
    with patch("src.request_validator.datetime") as mock_dt:
        mock_dt.now.return_value.isoformat.return_value = expected_ts
        err = ValidationError(field="content", reason="Invalid content")
        return err, expected_ts


def test_ValidationError___init___sets_fields_and_timestamp(validation_error_instance):
    """Test ValidationError initialization sets field, reason, and timestamp."""
    err, expected_ts = validation_error_instance
    assert err.field == "content"
    assert err.reason == "Invalid content"
    assert err.timestamp == expected_ts


def test_ValidationError_to_dict_returns_expected(validation_error_instance):
    """Test ValidationError.to_dict returns correct dictionary representation."""
    err, expected_ts = validation_error_instance
    result = err.to_dict()
    assert result == {
        "field": "content",
        "reason": "Invalid content",
        "timestamp": expected_ts,
    }


def test_validate_review_request_missing_content_logs_error():
    """Test validate_review_request returns error when content is missing."""
    errors = rv.validate_review_request({})
    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    assert errors[0].field == "content"
    assert "Content is required" in errors[0].reason

    log = rv.get_validation_errors()
    assert len(log) == 1
    assert log[0]["field"] == "content"


def test_validate_review_request_content_too_large():
    """Test validate_review_request returns error when content exceeds size."""
    big_content = "a" * (rv.MAX_CONTENT_SIZE + 1)
    errors = rv.validate_review_request({"content": big_content})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "exceeds maximum size" in errors[0].reason

    log = rv.get_validation_errors()
    assert len(log) == 1
    assert log[0]["field"] == "content"


def test_validate_review_request_content_contains_null_bytes():
    """Test validate_review_request returns error when content has null bytes."""
    errors = rv.validate_review_request({"content": "abc\x00def"})
    assert len(errors) == 1
    assert errors[0].field == "content"
    assert "invalid null bytes" in errors[0].reason


def test_validate_review_request_invalid_language():
    """Test validate_review_request returns error for unsupported language."""
    errors = rv.validate_review_request({"content": "ok", "language": "rust"})
    assert len(errors) == 1
    assert errors[0].field == "language"
    assert "must be one of" in errors[0].reason


def test_validate_review_request_valid_no_errors_logged():
    """Test validate_review_request with valid input returns no errors and logs nothing."""
    errors = rv.validate_review_request({"content": "ok", "language": "python"})
    assert errors == []
    assert rv.get_validation_errors() == []


def test_validate_statistics_request_files_missing():
    """Test validate_statistics_request returns error when files is missing."""
    errors = rv.validate_statistics_request({})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "Files array is required" in errors[0].reason


def test_validate_statistics_request_files_not_list():
    """Test validate_statistics_request returns error when files is not a list."""
    errors = rv.validate_statistics_request({"files": "not-a-list"})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "Files must be an array" in errors[0].reason


def test_validate_statistics_request_files_empty_triggers_required_message():
    """Test validate_statistics_request treats empty list as missing (per current logic)."""
    errors = rv.validate_statistics_request({"files": []})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "Files array is required" in errors[0].reason


def test_validate_statistics_request_files_too_many():
    """Test validate_statistics_request returns error when files exceed 1000 entries."""
    files = ["f"] * 1001
    errors = rv.validate_statistics_request({"files": files})
    assert len(errors) == 1
    assert errors[0].field == "files"
    assert "cannot exceed 1000" in errors[0].reason


def test_sanitize_input_removes_control_chars_and_keeps_whitespace():
    """Test sanitize_input removes disallowed control characters and keeps newlines/tabs."""
    input_str = "a\x00b\x07c\x0bd\x0ce\nf\rg\th\x1bi"
    # removes: 0, 7, 11, 12, 27 (ESC), keeps: \n, \r, \t
    result = rv.sanitize_input(input_str)
    assert result == "abcdef\ng\th" + "i".replace("\x1b", "")  # ensure ESC removed
    assert "\x00" not in result
    assert "\x07" not in result
    assert "\x0b" not in result
    assert "\x0c" not in result
    assert "\x1b" not in result
    assert "\n" in result and "\r" in result and "\t" in result


def test_sanitize_input_non_string_and_none():
    """Test sanitize_input converts non-string to str and passes None through."""
    assert rv.sanitize_input(123) == "123"
    assert rv.sanitize_input(None) is None


def test_sanitize_request_data_sanitizes_specific_fields_only():
    """Test sanitize_request_data only sanitizes content, language, and path keys."""
    data = {
        "content": "hello\x1bworld",
        "language": "py\x00thon",
        "path": "some\x0b/path",
        "other": "keep\x00as-is",
        "content_numeric": 42,
    }
    result = rv.sanitize_request_data(data)
    assert result["content"] == "helloworld"
    assert result["language"] == "python"
    assert result["path"] == "some/path"
    # other fields unchanged because not sanitized
    assert result["other"] == "keep\x00as-is"
    assert result["content_numeric"] == 42


def test_contains_null_bytes_detects_nulls():
    """Test contains_null_bytes correctly identifies presence of null bytes."""
    assert rv.contains_null_bytes("abc\x00def") is True
    assert rv.contains_null_bytes("abcdef") is False


def test_contains_path_traversal_detects_patterns():
    """Test contains_path_traversal detects '..' and '~/' substrings."""
    assert rv.contains_path_traversal("../secret") is True
    assert rv.contains_path_traversal("~/config") is True
    assert rv.contains_path_traversal("/safe/path") is False


def test_log_validation_errors_calls_keep_recent_errors_and_appends():
    """Test log_validation_errors calls keep_recent_errors and appends to log."""
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        rv.log_validation_errors([ValidationError("f", "r")])
        mock_keep.assert_called_once()
    stored = rv.get_validation_errors()
    assert len(stored) == 1
    assert stored[0]["field"] == "f"
    assert stored[0]["reason"] == "r"


def test_log_validation_errors_noop_when_no_errors():
    """Test log_validation_errors does nothing when given an empty list."""
    with patch("src.request_validator.keep_recent_errors") as mock_keep:
        rv.log_validation_errors([])
        mock_keep.assert_not_called()
    assert rv.get_validation_errors() == []


def test_keep_recent_errors_truncates_to_100_entries():
    """Test keep_recent_errors truncates the stored errors list to 100 entries."""
    rv.validation_errors = [{"field": f"f{i}", "reason": "r", "timestamp": "t"} for i in range(105)]
    rv.keep_recent_errors()
    assert len(rv.validation_errors) == 100
    # Ensure most recent are kept (i.e., last 100 from 5..104)
    assert rv.validation_errors[0]["field"] == "f5"
    assert rv.validation_errors[-1]["field"] == "f104"


def test_get_validation_errors_returns_copy_not_reference():
    """Test get_validation_errors returns a copy that does not affect the internal store."""
    rv.log_validation_errors([ValidationError("a", "b")])
    first = rv.get_validation_errors()
    first.append({"field": "hacked", "reason": "bad", "timestamp": "now"})
    second = rv.get_validation_errors()
    assert len(second) == 1
    assert second[0]["field"] == "a"


def test_log_validation_errors_exception_bubbles_and_store_unchanged():
    """Test log_validation_errors propagates exceptions from to_dict and leaves store unchanged."""
    bad_error = Mock()
    bad_error.to_dict.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        rv.log_validation_errors([bad_error])
    assert rv.get_validation_errors() == []