import json
from datetime import datetime, timezone

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .ses_feedback import parse_ses_feedback


NOW = datetime(2026, 9, 28, 14, tzinfo=timezone.utc)
TOPIC = "arn:aws:sns:eu-west-1:123456789012:organicseoops-mail-feedback"
SENDER = "notices@example.invalid"


def feedback(kind="Bounce", *, recipients=None, destinations=None):
    destinations = destinations or ["owner@example.invalid"]
    recipients = recipients if recipients is not None else [{"emailAddress": "owner@example.invalid"}]
    event = {"notificationType": kind, "mail": {"source": SENDER, "sendingAccountId": "123456789012",
             "messageId": "ses-message-0001", "timestamp": NOW.isoformat(), "destination": destinations}}
    if kind == "Bounce":
        event["bounce"] = {"bounceType": "Permanent", "bouncedRecipients": recipients}
    if kind == "Complaint":
        event["complaint"] = {"complainedRecipients": recipients}
    return {"Type": "Notification", "TopicArn": TOPIC, "MessageId": "sns-message-0001",
            "Timestamp": NOW.isoformat(), "Message": json.dumps(event)}


class SesFeedbackParserTests(SimpleTestCase):
    def parse(self, payload, **changes):
        return parse_ses_feedback(json.dumps(payload).encode(), topic_arn=TOPIC, sender=SENDER,
                                  now=NOW, **changes)

    def test_permanent_bounce_and_one_recipient_complaint(self):
        self.assertEqual(self.parse(feedback()), ("sns-message-0001", "permanent_bounce", ("owner@example.invalid",)))
        self.assertEqual(self.parse(feedback("Complaint", recipients=[])),
                         ("sns-message-0001", "complaint", ("owner@example.invalid",)))
        self.assertIsNone(self.parse(feedback("Complaint", destinations=["owner@example.invalid", "other@example.invalid"])))
        self.assertIsNone(self.parse(feedback("Bounce", recipients=[{"emailAddress": "foreign@example.invalid"}])))

    def test_delivery_transient_and_unrelated_source_never_suppress(self):
        self.assertIsNone(self.parse(feedback("Delivery")))
        transient = feedback()
        event = json.loads(transient["Message"])
        event["bounce"]["bounceType"] = "Transient"
        transient["Message"] = json.dumps(event)
        self.assertIsNone(self.parse(transient))
        for change in ({"TopicArn": "arn:aws:sns:eu-west-1:123456789012:foreign"},
                       {"Type": "SubscriptionConfirmation"}, {"Timestamp": "2020-01-01T00:00:00Z"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                self.parse({**feedback(), **change})
        foreign = feedback()
        event = json.loads(foreign["Message"])
        event["mail"]["sendingAccountId"] = "999999999999"
        foreign["Message"] = json.dumps(event)
        with self.assertRaises(ValidationError):
            self.parse(foreign)

    def test_duplicate_invalid_and_oversized_envelopes_fail_closed(self):
        for payload in (b'{}', b'{"Type":"Notification","Type":"Notification"}', b'[' + b' ' * 262144 + b']'):
            with self.subTest(payload=payload[:30]), self.assertRaises(ValidationError):
                parse_ses_feedback(payload, topic_arn=TOPIC, sender=SENDER, now=NOW)
        invalid = feedback()
        invalid["Message"] = '{"mail":{},"mail":{}}'
        with self.assertRaises(ValidationError):
            self.parse(invalid)
