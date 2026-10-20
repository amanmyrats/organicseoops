import json
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from .public_contact import ERROR, MAX_BODY, parse_contact_command, validate_contact_command


class PublicContactCommandTests(SimpleTestCase):
    def command(self, **changes):
        return {**dict(request_key="contact-request-001", category="sales", language="en",
                      reply_email="reply@example.invalid", question="How does product access work?",
                      no_sensitive_data=True), **changes}

    def test_exact_categories_languages_and_literal_text_without_database_or_delivery(self):
        with patch("django.core.mail.send_mail", side_effect=AssertionError("mail")), \
                patch("socket.create_connection", side_effect=AssertionError("network")):
            for category in ("sales", "support", "privacy", "accessibility"):
                for language in ("en", "tr"):
                    command = self.command(category=category, language=language,
                        question="Türkçe <script>inert plain text</script>\nSecond line\tend")
                    result = parse_contact_command(json.dumps(command).encode())
                    self.assertEqual(result, command)
                    self.assertIsNot(result, command)
                    self.assertNotIn("status", result)
            self.assertEqual(validate_contact_command(self.command(question="x" * 2000))["question"], "x" * 2000)

    def test_rejects_extra_authority_bad_scalars_address_controls_and_sensitive_text_without_echo(self):
        changes = (
            {"project_id": 1}, {"organization_id": 1}, {"job_id": 1}, {"recipient": "staff@example.invalid"},
            {"requester_id": 1}, {"category": ["sales"]}, {"category": "other"}, {"language": ["en"]},
            {"language": "de"}, {"no_sensitive_data": 1}, {"no_sensitive_data": False}, {"request_key": "short"},
            {"question": " "}, {"question": "x" * 2001}, {"question": "\ud800"}, {"question": "hidden\u202emark"},
            {"question": "Authorization: Bearer private-marker"}, {"question": "api_key=private-marker"},
            {"reply_email": ["reply@example.invalid"]}, {"reply_email": "Display <reply@example.invalid>"},
            {"reply_email": "reply@example.invalid\nBcc: private-marker@example.invalid"},
            {"reply_email": " reply@example.invalid"}, {"reply_email": "reply\u200b@example.invalid"},
            {"reply_email": "private-marker"}, {"reply_email": "\ud800@example.invalid"},
            {"reply_email": "a" * 255 + "@example.invalid"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValidationError) as raised:
                validate_contact_command(self.command(**change))
            self.assertEqual(raised.exception.messages, [ERROR])
        for command in (None, [], "bad", {}, {key: value for key, value in self.command().items() if key != "language"}):
            with self.assertRaises(ValidationError):
                validate_contact_command(command)

    def test_strict_bounded_utf8_json_rejects_duplicate_fields_nonfinite_and_nonobjects(self):
        valid = json.dumps(self.command()).encode()
        for body in (b"", b"\xff", b"{", b"[]", b"null", b'"text"', b'{"value":NaN}',
                     valid[:-1] + b',"language":"tr"}', b" " * (MAX_BODY + 1), valid.decode(), bytearray(valid),
                     b"[" * 2000 + b"]" * 2000):
            with self.subTest(body_type=type(body)), self.assertRaises(ValidationError) as raised:
                parse_contact_command(body)
            self.assertEqual(raised.exception.messages, [ERROR])
        self.assertEqual(parse_contact_command(valid + b" " * (MAX_BODY - len(valid))), self.command())
