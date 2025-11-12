import pytest
from unittest.mock import patch

from src.request_validator import ValidationError


@pytest.fixture
def error_instance_fixed_time():
    """Create ValidationError with a fixed timestamp using mock."""
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.return_value.isoformat.return_value = "2024-01-02T03:04:05"
        err = ValidationError(field="content", reason="missing")
    return err


def test_ValidationError_init_sets_fields_and_timestamp():
    """Test that __init__ sets field, reason, and a deterministic timestamp when mocked."""
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.return_value.isoformat.return_value = "2001-02-03T04:05:06"
        err = ValidationError(field="language", reason="invalid")
        assert err.field == "language"
        assert err.reason == "invalid"
        assert err.timestamp == "2001-02-03T04:05:06"


def test_ValidationError_to_dict_returns_expected_payload(error_instance_fixed_time):
    """Test to_dict returns a dict with correct keys and values."""
    payload = error_instance_fixed_time.to_dict()
    assert payload == {
        "field": "content",
        "reason": "missing",
        "timestamp": "2024-01-02T03:04:05",
    }


def test_ValidationError_to_dict_returns_new_dict_each_time(error_instance_fixed_time):
    """Test to_dict returns a new dictionary object on each call."""
    d1 = error_instance_fixed_time.to_dict()
    d2 = error_instance_fixed_time.to_dict()
    assert d1 is not d2
    assert d1 == d2


def test_ValidationError_timestamp_is_isoformat_compliant():
    """Test that timestamp is ISO-formatted by checking that fromisoformat can parse it."""
    err = ValidationError(field="files", reason="required")
    # Validate that datetime.fromisoformat can parse the timestamp
    from datetime import datetime as real_datetime

    parsed = real_datetime.fromisoformat(err.timestamp)
    assert isinstance(parsed, real_datetime)


def test_ValidationError_init_raises_when_datetime_now_throws():
    """Test that __init__ raises the underlying exception if datetime.now() fails."""
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.side_effect = RuntimeError("clock failure")
        with pytest.raises(RuntimeError, match="clock failure"):
            ValidationError(field="path", reason="bad timestamp")


@pytest.mark.parametrize(
    "field,reason",
    [
        ("", ""),                 # empty strings
        ("παράδειγμα", "λόγος"),  # unicode strings
        ("field", "理由"),         # mixed ASCII and non-ASCII
    ],
)
def test_ValidationError_handles_various_field_and_reason(field, reason):
    """Test that the class accepts empty and unicode values for field and reason."""
    err = ValidationError(field=field, reason=reason)
    assert err.field == field
    assert err.reason == reason
    # Ensure to_dict includes these values
    payload = err.to_dict()
    assert payload["field"] == field
    assert payload["reason"] == reason
    assert "timestamp" in payload and isinstance(payload["timestamp"], str)