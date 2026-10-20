"""Private IAM/SQS receive boundary; no HTTP feedback endpoint exists."""

import boto3
from botocore.config import Config
from django.conf import settings
from django.core.exceptions import ValidationError

from .ses_feedback import parse_ses_feedback


def poll_ses_feedback(*, handle, client=None):
    """Acknowledge only accepted/irrelevant messages; malformed input goes to the queue DLQ."""
    if not settings.SES_FEEDBACK_QUEUE_URL or not settings.SES_FEEDBACK_TOPIC_ARN:
        return 0
    if client is None:
        client = boto3.client("sqs", region_name=settings.SES_FEEDBACK_REGION,
                              config=Config(connect_timeout=5, read_timeout=10,
                                            retries={"total_max_attempts": 1}))
    response = client.receive_message(QueueUrl=settings.SES_FEEDBACK_QUEUE_URL,
                                      MaxNumberOfMessages=10, WaitTimeSeconds=0, VisibilityTimeout=60)
    messages = response.get("Messages", []) if type(response) is dict else None
    if type(messages) is not list or len(messages) > 10:
        raise ValidationError("Invalid feedback queue response.")
    acknowledged = 0
    for message in messages:
        if type(message) is not dict or type(message.get("ReceiptHandle")) is not str:
            continue
        receipt_handle = message["ReceiptHandle"]
        if not 1 <= len(receipt_handle) <= 1024 or not receipt_handle.isascii() or any(
            char.isspace() for char in receipt_handle
        ):
            continue
        try:
            event = parse_ses_feedback(message.get("Body"), topic_arn=settings.SES_FEEDBACK_TOPIC_ARN,
                                       sender=settings.DEFAULT_FROM_EMAIL)
        except ValidationError:
            continue  # Not ours: do not delete; policy-configured DLQ retains it for inspection.
        if event is None or handle(event) is True:
            client.delete_message(QueueUrl=settings.SES_FEEDBACK_QUEUE_URL, ReceiptHandle=receipt_handle)
            acknowledged += 1
    return acknowledged
