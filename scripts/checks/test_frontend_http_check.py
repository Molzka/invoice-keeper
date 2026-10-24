"""Regression checks for the frontend container HTTP contract (stdlib only)."""

import base64
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import threading
import unittest

import check_frontend


INDEX = b'''<!doctype html><html><head>
<link rel="icon" type="image/png" href="/brand/aeza.png">
<script src="/theme-init.js"></script>
<script type="module" src="/assets/app-123.js"></script>
<link rel="stylesheet" href="/assets/app-123.css">
</head><body><div id="root"></div></body></html>'''
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6itkAAAAASUVORK5CYII=")


class FrontendHttpCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests.append(self.path)
                status, mime, cache, body = cls.responses.get(
                    self.path, (404, "text/plain", "no-cache", b"missing")
                )
                self.send_response(status)
                self.send_header("Content-Type", mime)
                self.send_header("Cache-Control", cache)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        type(self).requests = []
        unavailable = json.dumps({"error": {
            "code": "API_NOT_AVAILABLE", "message": "API unavailable", "details": []
        }}).encode()
        type(self).responses = {
            "/": (200, "text/html", "no-cache", INDEX),
            "/index.html": (200, "text/html", "no-cache", INDEX),
            "/theme-init.js": (200, "text/javascript", "no-cache", b"document.documentElement.dataset.theme='dark'"),
            "/assets/app-123.js": (200, "text/javascript", "public, max-age=31536000, immutable", b"export const app = true"),
            "/assets/app-123.css": (200, "text/css", "public, max-age=31536000, immutable", b"body {color:black}"),
            "/brand/aeza.png": (200, "image/png", "no-cache", PNG),
            "/healthz": (200, "text/plain", "no-cache", b"ok\n"),
            "/api": (503, "application/json", "no-store", unavailable),
            "/api/v1/health": (503, "application/json", "no-store", unavailable),
            "/api/v1/ready": (200, "application/json", "no-store", b'{"status":"ok"}'),
        }

    def run_check(self, **kwargs):
        with redirect_stdout(io.StringIO()):
            check_frontend.check(self.origin, **kwargs)

    def set_index(self, value):
        for path in ("/", "/index.html"):
            self.responses[path] = (200, "text/html", "no-cache", value)

    def test_theme_bootstrap_and_actual_png_favicon_pass(self):
        self.run_check()
        self.assertIn("/theme-init.js", self.requests)
        self.assertIn("/brand/aeza.png", self.requests)
        self.assertNotIn("/glass-calendar.png", self.requests)

    def test_ready_api_mode_retains_asset_checks(self):
        self.run_check(api_ready=True)
        self.assertIn("/api/v1/ready", self.requests)
        self.assertIn("/theme-init.js", self.requests)

    def test_stable_theme_url_cannot_be_cached_immutably(self):
        status, mime, _cache, body = self.responses["/theme-init.js"]
        self.responses["/theme-init.js"] = (status, mime, "public, max-age=31536000, immutable", body)
        with self.assertRaisesRegex(RuntimeError, "theme bootstrap must revalidate"):
            self.run_check()

    def test_hashed_bundle_still_requires_immutable_cache(self):
        status, mime, _cache, body = self.responses["/assets/app-123.js"]
        self.responses["/assets/app-123.js"] = (status, mime, "no-cache", body)
        with self.assertRaisesRegex(RuntimeError, "missing immutable cache policy"):
            self.run_check()

    def test_other_unhashed_scripts_are_rejected(self):
        self.set_index(INDEX.replace(b"/theme-init.js", b"/unapproved.js"))
        with self.assertRaisesRegex(RuntimeError, "Expected a local built asset or theme bootstrap"):
            self.run_check()
        self.assertNotIn("/unapproved.js", self.requests)

    def test_external_assets_are_rejected_without_requesting_them(self):
        self.set_index(INDEX.replace(b"/theme-init.js", b"https://external.invalid/theme-init.js"))
        with self.assertRaisesRegex(RuntimeError, "Expected a local built asset or theme bootstrap"):
            self.run_check()

    def test_theme_bootstrap_does_not_replace_the_built_bundle(self):
        self.set_index(INDEX.replace(b'<script type="module" src="/assets/app-123.js"></script>', b""))
        with self.assertRaisesRegex(RuntimeError, "No built JavaScript"):
            self.run_check()

    def test_html_fallback_cannot_masquerade_as_bootstrap(self):
        self.responses["/theme-init.js"] = (200, "text/javascript", "no-cache", b"<!DOCTYPE html><html></html>")
        with self.assertRaisesRegex(RuntimeError, "missing asset contents"):
            self.run_check()

    def test_actual_favicon_must_have_the_correct_mime_type(self):
        self.responses["/brand/aeza.png"] = (200, "text/html", "no-cache", b"<!doctype html>")
        with self.assertRaisesRegex(RuntimeError, "unexpected Content-Type"):
            self.run_check()

    def test_source_environment_files_remain_forbidden(self):
        self.responses["/src/.env"] = (200, "text/plain", "no-cache", b"test fixture")
        with self.assertRaisesRegex(RuntimeError, "expected HTTP 404, got 200"):
            self.run_check()


if __name__ == "__main__":
    unittest.main()
