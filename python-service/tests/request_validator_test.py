import pytest
from unittest.mock import Mock
from src.request_validator import ValidationError
import src.request_validator as request_validator


@pytest.fixture(autouse=True)
def clear_global_validation_errors():
    """Ensure global validation errors storage is clean before and after each test"""
    request_validator.clear_validation_errors()
    yield
    request_validator.clear_validation_errors()


@pytest.fixture
def set_fake_datetime(monkeypatch):
    """Provide a helper to patch datetime.now().isoformat() to a fixed value"""

    def _set(iso_str: str):
        class FakeNow:
            def isoformat(self):
                return iso_str

        class FakeDatetime:
            @classmethod
            def now(cls):
                return FakeNow()

        monkeypatch.setattr(request_validator, "datetime", FakeDatetime, raising=False)
        return iso_str

    return _set


@pytest.fixture
def fixed_iso():
    """Provide a fixed ISO timestamp for deterministic tests"""
    return "2024-02-03T10:20:30"


@pytest.fixture
def validation_error_instance(set_fake_datetime, fixed_iso):
    """Create a ValidationError instance with deterministic timestamp"""
    set_fake_datetime(fixed_iso)
    return ValidationError(field="test_field", reason="test_reason")


def test_validationerror_init_sets_fields_and_timestamp(validation_error_instance, fixed_iso):
    """Test ValidationError initialization sets field, reason, and timestamp"""
    assert validation_error_instance.field == "test_field"
    assert validation_error_instance.reason == "test_reason"
    assert validation_error_instance.timestamp == fixed_iso


def test_validationerror_to_dict_returns_expected(validation_error_instance, fixed_iso):
    """Test to_dict returns correct dictionary representation"""
    result = validation_error_instance.to_dict()
    assert result == {
        "field": "test_field",
        "reason": "test_reason",
        "timestamp": fixed_iso,
    }


def test_validationerror_init_with_none_and_empty_strings(set_fake_datetime):
    """Test initialization with None and empty strings does not raise and is preserved"""
    iso = set_fake_datetime("2023-01-01T00:00:00")
    err = ValidationError(field=None, reason="")
    assert err.field is None
    assert err.reason == ""
    assert err.timestamp == iso
    assert err.to_dict() == {"field": None, "reason": "", "timestamp": iso}


def test_validationerror_timestamp_immutable_after_creation(set_fake_datetime):
    """Test timestamp is captured at creation and does not change on later calls"""
    iso1 = set_fake_datetime("2022-12-12T12:12:12")
    err = ValidationError(field="a", reason="b")
    iso2 = set_fake_datetime("2033-03-03T03:03:03")
    assert iso1 != iso2
    # The instance should retain the timestamp from creation time
    assert err.timestamp == iso1
    assert err.to_dict()["timestamp"] == iso1


def test_validationerror_init_calls_isoformat_once(monkeypatch):
    """Test __init__ calls datetime.now().isoformat exactly once"""
    mock_now = Mock()
    mock_now.isoformat.return_value = "2030-01-01T00:00:00"

    class FakeDatetime:
        @classmethod
        def now(cls):
            return mock_now

    monkeypatch.setattr(request_validator, "datetime", FakeDatetime, raising=False)

    err = ValidationError(field="x", reason="y")
    assert err.timestamp == "2030-01-01T00:00:00"
    mock_now.isoformat.assert_called_once_with()


def test_validationerror_init_raises_when_isoformat_fails(monkeypatch):
    """Test __init__ raises if datetime.now().isoformat raises an exception"""
    mock_now = Mock()
    mock_now.isoformat.side_effect = RuntimeError("isoformat failure")

    class FakeDatetime:
        @classmethod
        def now(cls):
            return mock_now

    monkeypatch.setattr(request_validator, "datetime", FakeDatetime, raising=False)

    with pytest.raises(RuntimeError):
        ValidationError(field="bad", reason="time")


def test_log_validation_errors_collects_dicts(set_fake_datetime):
    """Test log_validation_errors uses ValidationError.to_dict and stores results"""
    set_fake_datetime("2021-06-01T12:00:00")

    err1 = ValidationError("f1", "r1")
    err2 = ValidationError("f2", "r2")

    # Patch to_dict for controlled output
    err1_dict = {"field": "f1", "reason": "r1", "timestamp": "t1"}
    err2_dict = {"field": "f2", "reason": "r2", "timestamp": "t2"}

    err1.to_dict = lambda: err1_dict  # type: ignore
    err2.to_dict = lambda: err2_dict  # type: ignore

    request_validator.log_validation_errors([err1, err2])
    stored = request_validator.get_validation_errors()

    assert stored == [err1_dict, err2_dict]


def test_keep_recent_errors_trims_to_100_entries(set_fake_datetime):
    """Test that global validation errors are trimmed to the most recent 100 entries"""
    set_fake_datetime("2021-06-01T12:00:00")

    # Add 105 errors one by one to simulate real usage
    for i in range(105):
        err = ValidationError("f", str(i))
        request_validator.log_validation_errors([err])

    stored = request_validator.get_validation_errors()
    assert len(stored) == 100
    # Ensure the first five (0..4) were trimmed off
    reasons = [d["reason"] for d in stored]
    assert reasons[0] == "5"
    assert reasons[-1] == "104"