from datetime import datetime
from typing import Any, Dict, Optional


class ValidationError:
    def __init__(self, field: Optional[str], reason: Optional[str]) -> None:
        self.field = field
        self.reason = reason
        # Let exceptions from datetime.now() propagate as tests expect
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "field": self.field,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }