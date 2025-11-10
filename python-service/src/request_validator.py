import re
from datetime import datetime
from threading import Lock
from typing import List, Dict, Optional

MAX_CONTENT_SIZE = 1_000_000
MAX_PATH_LENGTH = 500
ALLOWED_LANGUAGES = ['go', 'python', 'ruby', 'javascript', 'typescript', 'java']

validation_errors: List[Dict] = []
validation_lock = Lock()


class ValidationError:
    def __init__(self, field: str, reason: str):
        self.field = field
        self.reason = reason
        self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict:
        return {
            'field': self.field,
            'reason': self.reason,
            'timestamp': self.timestamp
        }


def validate_review_request(data: Dict) -> List[ValidationError]:
    errors = []

    content = data.get('content')
    language = data.get('language')

    if not content:
        errors.append(ValidationError('content', 'Content is required and cannot be empty'))
    elif len(content) > MAX_CONTENT_SIZE:
        errors.append(ValidationError('content', f'Content exceeds maximum size of {MAX_CONTENT_SIZE} bytes'))
    elif contains_null_bytes(content):
        errors.append(ValidationError('content', 'Content contains invalid null bytes'))

    if language and language not in ALLOWED_LANGUAGES:
        errors.append(ValidationError('language', f'Language must be one of: {", ".join(ALLOWED_LANGUAGES)}'))

    log_validation_errors(errors)
    return errors


def validate_statistics_request(data: Dict) -> List[ValidationError]:
    errors = []

    files = data.get('files')

    if not files:
        errors.append(ValidationError('files', 'Files array is required'))
    elif not isinstance(files, list):
        errors.append(ValidationError('files', 'Files must be an array'))
    elif len(files) == 0:
        errors.append(ValidationError('files', 'Files array cannot be empty'))
    elif len(files) > 1000:
        errors.append(ValidationError('files', 'Files array cannot exceed 1000 entries'))

    log_validation_errors(errors)
    return errors


def sanitize_input(input_str: Optional[str]) -> Optional[str]:
    if input_str is None:
        return None
    if not isinstance(input_str, str):
        return str(input_str)

    sanitized = []
    for char in input_str:
        code = ord(char)
        if code == 0 or (1 <= code <= 8) or code == 11 or code == 12 or (14 <= code <= 31) or code == 127:
            continue
        if char in ['\n', '\r', '\t']:
            sanitized.append(char)
        elif not char.isprintable() and char not in ['\n', '\r', '\t']:
            continue
        else:
            sanitized.append(char)

    return ''.join(sanitized)


def sanitize_request_data(data: Dict) -> Dict:
    sanitized = data.copy()

    if 'content' in sanitized and isinstance(sanitized['content'], str):
        sanitized['content'] = sanitize_input(sanitized['content'])

    if 'language' in sanitized and isinstance(sanitized['language'], str):
        sanitized['language'] = sanitize_input(sanitized['language'])

    if 'path' in sanitized and isinstance(sanitized['path'], str):
        sanitized['path'] = sanitize_input(sanitized['path'])

    return sanitized


def contains_null_bytes(content: str) -> bool:
    return '\x00' in content


def contains_path_traversal(path: str) -> bool:
    return '..' in path or '~/' in path


def log_validation_errors(errors: List[ValidationError]):
    if not errors:
        return

    with validation_lock:
        validation_errors.extend([error.to_dict() for error in errors])
        keep_recent_errors()


def keep_recent_errors():
    global validation_errors
    if len(validation_errors) > 100:
        validation_errors = validation_errors[-100:]


def get_validation_errors() -> List[Dict]:
    with validation_lock:
        return validation_errors.copy()


def clear_validation_errors():
    with validation_lock:
        validation_errors.clear()
