import re
from datetime import datetime
import pytest
from unittest.mock import patch

from src.request_validator import ValidationError


@pytest.fixture
def fixed_now():
    """Provide a fixed datetime for deterministic timestamp testing."""
    return datetime(2021, 5, 17, 10, 30, 45, 123456)


@pytest.fixture
def validation_error_instance(fixed_now):
    """Create a ValidationError instance with a fixed timestamp for testing."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        return ValidationError(field="content", reason="invalid")


def test_validationerror_init_with_valid_data_sets_attributes_and_timestamp(fixed_now):
    """Test that __init__ sets field, reason, and timestamp (ISO) correctly."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        err = ValidationError(field="content", reason="bad content")
        assert err.field == "content"
        assert err.reason == "bad content"
        assert err.timestamp == fixed_now.isoformat()


def test_validationerror_to_dict_returns_expected_dict(fixed_now):
    """Test to_dict returns the correct dictionary representation."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.return_value = fixed_now
        err = ValidationError(field="language", reason="unsupported")
        data = err.to_dict()
        assert isinstance(data, dict)
        assert data == {
            "field": "language",
            "reason": "unsupported",
            "timestamp": fixed_now.isoformat(),
        }


def test_validationerror_init_allows_empty_strings_and_generates_iso_timestamp():
    """Test __init__ accepts empty strings and timestamp is in ISO 8601 format."""
    err = ValidationError(field="", reason="")
    assert err.field == ""
    assert err.reason == ""
    assert isinstance(err.timestamp, str)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$", err.timestamp)


def test_validationerror_init_raises_when_datetime_now_fails():
    """Test __init__ propagates exceptions if datetime.now() fails."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.side_effect = RuntimeError("clock failure")
        with pytest.raises(RuntimeError, match="clock failure"):
            ValidationError(field="any", reason="any")


def test_validationerror_to_dict_reflects_current_attribute_values(validation_error_instance, fixed_now):
    """Test to_dict reflects current attribute values after mutation."""
    # Mutate attributes after initialization
    validation_error_instance.field = "path"
    validation_error_instance.reason = "too long"
    result = validation_error_instance.to_dict()
    assert result["field"] == "path"
    assert result["reason"] == "too long"
    # Timestamp should remain the original fixed value
    assert result["timestamp"] == fixed_now.isoformat()