import re
import pytest
from unittest.mock import patch
from src.request_validator import ValidationError


@pytest.fixture
def validation_error_instance():
    """Create a ValidationError instance for testing"""
    return ValidationError(field="content", reason="Content is required and cannot be empty")


def test_validationerror_init_sets_fields_and_timestamp(validation_error_instance):
    """Test that __init__ sets field, reason, and a valid ISO timestamp"""
    assert validation_error_instance.field == "content"
    assert validation_error_instance.reason == "Content is required and cannot be empty"
    # ISO format: YYYY-MM-DDTHH:MM:SS(.ffffff optional)
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?$"
    assert isinstance(validation_error_instance.timestamp, str)
    assert re.match(iso_pattern, validation_error_instance.timestamp)


def test_validationerror_to_dict_returns_expected_keys_with_mocked_timestamp():
    """Test to_dict returns correct dict structure with mocked timestamp"""
    fixed_timestamp = "2025-01-01T00:00:00"
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_datetime.now.return_value.isoformat.return_value = fixed_timestamp
        err = ValidationError(field="language", reason="Invalid language")
        result = err.to_dict()
    assert result == {
        "field": "language",
        "reason": "Invalid language",
        "timestamp": fixed_timestamp,
    }


@pytest.mark.parametrize(
    "field,reason",
    [
        (123, {"error": "bad"}),
        (None, None),
        ("Δείγμα", "Причина с ошибкой"),
    ],
)
def test_validationerror_init_allows_non_string_types(field, reason):
    """Test __init__ accepts non-string types and preserves them in to_dict"""
    err = ValidationError(field=field, reason=reason)
    result = err.to_dict()
    assert result["field"] == field
    assert result["reason"] == reason
    assert isinstance(result["timestamp"], str)


def test_validationerror_to_dict_is_immutable_view(validation_error_instance):
    """Test that modifying the dict returned by to_dict does not change the instance"""
    data = validation_error_instance.to_dict()
    data["field"] = "modified"
    data["reason"] = "changed"
    # Original instance should remain unchanged
    assert validation_error_instance.field == "content"
    assert validation_error_instance.reason == "Content is required and cannot be empty"


def test_validationerror_timestamp_uses_isoformat_precisely():
    """Test that timestamp uses isoformat from datetime.now"""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_dt = mock_datetime.now.return_value
        mock_dt.isoformat.return_value = "2024-12-31T23:59:59.123456"
        err = ValidationError(field="path", reason="Invalid path")
        assert err.timestamp == "2024-12-31T23:59:59.123456"


def test_validationerror_init_raises_if_datetime_now_fails():
    """Test that __init__ propagates exceptions from datetime.now"""
    with patch("src.request_validator.datetime") as mock_datetime:
        mock_datetime.now.side_effect = RuntimeError("Clock failure")
        with pytest.raises(RuntimeError, match="Clock failure"):
            ValidationError(field="content", reason="Issue with clock")