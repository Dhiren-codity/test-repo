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
    get_validation_errors,
    clear_validation_errors,
    keep_recent_errors,
    MAX_CONTENT_SIZE,
)


@pytest.fixture(autouse=True)
def clear_validation_store():
    """Ensure validation error store is clean before and after each test"""
    clear_validation_errors()
    yield
    clear_validation_errors()


@pytest.fixture
def validation_error_instance():
    """Create ValidationError instance with a fixed timestamp"""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = MagicMock()
        mock_now.isoformat.return_value = '2021-01-01T00:00:00'
        mock_datetime.now.return_value = mock_now
        return ValidationError(field='content', reason='Invalid content')


def test_ValidationError___init___sets_fields_and_timestamp(validation_error_instance):
    """Test that ValidationError initializes field, reason, and timestamp"""
    assert validation_error_instance.field == 'content'
    assert validation_error_instance.reason == 'Invalid content'
    assert validation_error_instance.timestamp == '2021-01-01T00:00:00'


def test_ValidationError_to_dict_returns_expected(validation_error_instance):
    """Test that to_dict returns the correct dictionary"""
    result = validation_error_instance.to_dict()
    assert result == {
        'field': 'content',
        'reason': 'Invalid content',
        'timestamp': '2021-01-01T00:00:00',
    }


def test_validate_review_request_missing_content_logs_and_returns_error():
    """Test validate_review_request when content is missing"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_review_request({'language': 'python'})
        assert len(errors) == 1
        assert errors[0].field == 'content'
        assert 'required' in errors[0].reason.lower()
        mock_log.assert_called_once()
        called_errors = mock_log.call_args[0][0]
        assert isinstance(called_errors, list)
        assert len(called_errors) == 1


def test_validate_review_request_content_exceeds_max_size():
    """Test validate_review_request when content exceeds MAX_CONTENT_SIZE"""
    oversized = 'a' * (MAX_CONTENT_SIZE + 1)
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_review_request({'content': oversized})
        assert len(errors) == 1
        assert errors[0].field == 'content'
        assert str(MAX_CONTENT_SIZE) in errors[0].reason
        mock_log.assert_called_once()


def test_validate_review_request_content_contains_null_bytes_and_invalid_language():
    """Test validate_review_request with null bytes and invalid language"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_review_request({'content': 'abc\x00def', 'language': 'kotlin'})
        assert len(errors) == 2
        fields = {e.field for e in errors}
        assert 'content' in fields
        assert 'language' in fields
        reasons = [e.reason for e in errors]
        assert any('null bytes' in r for r in reasons)
        assert any('Language must be one of' in r for r in reasons)
        mock_log.assert_called_once()


