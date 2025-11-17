from datetime import datetime
from typing import Any, Dict


class ValidationError:
    def __init__(self, field: Any, reason: Any):
        self.field = field
        self.reason = reason
        # Allow exceptions from isoformat() to propagate as tests expect
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }