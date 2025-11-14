import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from src.request_validator import ValidationError


@pytest.fixture
def fixed_timestamp():
    """Provide a fixed ISO timestamp string for deterministic tests."""
    return "2025-01-02T03:04:05.123456"


@pytest.fixture
def validation_error_instance(fixed_timestamp):
    """Create ValidationError instance with mocked datetime.now().isoformat()."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now
        ve = ValidationError(field="content", reason="invalid")
    return ve, fixed_timestamp


def test_ValidationError___init___sets_fields_and_iso_timestamp():
    """Test that __init__ sets field, reason, and a valid ISO timestamp."""
    ve = ValidationError(field="language", reason="not allowed")
    assert ve.field == "language"
    assert ve.reason == "not allowed"
    # Validate that timestamp is ISO-formatted
    parsed = datetime.fromisoformat(ve.timestamp)
    assert isinstance(parsed, datetime)


def test_ValidationError_to_dict_returns_expected_keys_and_values_with_mocked_timestamp(validation_error_instance):
    """Test to_dict returns expected structure and values, including mocked timestamp."""
    ve, fixed_ts = validation_error_instance
    result = ve.to_dict()
    assert set(result.keys()) == {"field", "reason", "timestamp"}
    assert result["field"] == "content"
    assert result["reason"] == "invalid"
    assert result["timestamp"] == fixed_ts


def test_ValidationError___init___handles_empty_strings():
    """Test __init__ handles empty string values for field and reason."""
    ve = ValidationError(field="", reason="")
    d = ve.to_dict()
    assert d["field"] == ""
    assert d["reason"] == ""
    # Timestamp should still be a valid ISO format string
    assert isinstance(datetime.fromisoformat(d["timestamp"]), datetime)


def test_ValidationError___init___accepts_non_string_values():
    """Test __init__ accepts non-string values and preserves them in to_dict."""
    ve = ValidationError(field=123, reason=456)
    d = ve.to_dict()
    assert d["field"] == 123
    assert d["reason"] == 456


def test_ValidationError___init___raises_when_datetime_now_fails():
    """Test that __init__ propagates exceptions when datetime.now() fails."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.side_effect = RuntimeError("clock failure")
        with pytest.raises(RuntimeError) as excinfo:
            ValidationError(field="any", reason="reason")
        assert "clock failure" in str(excinfo.value)