def test_validate_review_request_valid_input():
    """Test validate_review_request with valid input"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_review_request({'content': 'print("hello")', 'language': 'python'})
        assert errors == []
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == []


def test_validate_statistics_request_missing_files():
    """Test validate_statistics_request when files key is missing"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_statistics_request({})
        assert len(errors) == 1
        assert errors[0].field == 'files'
        assert 'required' in errors[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_files_not_list():
    """Test validate_statistics_request when files is not a list"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_statistics_request({'files': 'not-a-list'})
        assert len(errors) == 1
        assert errors[0].field == 'files'
        assert 'array' in errors[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_files_empty():
    """Test validate_statistics_request when files list is empty"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_statistics_request({'files': []})
        assert len(errors) == 1
        assert errors[0].field == 'files'
        assert 'cannot be empty' in errors[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_files_too_many():
    """Test validate_statistics_request when files list exceeds 1000 entries"""
    many_files = [f'file_{i}.txt' for i in range(1001)]
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_statistics_request({'files': many_files})
        assert len(errors) == 1
        assert errors[0].field == 'files'
        assert 'cannot exceed 1000' in errors[0].reason.lower()
        mock_log.assert_called_once()


def test_validate_statistics_request_valid():
    """Test validate_statistics_request with valid input"""
    with patch('src.request_validator.log_validation_errors') as mock_log:
        errors = validate_statistics_request({'files': ['a.py', 'b.py']})
        assert errors == []
        mock_log.assert_called_once()
        assert mock_log.call_args[0][0] == []


def test_sanitize_input_none_and_non_string():
    """Test sanitize_input returns None for None and str() for non-string"""
    assert sanitize_input(None) is None
    assert sanitize_input(123) == '123'


def test_sanitize_input_removes_control_chars_and_keeps_newlines_tabs():
    """Test sanitize_input removes control characters but preserves LF, CR, TAB"""
    raw = "A\x00B\x01C\x0bD\x0cE\x1fF\x7fG\nH\rI\tJ"
    sanitized = sanitize_input(raw)
    assert '\x00' not in sanitized
    assert '\x01' not in sanitized
    assert '\x0b' not in sanitized
    assert '\x0c' not in sanitized
    assert '\x1f' not in sanitized
    assert '\x7f' not in sanitized
    assert '\n' in sanitized
    assert '\r' in sanitized
    assert '\t' in sanitized
    # Ensure printable chars remain in order
    assert sanitized.replace('\n', '').replace('\r', '').replace('\t', '').startswith('ABCDEFGIJ')


def test_sanitize_input_exception_when_str_fails():
    """Test sanitize_input raises when __str__ of non-string input raises"""
    class BadStr:
        def __str__(self):
            raise ValueError("cannot cast to str")

    with pytest.raises(ValueError):
        sanitize_input(BadStr())


def test_sanitize_request_data_sanitizes_string_fields_only():
    """Test sanitize_request_data sanitizes only string fields content/language/path"""
    data = {
        'content': "A\x00B\x07C\nD",
        'language': "py\x00thon",
        'path': "foo/\x00bar",
        'other': 123
    }
    sanitized = sanitize_request_data(data)
    assert sanitized['content'] == "ABC\nD"
    assert sanitized['language'] == "python"
    assert sanitized['path'] == "foobar"
    # Non-string field remains unchanged
    assert sanitized['other'] == 123


def test_contains_null_bytes():
    """Test contains_null_bytes correctly detects null byte presence"""
    assert contains_null_bytes('abc\x00def') is True
    assert contains_null_bytes('abcdef') is False


def test_contains_path_traversal():
    """Test contains_path_traversal detects '..' and '~/' patterns"""
    assert contains_path_traversal('../etc/passwd') is True
    assert contains_path_traversal('~/secrets') is True
    assert contains_path_traversal('safe/path/file.txt') is False


def test_log_validation_errors_appends_and_trims():
    """Test log_validation_errors appends errors and keep_recent_errors trims to 100"""
    # Create 105 errors
    errors = [ValidationError('field', f'reason_{i}') for i in range(105)]
    log_validation_errors(errors)
    stored = get_validation_errors()
    assert len(stored) == 100
    # Confirm that it kept the most recent 100 (i.e., reasons 5..104)
    assert stored[0]['reason'] == 'reason_5'
    assert stored[-1]['reason'] == 'reason_104'


def test_log_validation_errors_calls_keep_recent_errors_when_errors_present():
    """Test log_validation_errors calls keep_recent_errors only when errors exist"""
    with patch('src.request_validator.keep_recent_errors') as mock_keep:
        log_validation_errors([ValidationError('a', 'b')])
        mock_keep.assert_called_once()

    clear_validation_errors()
    with patch('src.request_validator.keep_recent_errors') as mock_keep:
        log_validation_errors([])
        mock_keep.assert_not_called()


def test_get_validation_errors_returns_copy():
    """Test get_validation_errors returns a copy that doesn't affect the original store"""
    log_validation_errors([ValidationError('x', 'y')])
    first = get_validation_errors()
    assert len(first) == 1
    # Modify the returned list and verify the internal store is unaffected
    first.append({'field': 'extra', 'reason': 'hack', 'timestamp': 't'})
    second = get_validation_errors()
    assert len(second) == 1  # unchanged internal state


def test_keep_recent_errors_trims_global_store():
    """Test keep_recent_errors trims the global validation_errors list when exceeding 100"""
    # Populate more than 100 entries via multiple calls
    for i in range(3):
        log_validation_errors([ValidationError('f', f'r{i}_{j}') for j in range(50)])
    # Now we should have 150 entries trimmed to 100
    stored = get_validation_errors()
    assert len(stored) == 100
    # Ensure the earliest 50 entries were trimmed
    reasons = [e['reason'] for e in stored]
    assert any(r.startswith('r1_') for r in reasons)
    assert any(r.startswith('r2_') for r in reasons)
    assert not any(r.startswith('r0_') for r in reasons)