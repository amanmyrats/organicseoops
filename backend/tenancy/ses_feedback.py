"""Parse only SES feedback from a separately trusted, topic-restricted SQS delivery."""

import json
import re
from datetime import datetime, timedelta, timezone

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from accounts.models import UserManager


_TOPIC = re.compile(r"arn:aws:sns:([a-z0-9-]{5,32}):([0-9]{12}):[A-Za-z0-9_-]{1,100}\Z")
_ID = re.compile(r"[A-Za-z0-9_-]{8,200}\Z")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate feedback field")
        result[key] = value
    return result


def _reject_constant(_):
    raise ValueError("Invalid feedback number")


def _object(raw, limit):
    if not isinstance(raw, (str, bytes)) or len(raw) > limit:
        raise ValueError("Feedback size exceeded")
    result = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    if type(result) is not dict:
        raise ValueError("Feedback must be an object")
    return result


def _when(value, now):
    if not isinstance(value, str) or not 19 <= len(value) <= 40:
        raise ValueError("Invalid feedback time")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None or not now - timedelta(days=7) <= result <= now + timedelta(minutes=5):
        raise ValueError("Out-of-window feedback")
    return result


def _emails(values):
    if type(values) is not list or not 1 <= len(values) <= 10:
        raise ValueError("Invalid recipient list")
    result = set()
    for value in values:
        if type(value) is not str or len(value) > 254:
            raise ValueError("Invalid recipient")
        validate_email(value)
        result.add(UserManager.normalize_email(value))
    return result


def parse_ses_feedback(raw, *, topic_arn, sender, now=None):
    """Return bounded (event ID, kind, addresses), or None for inapplicable feedback.

    Caller must obtain raw bytes from an IAM-restricted SQS queue subscribed only
    to this exact SNS topic. An arbitrary HTTP request is never trusted input here.
    """
    now = now or datetime.now(timezone.utc)
    match = _TOPIC.fullmatch(topic_arn) if type(topic_arn) is str else None
    if not match or type(sender) is not str:
        raise ValidationError("Invalid feedback source configuration.")
    try:
        validate_email(sender)
        envelope = _object(raw, 262144)
        if (envelope.get("Type") != "Notification" or envelope.get("TopicArn") != topic_arn
            or type(envelope.get("MessageId")) is not str
            or not _ID.fullmatch(envelope["MessageId"])):
            raise ValueError("Invalid SNS notification")
        _when(envelope.get("Timestamp"), now)
        event = _object(envelope.get("Message"), 65536)
        mail = event.get("mail")
        if (type(mail) is not dict or mail.get("sendingAccountId") != match.group(2)
            or UserManager.normalize_email(mail.get("source", "")) != UserManager.normalize_email(sender)
            or type(mail.get("messageId")) is not str or not _ID.fullmatch(mail["messageId"])):
            raise ValueError("Invalid SES mail identity")
        _when(mail.get("timestamp"), now)
        destinations = _emails(mail.get("destination"))
        kind = event.get("notificationType")
        if kind == "Delivery":
            return None
        if kind == "Bounce":
            bounce = event.get("bounce")
            if type(bounce) is not dict or bounce.get("bounceType") not in {"Permanent", "Transient", "Undetermined"}:
                raise ValueError("Invalid bounce")
            if bounce["bounceType"] != "Permanent":
                return None
            recipients = bounce.get("bouncedRecipients")
            if type(recipients) is not list or not 1 <= len(recipients) <= 10:
                raise ValueError("Invalid bounced recipients")
            addresses = _emails([item.get("emailAddress") if type(item) is dict else None for item in recipients])
            kind = "permanent_bounce"
        elif kind == "Complaint":
            complaint = event.get("complaint")
            if type(complaint) is not dict:
                raise ValueError("Invalid complaint")
            recipients = complaint.get("complainedRecipients")
            if type(recipients) is not list or len(recipients) > 10:
                raise ValueError("Invalid complained recipients")
            addresses = (_emails([item.get("emailAddress") if type(item) is dict else None for item in recipients])
                         if recipients else destinations)
            # ISPs may supply all possible complainants, not the one who complained.
            if len(destinations) != 1:
                return None
            kind = "complaint"
        else:
            raise ValueError("Unsupported SES notification")
        addresses &= destinations
        return (envelope["MessageId"], kind, tuple(sorted(addresses))) if addresses else None
    except (ValueError, TypeError, UnicodeError, KeyError, ValidationError, RecursionError):
        raise ValidationError("Invalid or unrelated SES feedback.") from None
