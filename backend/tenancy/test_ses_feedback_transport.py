import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from .ses_feedback import parse_ses_feedback
from .ses_feedback_transport import poll_ses_feedback
from .test_ses_feedback import NOW, SENDER, TOPIC, feedback


QUEUE = "https://sqs.eu-west-1.amazonaws.com/123456789012/organicseoops-mail-feedback"


@override_settings(SES_FEEDBACK_QUEUE_URL=QUEUE, SES_FEEDBACK_TOPIC_ARN=TOPIC,
                   SES_FEEDBACK_REGION="eu-west-1", DEFAULT_FROM_EMAIL=SENDER)
class SesFeedbackTransportTests(SimpleTestCase):
    def test_private_queue_deletes_only_processed_or_irrelevant_events(self):
        messages = [
            {"Body": json.dumps(feedback()), "ReceiptHandle": "valid_receipt"},
            {"Body": json.dumps(feedback("Delivery")), "ReceiptHandle": "delivery_receipt"},
            {"Body": json.dumps({**feedback(), "TopicArn": "arn:aws:sns:eu-west-1:123456789012:foreign"}),
             "ReceiptHandle": "foreign_receipt"},
            {"Body": json.dumps(feedback()), "ReceiptHandle": "unprocessed_receipt"},
        ]

        class FakeQueue:
            def __init__(self):
                self.deleted = []

            def receive_message(self, **kwargs):
                self.request = kwargs
                return {"Messages": messages}

            def delete_message(self, **kwargs):
                self.deleted.append(kwargs["ReceiptHandle"])

        queue = FakeQueue()
        received = []

        def process(event):
            received.append(event)
            return len(received) == 1

        with patch("tenancy.ses_feedback_transport.parse_ses_feedback",
                   side_effect=lambda raw, **kwargs: parse_ses_feedback(raw, now=NOW, **kwargs)):
            self.assertEqual(poll_ses_feedback(handle=process, client=queue), 2)
        self.assertEqual(queue.request, {"QueueUrl": QUEUE, "MaxNumberOfMessages": 10,
                                         "WaitTimeSeconds": 0, "VisibilityTimeout": 60})
        self.assertEqual(queue.deleted, ["valid_receipt", "delivery_receipt"])
        self.assertEqual(len(received), 2)

    @override_settings(SES_FEEDBACK_QUEUE_URL="", SES_FEEDBACK_TOPIC_ARN="")
    def test_unconfigured_feedback_never_reads_aws(self):
        with patch("tenancy.ses_feedback_transport.boto3.client") as client:
            self.assertEqual(poll_ses_feedback(handle=lambda _: True), 0)
        client.assert_not_called()
