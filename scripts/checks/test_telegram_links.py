"""URL regressions; standard library only, no credentials or network calls."""

import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "telegram_links", Path(__file__).resolve().parents[2] / "telegram/links.py"
)
links = importlib.util.module_from_spec(spec)
spec.loader.exec_module(links)


class TelegramLinksTest(unittest.TestCase):
    def test_local_addresses_remain_readable_but_never_become_url_buttons(self):
        for value in (
            "http://localhost:8080",
            "http://LOCALHOST.:8080",
            "https://panel.localhost",
            "http://127.0.0.1:8080/#payments",
            "http://0.0.0.0:8080",
            "http://[::1]:8080",
            "http://backend:8000",
        ):
            with self.subTest(value=value):
                self.assertEqual(links.http_url(value), value)
                self.assertIsNone(links.keyboard_url(value))

    def test_network_urls_survive_and_invalid_addresses_are_rejected(self):
        for value in (
            "https://panel.example.org/app?tab=payments",
            "http://192.168.1.10:8080",
            "https://[2001:db8::1]/app",
        ):
            with self.subTest(value=value):
                self.assertEqual(links.keyboard_url(value), value)
        for value in (
            None,
            "",
            "javascript:alert(1)",
            "/payments",
            "http://",
            "https://user:pass@example.org",
            "https://example.org:99999",
            "https://example.org:0",
            "https://example.org/a b",
            "https://example.org/\x00",
        ):
            with self.subTest(value=value):
                self.assertIsNone(links.http_url(value))
                self.assertIsNone(links.keyboard_url(value))


if __name__ == "__main__":
    unittest.main()
