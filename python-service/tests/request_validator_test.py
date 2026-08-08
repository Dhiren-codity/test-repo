import pytest
from unittest.mock import Mock, patch
from src.request_validator import ValidationError


@pytest.fixture
def fixed_timestamp():
    """Provide a fixed timestamp for deterministic testing."""
    return "2030-12-31T23:59:59"


@pytest.fixture
def patched_datetime(fixed_timestamp):
    """Patch the datetime.now().isoformat() call to return a fixed timestamp."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now
        yield mock_datetime


@pytest.fixture
def validation_error_instance(patched_datetime):
    """Create a ValidationError instance with a patched datetime."""
    return ValidationError(field="content", reason="Invalid content")


def test_validationerror_init_sets_properties(patched_datetime, fixed_timestamp):
    """Test that ValidationError initialization sets field, reason, and timestamp correctly."""
    err = ValidationError(field="content", reason="Bad request")
    assert err.field == "content"
    assert err.reason == "Bad request"
    assert err.timestamp == fixed_timestamp
    patched_datetime.now.assert_called_once()


def test_validationerror_to_dict_returns_expected_structure(validation_error_instance, fixed_timestamp):
    """Test that to_dict returns the expected dictionary structure."""
    result = validation_error_instance.to_dict()
    assert isinstance(result, dict)
    assert result["field"] == "content"
    assert result["reason"] == "Invalid content"
    assert result["timestamp"] == fixed_timestamp
    assert set(result.keys()) == {"field", "reason", "timestamp"}


def test_validationerror_init_allows_empty_strings(patched_datetime, fixed_timestamp):
    """Test that ValidationError allows empty strings for field and reason."""
    err = ValidationError(field="", reason="")
    assert err.field == ""
    assert err.reason == ""
    assert err.timestamp == fixed_timestamp


def test_validationerror_to_dict_handles_unicode(patched_datetime):
    """Test that to_dict handles unicode characters properly."""
    err = ValidationError(field="字段", reason="原因: 无效字符")
    result = err.to_dict()
    assert result["field"] == "字段"
    assert result["reason"] == "原因: 无效字符"
    assert "timestamp" in result
    assert isinstance(result["timestamp"], str)


def test_validationerror_init_raises_when_datetime_now_fails():
    """Test that ValidationError initialization propagates exceptions from datetime.now()."""
    with patch('src.request_validator.datetime') as mock_datetime:
        mock_datetime.now.side_effect = RuntimeError("datetime failure")
        with pytest.raises(RuntimeError, match="datetime failure"):
            ValidationError(field="content", reason="Error")