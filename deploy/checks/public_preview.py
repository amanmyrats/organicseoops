"""Local-only password-protected preview of generated frontend HTML; never deploy."""
import argparse
import base64
import getpass
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import compare_digest


DEFAULT_OUTPUT = Path(__file__).resolve().parents[2] / "frontend/dist/organicseoops/browser"


def preview_handler(directory, password):
    root = Path(directory).resolve(strict=True)
    expected = "Basic " + base64.b64encode(f"editor:{password}".encode()).decode()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def _authorized(self):
            if compare_digest(self.headers.get("Authorization", ""), expected):
                return True
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Local content preview"')
            self.end_headers()
            return False

        def do_GET(self):
            if self._authorized():
                super().do_GET()

        def do_HEAD(self):
            if self._authorized():
                super().do_HEAD()

        def send_head(self):
            if not Path(self.translate_path(self.path)).resolve().is_relative_to(root):
                self.send_error(403)
                return None
            return super().send_head()

        def list_directory(self, path):
            self.send_error(404)
            return None

        def end_headers(self):
            self.send_header("X-Robots-Tag", "noindex, nofollow")
            self.send_header("Cache-Control", "private, no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            super().end_headers()

        def log_message(self, format, *args):
            pass  # Never log preview URLs, headers or draft contents.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18105)
    parser.add_argument("--candidate", action="store_true", help="Preview the separate unapproved metadata candidate")
    args = parser.parse_args()
    output = DEFAULT_OUTPUT.parent / "review-browser" if args.candidate else DEFAULT_OUTPUT
    if not 1024 <= args.port <= 65535 or not output.is_dir():
        parser.error("Use an unprivileged port after a successful frontend production build")
    password = getpass.getpass("Local preview password (at least 16 characters): ")
    if len(password) < 16:
        parser.error("Choose a longer local-only preview password")
    with ThreadingHTTPServer(("127.0.0.1", args.port), preview_handler(output, password)) as server:
        print(f"Local private preview: http://127.0.0.1:{server.server_port}/")
        server.serve_forever()


if __name__ == "__main__":
    main()
