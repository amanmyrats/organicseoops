"""Public contact input; validation grants no support or send authority."""
import json
import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from integrations.google_tokens import _reject_constant, _unique_object
from .support_requests import validate_support_command


FIELDS = frozenset({"request_key", "category", "language", "reply_email", "question", "no_sensitive_data"})
CATEGORIES = frozenset({"sales", "support", "privacy", "accessibility"})
MAX_BODY = 16 * 1024
ERROR = "Use one bounded contact question without sensitive data."


def validate_contact_command(command):
    if (type(command) is not dict or set(command) != FIELDS
        or type(command["category"]) is not str or command["category"] not in CATEGORIES
        or type(command["language"]) is not str or command["language"] not in {"en", "tr"}):
        raise ValidationError(ERROR)
    email = command["reply_email"]
    if (type(email) is not str or not 3 <= len(email) <= 254 or email != email.strip()
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in email)):
        raise ValidationError(ERROR)
    try:
        validate_email(email)
        validate_support_command({"request_key": command["request_key"], "category": "other",
            "question": command["question"], "job_id": None, "no_sensitive_data": command["no_sensitive_data"]})
    except (ValidationError, UnicodeError):
        raise ValidationError(ERROR) from None
    return dict(command)


def parse_contact_command(body):
    if type(body) is not bytes or not 1 <= len(body) <= MAX_BODY:
        raise ValidationError(ERROR)
    try:
        command = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ValidationError(ERROR) from None
    return validate_contact_command(command)
