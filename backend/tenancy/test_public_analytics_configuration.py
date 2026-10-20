import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from .public_analytics_policy import ERROR, MAX_BYTES, load_public_analytics_policy, parse_public_analytics_policy
from .test_public_analytics_policy import policy


class PublicAnalyticsConfigurationTests(SimpleTestCase):
    def test_actual_bounded_file_pin_origin_default_off_and_current_displacement(self):
        content = json.dumps(policy()).encode()
        pin = parse_public_analytics_policy(content)[1]
        with TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            path.write_bytes(content)
            with override_settings(PUBLIC_ANALYTICS_ENABLED=True, PUBLIC_ANALYTICS_POLICY_FILE=str(path),
                                   PUBLIC_ANALYTICS_POLICY_SHA256=pin, FRONTEND_ORIGIN=policy()["origin"]):
                self.assertEqual(load_public_analytics_policy(), (content, pin))
                for changes in ({"PUBLIC_ANALYTICS_ENABLED": False}, {"PUBLIC_ANALYTICS_ENABLED": 1},
                                {"PUBLIC_ANALYTICS_POLICY_FILE": "relative.json"},
                                {"PUBLIC_ANALYTICS_POLICY_SHA256": "f" * 64},
                                {"FRONTEND_ORIGIN": "https://other.example.invalid"},
                                {"PUBLIC_ANALYTICS_POLICY_FILE": ""}):
                    with override_settings(**changes), self.assertRaisesMessage(ValueError, ERROR):
                        load_public_analytics_policy()
                for bad in (b"", b"\xff", b" " * (MAX_BYTES + 1), b'{"token":"private"}',
                            json.dumps({**policy(), "origin": "https://other.example.invalid"}).encode()):
                    path.write_bytes(bad)
                    with self.assertRaisesMessage(ValueError, ERROR): load_public_analytics_policy()
                path.unlink()
                with self.assertRaisesMessage(ValueError, ERROR): load_public_analytics_policy()
                os.mkfifo(path)
                with self.assertRaisesMessage(ValueError, ERROR): load_public_analytics_policy()
                path.unlink()
                target = Path(directory) / "checked.json"
                target.write_bytes(content)
                path.symlink_to(target)
                with self.assertRaisesMessage(ValueError, ERROR): load_public_analytics_policy()
        # Legacy test-only bytes cannot supply deployment authority.
        with override_settings(PUBLIC_ANALYTICS_ENABLED=False, PUBLIC_ANALYTICS_POLICY_BYTES=content):
            with self.assertRaisesMessage(ValueError, ERROR): load_public_analytics_policy()
