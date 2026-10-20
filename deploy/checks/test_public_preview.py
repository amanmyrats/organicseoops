import base64
from http.server import ThreadingHTTPServer
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from public_preview import preview_handler


class PrivatePublicPreviewTests(unittest.TestCase):
    def test_local_preview_requires_password_and_never_lists_or_exports_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "public"
            root.mkdir()
            (root / "index.html").write_text("<h1>Synthetic approved fixture</h1>")
            nested = root / "sample-report"
            nested.mkdir()
            (nested / "index.html").write_text("<h1>Synthetic draft fixture</h1>")
            (root / "escape.html").symlink_to(Path(tmp) / "private.txt")
            (Path(tmp) / "private.txt").write_text("private-secret-fixture")
            with ThreadingHTTPServer(("127.0.0.1", 0), preview_handler(root, "fixture-secret-16-characters")) as server:
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                base = f"http://127.0.0.1:{server.server_port}/"
                direct = build_opener(ProxyHandler({}))  # Local fixtures must never use ambient outbound proxies.

                def request(path, authorization=""):
                    headers = {"Authorization": authorization} if authorization else {}
                    return direct.open(Request(base + path, headers=headers), timeout=5)

                try:
                    with self.assertRaises(HTTPError) as denied:
                        request("sample-report/")
                    self.assertEqual(denied.exception.code, 401)
                    self.assertEqual(denied.exception.headers["X-Robots-Tag"], "noindex, nofollow")
                    with self.assertRaises(HTTPError) as rejected:
                        request("sample-report/", "Basic wrong-token")
                    self.assertEqual(rejected.exception.code, 401)
                    auth = "Basic " + base64.b64encode(b"editor:fixture-secret-16-characters").decode()
                    with request("", auth) as response:
                        self.assertIn(b"Synthetic approved fixture", response.read())
                        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
                        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
                    with request("sample-report/", auth) as response:
                        self.assertIn(b"Synthetic draft fixture", response.read())
                        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
                        self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
                    for path, status in (("missing.js", 404), ("escape.html", 403)):
                        with self.assertRaises(HTTPError) as error:
                            request(path, auth)
                        self.assertEqual(error.exception.code, status)
                        self.assertNotIn("private-secret-fixture", error.exception.read().decode())
                finally:
                    server.shutdown()
                    thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
