import re
from datetime import datetime
from unittest.mock import patch

import pytest

from src.request_validator import ValidationError


@pytest.fixture
def fixed_dt():
    """Provide a fixed datetime for deterministic timestamps."""
    return datetime(2023, 5, 4, 10, 20, 30)


@pytest.fixture
def validation_error_instance(fixed_dt):
    """Create a ValidationError instance with a patched datetime.now()."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.return_value = fixed_dt
        err = ValidationError('content', 'Content is required')
    return err


def test_validationerror_init_sets_fields_and_timestamp(validation_error_instance, fixed_dt):
    """Test that ValidationError initializes fields and timestamp correctly."""
    assert validation_error_instance.field == 'content'
    assert validation_error_instance.reason == 'Content is required'
    assert validation_error_instance.timestamp == fixed_dt.isoformat()


def test_validationerror_to_dict_contains_expected_fields(validation_error_instance, fixed_dt):
    """Test that to_dict returns the expected dictionary structure."""
    result = validation_error_instance.to_dict()
    assert isinstance(result, dict)
    assert result['field'] == 'content'
    assert result['reason'] == 'Content is required'
    assert result['timestamp'] == fixed_dt.isoformat()


def test_validationerror_init_with_non_string_types(fixed_dt):
    """Test that ValidationError can handle non-string field and reason inputs."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.return_value = fixed_dt
        err = ValidationError(123, {'message': 'oops'})
    assert err.field == 123
    assert err.reason == {'message': 'oops'}
    d = err.to_dict()
    assert d['field'] == 123
    assert d['reason'] == {'message': 'oops'}
    assert d['timestamp'] == fixed_dt.isoformat()


def test_validationerror_init_with_empty_strings(fixed_dt):
    """Test that ValidationError handles empty string inputs gracefully."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.return_value = fixed_dt
        err = ValidationError('', '')
    assert err.field == ''
    assert err.reason == ''
    assert err.timestamp == fixed_dt.isoformat()


def test_validationerror_timestamp_format_iso8601(validation_error_instance):
    """Test that timestamp is in ISO 8601 format."""
    ts = validation_error_instance.timestamp
    # ISO 8601 basic check: YYYY-MM-DDTHH:MM:SS
    assert re.match(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', ts) is not None


def test_validationerror_to_dict_multiple_calls_consistent(validation_error_instance):
    """Test that calling to_dict multiple times returns consistent data."""
    first = validation_error_instance.to_dict()
    second = validation_error_instance.to_dict()
    assert first == second
    assert first['timestamp'] == validation_error_instance.timestamp


def test_validationerror_init_raises_when_datetime_now_fails():
    """Test that ValidationError initialization surfaces errors from datetime.now()."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.side_effect = RuntimeError("datetime failure")
        with pytest.raises(RuntimeError):
            ValidationError('field', 'reason')