"""Load recorder credentials with the confirmed 16-character login limit."""

import json
from pathlib import Path

DEFAULT_CREDENTIALS_FILE = Path(__file__).resolve().parents[1] / ".local/nvr-credentials.json"
LOGIN_PASSWORD_MAX_CHARS = 16


def load_credentials(path=None):
    """Read credentials without changing the file; limit only the login password.

    The username and verification/encryption code are preserved. Callers must
    keep credentials private and apply any protocol-specific encoding afterward.
    """
    source = Path(path) if path is not None else DEFAULT_CREDENTIALS_FILE
    try:
        credentials = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise ValueError("credential file must contain valid JSON") from None
    if not isinstance(credentials, dict):
        raise ValueError("credential file must contain a JSON object")
    for key in ("username", "password"):
        value = credentials.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"a nonempty {key} string is required")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError(f"control characters are not allowed in {key}")
    if "verification_code" in credentials and not isinstance(credentials["verification_code"], str):
        raise ValueError("verification_code must be a string")
    credentials["password"] = credentials["password"][:LOGIN_PASSWORD_MAX_CHARS]
    return credentials
