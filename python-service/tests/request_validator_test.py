import re
import pytest
from unittest.mock import Mock, patch

from src.request_validator import ValidationError


@pytest.fixture
def fixed_timestamp():
    """Provide a fixed ISO timestamp string for deterministic tests."""
    return "2023-04-05T06:07:08.123456"


@pytest.fixture
def patch_datetime(fixed_timestamp):
    """Patch datetime.now().isoformat() used in ValidationError to return a fixed timestamp."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now
        yield mock_datetime


@pytest.fixture
def error_instance(patch_datetime):
    """Create a ValidationError instance with patched timestamp."""
    return ValidationError(field="content", reason="is invalid")


def test_validationerror_init_sets_attributes(error_instance, fixed_timestamp):
    """Test that ValidationError initializes field, reason, and timestamp correctly."""
    assert error_instance.field == "content"
    assert error_instance.reason == "is invalid"
    assert error_instance.timestamp == fixed_timestamp


def test_validationerror_to_dict_includes_all_fields(error_instance, fixed_timestamp):
    """Test that to_dict returns the expected dictionary structure with all fields."""
    data = error_instance.to_dict()
    assert isinstance(data, dict)
    assert data["field"] == "content"
    assert data["reason"] == "is invalid"
    assert data["timestamp"] == fixed_timestamp


def test_validationerror_init_accepts_empty_strings():
    """Test that ValidationError accepts empty strings and sets a valid ISO timestamp."""
    err = ValidationError(field="", reason="")
    assert err.field == ""
    assert err.reason == ""
    assert isinstance(err.timestamp, str)
    # Basic ISO-8601 format check
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", err.timestamp)


def test_validationerror_non_string_values_preserved():
    """Test that non-string field and reason values are preserved in the instance and to_dict."""
    field_value = 123
    reason_value = {"detail": "oops"}
    err = ValidationError(field=field_value, reason=reason_value)
    data = err.to_dict()
    assert err.field == field_value
    assert err.reason == reason_value
    assert data["field"] == field_value
    assert data["reason"] == reason_value
    assert isinstance(data["timestamp"], str)


def test_validationerror_timestamp_unique_per_instance_with_mock():
    """Test timestamps differ for separate instances when datetime.now returns different values."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now_1 = Mock()
        mock_now_1.isoformat.return_value = "2025-01-01T00:00:00"
        mock_now_2 = Mock()
        mock_now_2.isoformat.return_value = "2025-01-01T00:00:01"
        mock_datetime.now.side_effect = [mock_now_1, mock_now_2]

        err1 = ValidationError("f1", "r1")
        err2 = ValidationError("f2", "r2")

        assert err1.timestamp == "2025-01-01T00:00:00"
        assert err2.timestamp == "2025-01-01T00:00:01"
        assert err1.timestamp != err2.timestamp


def test_validationerror_isoformat_called_once_during_initialization(fixed_timestamp):
    """Test that isoformat is called exactly once during ValidationError initialization."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now

        err = ValidationError("field", "reason")
        assert err.timestamp == fixed_timestamp
        assert mock_now.isoformat.call_count == 1


def test_validationerror_init_raises_if_isoformat_fails():
    """Test that ValidationError initialization propagates exceptions from isoformat."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.side_effect = RuntimeError("isoformat failed")
        mock_datetime.now.return_value = mock_now

        with pytest.raises(RuntimeError, match="isoformat failed"):
            ValidationError("field", "reason")