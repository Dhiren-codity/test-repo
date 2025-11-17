import pytest
from unittest.mock import Mock, patch
from src.request_validator import ValidationError


@pytest.fixture
def fixed_timestamp():
    """Provide a fixed ISO timestamp string for deterministic testing."""
    return "2025-01-02T03:04:05"


@pytest.fixture
def validation_error_instance(fixed_timestamp):
    """Create a ValidationError instance with a mocked datetime.now().isoformat()."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now
        instance = ValidationError(field="content", reason="Invalid content")
    return instance


def test_ValidationError_init_sets_attributes(fixed_timestamp):
    """Test that __init__ sets field, reason, and timestamp using datetime.now().isoformat()."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now

        err = ValidationError(field="content", reason="Invalid content")

        assert err.field == "content"
        assert err.reason == "Invalid content"
        assert err.timestamp == fixed_timestamp
        mock_datetime.now.assert_called_once()
        mock_now.isoformat.assert_called_once()


def test_ValidationError_to_dict_returns_expected(validation_error_instance, fixed_timestamp):
    """Test that to_dict returns a dictionary with correct keys and values."""
    result = validation_error_instance.to_dict()
    assert isinstance(result, dict)
    assert result["field"] == "content"
    assert result["reason"] == "Invalid content"
    assert result["timestamp"] == fixed_timestamp


def test_ValidationError_init_with_non_string_inputs(fixed_timestamp):
    """Test __init__ handles non-string inputs for field and reason without raising exceptions."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now

        err = ValidationError(field=123, reason=None)
        assert err.field == 123
        assert err.reason is None
        assert err.timestamp == fixed_timestamp

        d = err.to_dict()
        assert d["field"] == 123
        assert d["reason"] is None
        assert d["timestamp"] == fixed_timestamp


def test_ValidationError_init_calls_isoformat_once(fixed_timestamp):
    """Test __init__ ensures isoformat() is called exactly once on datetime.now() result."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.return_value = fixed_timestamp
        mock_datetime.now.return_value = mock_now

        _ = ValidationError(field="f", reason="r")
        mock_datetime.now.assert_called_once()
        mock_now.isoformat.assert_called_once()


def test_ValidationError_init_raises_when_isoformat_fails():
    """Test __init__ raises an exception if isoformat() fails."""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_now = Mock()
        mock_now.isoformat.side_effect = RuntimeError("isoformat failed")
        mock_datetime.now.return_value = mock_now

        with pytest.raises(RuntimeError, match="isoformat failed"):
            _ = ValidationError(field="f", reason="r")