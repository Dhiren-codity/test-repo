import pytest
from unittest.mock import Mock, patch

from src.request_validator import ValidationError


FIXED_ISO = "2024-01-02T03:04:05.000001"


@pytest.fixture
def fixed_datetime():
    """Patch datetime.now to return a fixed timestamp."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = FIXED_ISO
        mock_datetime.now.return_value = mock_now
        yield mock_datetime


@pytest.fixture
def validation_error_instance(fixed_datetime):
    """Create a ValidationError instance with deterministic timestamp."""
    return ValidationError(field="content", reason="Invalid content")


def test_ValidationError___init___sets_fields_and_timestamp(fixed_datetime):
    """Test that ValidationError initializes fields and timestamp correctly."""
    err = ValidationError(field="test_field", reason="test_reason")
    assert err.field == "test_field"
    assert err.reason == "test_reason"
    assert err.timestamp == FIXED_ISO
    fixed_datetime.now.assert_called_once_with()


def test_ValidationError_to_dict_returns_expected_structure(validation_error_instance):
    """Test to_dict returns a dict with correct keys and values."""
    result = validation_error_instance.to_dict()
    assert isinstance(result, dict)
    assert result["field"] == "content"
    assert result["reason"] == "Invalid content"
    assert result["timestamp"] == FIXED_ISO


def test_ValidationError___init___handles_unicode_and_whitespace(fixed_datetime):
    """Test that ValidationError accepts unicode and whitespace in fields."""
    field = "naïve\nfield"
    reason = "résumé\treason"
    err = ValidationError(field=field, reason=reason)
    assert err.field == field
    assert err.reason == reason
    assert err.timestamp == FIXED_ISO


def test_ValidationError___init___accepts_empty_strings(fixed_datetime):
    """Test that ValidationError accepts empty strings for field and reason."""
    err = ValidationError(field="", reason="")
    assert err.field == ""
    assert err.reason == ""
    assert err.timestamp == FIXED_ISO


def test_ValidationError_to_dict_with_none_values(fixed_datetime):
    """Test to_dict when field and reason are None."""
    err = ValidationError(field=None, reason=None)  # type: ignore
    result = err.to_dict()
    assert result["field"] is None
    assert result["reason"] is None
    assert result["timestamp"] == FIXED_ISO


def test_ValidationError___init___raises_when_datetime_now_fails():
    """Test that __init__ raises if datetime.now fails."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.side_effect = RuntimeError("Clock failure")
        with pytest.raises(RuntimeError):
            ValidationError(field="f", reason="r")


def test_ValidationError_to_dict_is_idempotent(validation_error_instance):
    """Test that consecutive to_dict calls return consistent results."""
    first = validation_error_instance.to_dict()
    second = validation_error_instance.to_dict()
    assert first == second
    assert first["timestamp"] == FIXED_ISO
    assert second["timestamp"] == FIXED_ISO


def test_ValidationError_attributes_mutation_reflected_in_to_dict(validation_error_instance):
    """Test that changes to attributes after initialization are reflected in to_dict."""
    validation_error_instance.field = "new_field"
    validation_error_instance.reason = "new_reason"
    result = validation_error_instance.to_dict()
    assert result["field"] == "new_field"
    assert result["reason"] == "new_reason"