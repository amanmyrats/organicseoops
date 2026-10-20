from datetime import datetime, timedelta, timezone
import json

from django.test import SimpleTestCase

from .bot_logs import BotLogError, MAX_BYTES, MAX_LINE_BYTES, MAX_ROWS, parse_bot_logs


class BotLogParserTests(SimpleTestCase):
    def setUp(self):
        self.end = datetime(2026, 10, 1, tzinfo=timezone.utc)
        self.args = {"origin": "https://logs.example.invalid", "window_start": self.end - timedelta(days=1),
                     "window_end": self.end, "now": self.end, "known_urls": ["https://logs.example.invalid/service"]}
        self.row = {"timestamp": "2026-09-30T12:00:00Z", "origin": self.args["origin"], "target": "/service?token=raw-secret#personal",
                    "status": 200, "user_agent": "Mozilla compatible; OAI-SearchBot/1.4; raw-secret"}

    def parse(self, rows, **changes):
        return parse_bot_logs("\n".join(json.dumps(row) for row in rows).encode(), **{**self.args, **changes})

    def test_known_inventory_only_redaction_utc_status_counts_and_repeat_requests_not_visitors(self):
        rows = [{**self.row, "ip": "192.0.2.99", "cookie": "raw-secret", "referrer": "private-personal"}, self.row,
                {**self.row, "timestamp": "2026-09-30T15:00:00+02:00", "status": 404},
                {**self.row, "target": "/private-personal/raw-secret?email=someone@example.invalid", "user_agent": "ChatGPT-User/1.0"}]
        report = self.parse(rows)
        self.assertEqual(report["rows_seen"], 4)
        search = next(row for row in report["groups"] if row["agent"] == "OAI-SearchBot")
        self.assertEqual(search["request_count"], 3)
        self.assertEqual(search["status_counts"], {"200": 2, "404": 1})
        self.assertEqual(search["last_seen"], "2026-09-30T13:00:00+00:00")
        self.assertEqual(search["known_url"], self.args["known_urls"][0])
        user = next(row for row in report["groups"] if row["agent"] == "ChatGPT-User")
        self.assertIsNone(user["known_url"]); self.assertEqual(user["identity"], "user_agent_only_unverified")
        serialized = json.dumps(report)
        for value in ("raw-secret", "private-personal", "192.0.2.99", "someone@example.invalid", "Mozilla", "cookie", "referrer"):
            self.assertNotIn(value, serialized)
        self.assertEqual(report["coverage"], "partial_customer_supplied_logs")

    def test_spoofed_and_ambiguous_user_agents_never_become_verified_identities(self):
        report = self.parse([{**self.row, "user_agent": value} for value in (
            "FakeOAI-SearchBot", "OAI-SearchBot-Evil", "GPTBot ChatGPT-User", "browser", "GPTBot/1.4")])
        self.assertEqual({row["agent"]: row["request_count"] for row in report["groups"]}, {"other_unclassified": 4, "GPTBot": 1})
        self.assertTrue(all(row["identity"] == "user_agent_only_unverified" for row in report["groups"]))

    def test_malformed_unsafe_foreign_duplicate_and_temporal_rows_fail_categorically(self):
        for change in ({"origin": "https://foreign.example.invalid"}, {"status": True}, {"status": 600},
                       {"target": "//foreign.example.invalid/secret"}, {"target": "/\\raw-secret"},
                       {"timestamp": "2026-10-01T00:00:00Z"}, {"timestamp": "2026-09-30T12:00:00"},
                       {"timestamp": "2026-02-30T12:00:00Z"}, {"user_agent": "\ud800raw-secret"}, {"user_agent": "raw-secret\n"}):
            with self.subTest(change=change), self.assertRaises(BotLogError) as raised:
                self.parse([{**self.row, **change}])
            self.assertNotIn("raw-secret", str(raised.exception))
        with self.assertRaisesRegex(BotLogError, "invalid_timestamp"):
            self.parse([{**self.row, "timestamp": "0001-01-01T00:00:00+10:00"}])
        for raw in (b"not raw-secret json", b'{"status":200,"status":500}', b'\xff', b'{"extra":NaN}', b"\n"):
            with self.assertRaises(BotLogError): parse_bot_logs(raw, **self.args)
        with self.assertRaises(BotLogError): self.parse([self.row], known_urls=["https://foreign.example.invalid/service"])
        with self.assertRaises(BotLogError): self.parse([self.row], known_urls=[self.args["known_urls"][0] + "?secret=raw-secret"])
        with self.assertRaisesRegex(BotLogError, "invalid_inventory"): self.parse([self.row], known_urls=["https://[bad.example.invalid/service"])

    def test_byte_line_row_group_and_window_limits_are_enforced_without_truncation(self):
        for raw in (b"x" * (MAX_BYTES + 1), b"x" * (MAX_LINE_BYTES + 1)):
            with self.assertRaises(BotLogError): parse_bot_logs(raw, **self.args)
        with self.assertRaisesRegex(BotLogError, "row_limit"): self.parse([self.row] * (MAX_ROWS + 1))
        urls = [self.args["origin"] + f"/path-{index}" for index in range(101)]
        with self.assertRaisesRegex(BotLogError, "group_limit"):
            self.parse([{**self.row, "target": f"/path-{index}"} for index in range(101)], known_urls=urls)
        paths = ["/" + "a" * 450 + str(index) for index in range(70)]
        with self.assertRaisesRegex(BotLogError, "summary_limit"):
            self.parse([{**self.row, "target": path} for path in paths], known_urls=[self.args["origin"] + path for path in paths])
        with self.assertRaisesRegex(BotLogError, "invalid_coverage_window"):
            self.parse([self.row], window_start=self.end - timedelta(days=8))
        with self.assertRaisesRegex(BotLogError, "invalid_coverage_window"):
            self.parse([self.row], window_end=self.end + timedelta(seconds=1))
        with self.assertRaisesRegex(BotLogError, "invalid_coverage_window"):
            self.parse([self.row], window_start=(self.end - timedelta(days=1)).replace(tzinfo=None))
