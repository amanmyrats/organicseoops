import base64
import hashlib
import importlib.util
import os
import time
import unittest
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("isolated_renderer", ROOT / "renderer/service.py")
renderer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(renderer)


class RendererProtocolTests(unittest.TestCase):
    def request(self, html=b"<title>Fixture</title>"):
        request = {
            "protocol": renderer.PROTOCOL_VERSION,
            "request_id": str(uuid.uuid4()),
            "token": "a" * 64,
            "source_hash": hashlib.sha256(html).hexdigest(),
            "method_version": renderer.METHOD_VERSION,
            "base_url": "https://fixture.example/",
            "deadline_ms": int((time.time() + 10) * 1000),
            "html_b64": base64.b64encode(html).decode(),
        }
        request["request_hash"] = renderer.canonical_hash(request)
        return request

    def test_request_identity_hash_version_and_source_are_bound(self):
        request = self.request()
        self.assertIn("Fixture", renderer.validate_request(request))
        for field, value in (("method_version", "other"), ("token", "short"), ("source_hash", "0" * 64)):
            with self.subTest(field=field):
                tampered = {**request, field: value}
                with self.assertRaises(renderer.InvalidRequest):
                    renderer.validate_request(tampered)

    def test_expired_and_oversized_requests_fail(self):
        expired = self.request()
        expired["deadline_ms"] = 0
        expired["request_hash"] = renderer.canonical_hash({key: value for key, value in expired.items()
                                                             if key != "request_hash"})
        with self.assertRaises(TimeoutError):
            renderer.render_child(expired)
        with self.assertRaises(renderer.InvalidRequest):
            renderer.validate_request(self.request(b"x" * (renderer.MAX_HTML_BYTES + 1)))

    def test_blocked_urls_are_sanitized(self):
        self.assertEqual(
            renderer.sanitize_url("https://user:password@example.test:8443/path?token=secret#fragment"),
            "https://example.test:8443/path",
        )
        self.assertEqual(renderer.sanitize_url("javascript:secret()"), "javascript:")

    def test_stale_cleanup_removes_only_expected_regular_files(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as outside:
            root = Path(directory)
            request_name = f"{uuid.uuid4()}.json"
            temporary_name = f".{uuid.uuid4()}.json.0123456789abcdef.tmp"
            stale = [root / request_name, root / temporary_name]
            for path in stale:
                path.write_text("stale")
                os.utime(path, (0, 0))
            active = root / f"{uuid.uuid4()}.json"
            active.write_text("active")
            unexpected = root / "unexpected.json"
            unexpected.write_text("unexpected")
            symlink = root / f"{uuid.uuid4()}.json"
            symlink.symlink_to(Path(outside) / "missing")

            renderer.cleanup_stale(root, now=renderer.STALE_SPOOL_SECONDS + 1)

            self.assertTrue(all(not path.exists() for path in stale))
            self.assertTrue(active.exists())
            self.assertTrue(unexpected.exists())
            self.assertTrue(symlink.is_symlink())


if __name__ == "__main__":
    unittest.main()
