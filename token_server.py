"""
token_server.py
===============
Lightweight HTTP server that issues LiveKit access tokens for the frontend.
Run alongside voice-agent.py:
    python token_server.py
"""

import os
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import urllib.parse
from livekit.api import AccessToken, VideoGrants

load_dotenv(".env")

LIVEKIT_API_KEY    = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
LIVEKIT_URL        = os.environ["LIVEKIT_URL"]
PORT               = int(os.environ.get("TOKEN_SERVER_PORT", 8080))
ROOM_NAME          = os.environ.get("LIVEKIT_ROOM", "restaurant-lobby")


def _make_token(identity: str) -> str:
    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(identity)
        .with_grants(VideoGrants(room_join=True, room=ROOM_NAME))
    )
    return token.to_jwt()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # silence default access log
        pass

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/token":
            self._send_json(404, {"error": "not found"})
            return

        params = urllib.parse.parse_qs(parsed.query)
        identity = params.get("identity", ["guest"])[0]

        try:
            jwt = _make_token(identity)
            self._send_json(200, {
                "token": jwt,
                "url": LIVEKIT_URL,
                "room": ROOM_NAME,
            })
        except Exception as e:
            self._send_json(500, {"error": str(e)})


if __name__ == "__main__":
    print(f"Token server listening on http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
