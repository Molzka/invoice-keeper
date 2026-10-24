"""Check a running frontend container over HTTP (Python 3.10+, no dependencies)."""

import argparse
import json
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.paths = set()
        self.icons = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.paths.add(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet":
            self.paths.add(attrs.get("href", ""))
        if tag == "link" and "icon" in attrs.get("rel", "").split():
            self.icons.add(attrs.get("href", ""))


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def fetch(base_url, path, expected_status, expected_type=None):
    url = base_url + path
    try:
        response = urlopen(url, timeout=10)
    except HTTPError as error:
        response = error
    with response:
        require(response.status == expected_status,
                f"{path}: expected HTTP {expected_status}, got {response.status}")
        require(response.geturl() == url, f"{path}: unexpected redirect")
        if expected_type:
            require(response.headers.get_content_type() in expected_type,
                    f"{path}: unexpected Content-Type {response.headers.get('Content-Type')}")
        body = response.read()
        headers = response.headers
    print(f"OK {expected_status} {path}")
    return body, headers


def check(base_url, api_ready=False):
    index, headers = fetch(base_url, "/index.html", 200, {"text/html"})
    require(b'<div id="root"></div>' in index, "Missing React root in index.html")
    require("no-cache" in headers.get("Cache-Control", ""), "index.html must not be cached without revalidation")
    home, headers = fetch(base_url, "/", 200, {"text/html"})
    require(home == index, "/ must serve index.html")
    require("no-cache" in headers.get("Cache-Control", ""), "/ must not be cached without revalidation")

    parser = Assets()
    parser.feed(index.decode("utf-8"))
    require(any(path.startswith("/assets/") and path.endswith(".js") for path in parser.paths),
            "No built JavaScript in index.html")
    require(any(path.endswith(".css") for path in parser.paths), "No built stylesheet in index.html")
    for path in sorted(parser.paths):
        address = urlsplit(path)
        require((path.startswith("/assets/") or path == "/theme-init.js")
                and not address.netloc and not address.scheme and not address.query and not address.fragment,
                f"Expected a local built asset or theme bootstrap, got {path}")
        types = {"text/css"} if path.endswith(".css") else {"text/javascript", "application/javascript"}
        body, headers = fetch(base_url, path, 200, types)
        require(body and not body.lstrip().lower().startswith(b"<!doctype html"), f"{path}: missing asset contents")
        cache = headers.get("Cache-Control", "").lower()
        if path == "/theme-init.js":
            # This stable URL runs before React; it must revalidate after deployment.
            require("no-cache" in cache and "immutable" not in cache,
                    f"{path}: theme bootstrap must revalidate instead of using immutable caching")
        else:
            require("immutable" in cache, f"{path}: missing immutable cache policy")

    require(parser.icons, "No favicon in index.html")
    icon_types = {
        "png": {"image/png"}, "svg": {"image/svg+xml"}, "webp": {"image/webp"},
        "ico": {"image/x-icon", "image/vnd.microsoft.icon"},
        "jpg": {"image/jpeg"}, "jpeg": {"image/jpeg"},
    }
    for path in sorted(parser.icons):
        address = urlsplit(path)
        require(path.startswith("/") and not address.netloc and not address.scheme
                and not address.query and not address.fragment,
                f"Expected a local favicon, got {path}")
        types = icon_types.get(path.rsplit(".", 1)[-1].lower())
        require(types, f"Unsupported favicon format: {path}")
        body, _ = fetch(base_url, path, 200, types)
        require(body and not body.lstrip().lower().startswith(b"<!doctype html"),
                f"{path}: missing favicon contents")
    health, _ = fetch(base_url, "/healthz", 200, {"text/plain"})
    require(health == b"ok\n", "Unexpected frontend health response")

    if api_ready:
        body, _ = fetch(base_url, "/api/v1/ready", 200, {"application/json"})
        require(json.loads(body) == {"status": "ok"}, "API is not ready")

    for path in (() if api_ready else ("/api", "/api/v1/health")):
        body, _ = fetch(base_url, path, 503, {"application/json"})
        payload = json.loads(body)
        require(isinstance(payload, dict) and isinstance(payload.get("error"), dict),
                f"{path}: missing error object")
        error = payload["error"]
        require(error.get("code") == "API_NOT_AVAILABLE", f"{path}: unexpected error code")
        require(isinstance(error.get("message"), str) and error["message"].strip(),
                f"{path}: missing error message")
        require(error.get("details") == [], f"{path}: expected an empty details array")

    for path in ("/assets/nonexistent.js", "/.env", "/.env.local", "/src/.env"):
        fetch(base_url, path, 404)
    print("Frontend HTTP checks passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Frontend address, e.g. http://127.0.0.1:8080")
    parser.add_argument("--api-ready", action="store_true", help="Expect a running API and database")
    args = parser.parse_args()
    address = urlsplit(args.url)
    if address.scheme not in {"http", "https"} or not address.netloc or address.path not in {"", "/"} or address.query or address.fragment:
        parser.error("Provide an HTTP(S) origin without a path, query or fragment")
    try:
        check(args.url.rstrip("/"), api_ready=args.api_ready)
    except (RuntimeError, URLError, OSError, ValueError) as error:
        print(f"Frontend check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
