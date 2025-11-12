import pytest
from datetime import datetime
from unittest.mock import patch

from src.request_validator import ValidationError


@pytest.fixture
def fixed_datetime():
    """Provide a fixed datetime for deterministic timestamp testing."""
    return datetime(2023, 5, 6, 7, 8, 9, 123456)


@pytest.fixture
def error_instance(fixed_datetime):
    """Create a ValidationError instance with a patched datetime.now."""
    with patch("src.request_validator.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_datetime
        err = ValidationError(field="content", reason="Invalid content")
    return err


def test_validationerror_init_sets_fields_and_timestamp(error_instance, fixed_datetime):
    """Test that ValidationError initializes fields and timestamp correctly."""
    assert error_instance.field == "content"
    assert error_instance.reason == "Invalid content"
    assert error_instance.timestamp == fixed_datetime.isoformat()


def test_validationerror_to_dict_returns_expected_dict(fixed_datetime):
    """Test that to_dict returns the correct dictionary representation."""
    with patch("src.request_validator.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_datetime
        err = ValidationError(field="language", reason="Unsupported language")
    as_dict = err.to_dict()
    assert as_dict == {
        "field": "language",
        "reason": "Unsupported language",
        "timestamp": fixed_datetime.isoformat(),
    }


def test_validationerror_timestamp_is_isoformat_parseable():
    """Test that the timestamp is an ISO format string that can be parsed."""
    err = ValidationError(field="path", reason="Too long")
    # Should not raise
    parsed = datetime.fromisoformat(err.timestamp)
    assert isinstance(parsed, datetime)


def test_validationerror_multiple_instances_unique_timestamps():
    """Test that multiple instances get unique timestamps when datetime.now changes."""
    dt1 = datetime(2024, 1, 2, 3, 4, 5, 111111)
    dt2 = datetime(2024, 1, 2, 3, 4, 5, 222222)
    with patch("src.request_validator.datetime") as mock_dt:
        mock_dt.now.side_effect = [dt1, dt2]
        err1 = ValidationError(field="f1", reason="r1")
        err2 = ValidationError(field="f2", reason="r2")
    assert err1.timestamp == dt1.isoformat()
    assert err2.timestamp == dt2.isoformat()
    assert err1.timestamp != err2.timestamp


def test_validationerror_init_with_none_values_edge_case():
    """Test that ValidationError handles None values for field and reason."""
    err = ValidationError(field=None, reason=None)
    assert err.field is None
    assert err.reason is None
    d = err.to_dict()
    assert "field" in d and d["field"] is None
    assert "reason" in d and d["reason"] is None
    # Timestamp should still be a valid ISO string
    datetime.fromisoformat(d["timestamp"])  # should not raise


def test_validationerror_to_dict_does_not_mutate_instance(error_instance):
    """Test that calling to_dict does not mutate the ValidationError instance."""
    before_field = error_instance.field
    before_reason = error_instance.reason
    before_timestamp = error_instance.timestamp

    _ = error_instance.to_dict()

    assert error_instance.field == before_field
    assert error_instance.reason == before_reason
    assert error_instance.timestamp == before_timestamp


def test_validationerror_init_raises_when_datetime_now_fails():
    """Test that an exception from datetime.now during initialization propagates."""
    with patch("src.request_validator.datetime") as mock_dt:
        mock_dt.now.side_effect = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            ValidationError(field="any", reason="any")