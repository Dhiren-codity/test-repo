import pytest
from unittest.mock import patch
from datetime import datetime

from src.request_validator import ValidationError


@pytest.fixture
def fixed_timestamp():
    """Provide a fixed datetime for deterministic timestamp testing"""
    return datetime(2023, 5, 1, 14, 30, 0)


@pytest.fixture
def validation_error_instance(fixed_timestamp):
    """Create a ValidationError instance with a mocked datetime.now"""
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_timestamp
        instance = ValidationError(field="content", reason="Invalid content")
    return instance


def test_validationerror_init_sets_fields_and_timestamp(fixed_timestamp):
    """Test that ValidationError initializes with correct field, reason, and ISO timestamp"""
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.return_value = fixed_timestamp
        err = ValidationError(field="language", reason="Unsupported language")

    assert err.field == "language"
    assert err.reason == "Unsupported language"
    assert err.timestamp == fixed_timestamp.isoformat()


def test_validationerror_to_dict_returns_expected_keys_values(validation_error_instance, fixed_timestamp):
    """Test that to_dict returns the correct dictionary representation"""
    d = validation_error_instance.to_dict()
    assert set(d.keys()) == {"field", "reason", "timestamp"}
    assert d["field"] == "content"
    assert d["reason"] == "Invalid content"
    assert d["timestamp"] == fixed_timestamp.isoformat()


def test_validationerror_to_dict_isolation_from_instance(validation_error_instance):
    """Test that modifying the dict from to_dict does not affect the original instance"""
    d = validation_error_instance.to_dict()
    d["field"] = "modified"
    d["reason"] = "changed"
    d["timestamp"] = "2000-01-01T00:00:00"

    assert validation_error_instance.field == "content"
    assert validation_error_instance.reason == "Invalid content"
    # Ensure timestamp on instance has not been altered by dict mutation
    assert validation_error_instance.timestamp != "2000-01-01T00:00:00"


def test_validationerror_init_allows_empty_strings():
    """Test that ValidationError accepts empty string values without error"""
    err = ValidationError(field="", reason="")
    assert err.field == ""
    assert err.reason == ""
    # Ensure timestamp is a non-empty ISO string
    assert isinstance(err.timestamp, str)
    assert "T" in err.timestamp


def test_validationerror_init_with_unicode_and_control_chars():
    """Test that ValidationError supports unicode and control characters in fields"""
    unicode_field = "フィールド"
    unicode_reason = "理由\n詳細\t追加"
    err = ValidationError(field=unicode_field, reason=unicode_reason)
    d = err.to_dict()
    assert d["field"] == unicode_field
    assert d["reason"] == unicode_reason


def test_validationerror_init_raises_if_datetime_now_fails():
    """Test that ValidationError initialization propagates exceptions from datetime.now"""
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.side_effect = RuntimeError("datetime failure")
        with pytest.raises(RuntimeError, match="datetime failure"):
            ValidationError(field="content", reason="anything")


def test_validationerror_timestamp_is_immutable_after_creation():
    """Test that timestamp is fixed at creation time and does not change afterward"""
    first = datetime(2022, 1, 1, 10, 0, 0)
    second = datetime(2022, 1, 1, 11, 0, 0)

    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.return_value = first
        err = ValidationError(field="content", reason="initial")
    # Change mocked time and ensure err.timestamp remains from creation
    with patch('src.request_validator.datetime') as mock_dt:
        mock_dt.now.return_value = second
        # creating a new one should have a different timestamp, but the old one remains the same
        err2 = ValidationError(field="content", reason="second")

    assert err.timestamp == first.isoformat()
    assert err2.timestamp == second.isoformat()
    assert err.timestamp != err2.timestamp