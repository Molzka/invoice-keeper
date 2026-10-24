"""Offline transport fixture; never imported by the production application."""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs


def serve():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, payload, status=200):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            self.respond(
                requests if self.path == "/requests" else {},
                200 if self.path == "/requests" else 404,
            )

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            fields = parse_qs(body.decode())
            requests.append({"method": self.path.rsplit("/", 1)[-1], "fields": fields})
            if (
                not self.path.endswith("/sendMessage")
                or self.headers.get_content_type() != "application/x-www-form-urlencoded"
            ):
                self.respond({"ok": False, "description": "Unexpected request"}, 400)
                return
            self.respond(
                {
                    "ok": True,
                    "result": {
                        "message_id": len(requests),
                        "date": int(time.time()),
                        "chat": {"id": int(fields["chat_id"][0]), "type": "supergroup"},
                        "text": fields["text"][0],
                    },
                }
            )

    HTTPServer(("0.0.0.0", 8081), Handler).serve_forever()


def worker():
    from aiogram import Bot
    from aiogram.client.session.aiohttp import AiohttpSession
    from aiogram.client.telegram import TelegramAPIServer
    from app.delivery import cli

    class LocalBot(Bot):
        def __init__(self, token):
            super().__init__(
                token,
                session=AiohttpSession(
                    api=TelegramAPIServer.from_base("http://telegram-stub:8081"),
                ),
            )

    cli.Bot = LocalBot
    sys.argv = ["app.delivery.cli", *sys.argv[2:]]
    cli.main()


if __name__ == "__main__":
    {"stub": serve, "worker": worker}[sys.argv[1]]()
