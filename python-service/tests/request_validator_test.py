import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.request_validator import ValidationError


@pytest.fixture
def fixed_timestamp():
    """Provide a fixed ISO timestamp string for deterministic testing"""
    return "2023-01-01T00:00:00"


@pytest.fixture
def mock_datetime_with_fixed_timestamp(fixed_timestamp):
    """Mock src.request_validator.datetime.now().isoformat() to return a fixed timestamp"""
    mock_dt = Mock()
    mock_now = Mock()
    mock_now.isoformat.return_value = fixed_timestamp
    mock_dt.now.return_value = mock_now
    with patch('src.request_validator.datetime', mock_dt):
        yield mock_dt


@pytest.fixture
def validation_error_instance(mock_datetime_with_fixed_timestamp, fixed_timestamp):
    """Create a ValidationError instance with a fixed timestamp"""
    ve = ValidationError(field="content", reason="invalid data")
    assert ve.timestamp == fixed_timestamp  # sanity check fixture works
    return ve


def test_validationerror_init_sets_attributes_with_valid_data(validation_error_instance, fixed_timestamp):
    """Test that __init__ sets the field, reason, and timestamp correctly with valid input"""
    ve = validation_error_instance
    assert ve.field == "content"
    assert ve.reason == "invalid data"
    assert ve.timestamp == fixed_timestamp
    assert isinstance(ve.timestamp, str)


def test_validationerror_init_uses_current_time_mocked(mock_datetime_with_fixed_timestamp, fixed_timestamp):
    """Test that __init__ uses datetime.now().isoformat() by verifying mocked timestamp is used"""
    ve = ValidationError(field="path", reason="too long")
    assert ve.timestamp == fixed_timestamp
    mock_datetime_with_fixed_timestamp.now.assert_called_once()


def test_validationerror_to_dict_returns_expected_dict(validation_error_instance, fixed_timestamp):
    """Test that to_dict returns a dictionary with the correct structure and values"""
    ve = validation_error_instance
    result = ve.to_dict()
    assert isinstance(result, dict)
    assert result == {
        "field": "content",
        "reason": "invalid data",
        "timestamp": fixed_timestamp,
    }


def test_validationerror_init_handles_non_string_fields(mock_datetime_with_fixed_timestamp, fixed_timestamp):
    """Test that __init__ accepts non-string values for field and reason without error"""
    ve = ValidationError(field=123, reason=None)
    assert ve.field == 123
    assert ve.reason is None
    assert ve.timestamp == fixed_timestamp
    assert ve.to_dict()["field"] == 123
    assert ve.to_dict()["reason"] is None


def test_validationerror_timestamp_is_isoformat():
    """Test that timestamp is a valid ISO formatted string when not mocked"""
    ve = ValidationError(field="x", reason="y")
    # Should not raise if the timestamp is valid ISO format
    parsed = datetime.fromisoformat(ve.timestamp)
    assert isinstance(parsed, datetime)


def test_validationerror_init_raises_when_datetime_now_fails(monkeypatch):
    """Test that __init__ propagates exceptions if datetime.now() fails"""
    mock_dt = Mock()
    mock_dt.now.side_effect = RuntimeError("time source failure")
    monkeypatch.setattr('src.request_validator.datetime', mock_dt)

    with pytest.raises(RuntimeError, match="time source failure"):
        ValidationError(field="f", reason="r")