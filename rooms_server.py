"""
rooms_server.py
===============
HTTP server for room bookings.
GET  /room-bookings          — list all bookings
POST /room-bookings          — create a booking
DELETE /room-bookings/<code> — cancel a booking
"""

import json
import uuid
import os
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime
from dotenv import load_dotenv

load_dotenv(".env", override=False)  # don't override if already loaded by start.py

PORT = int(os.environ.get("ROOMS_SERVER_PORT", 8083))

# In-memory store
room_bookings: dict[str, dict] = {}

N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "")


def _fire_webhook(data: dict):
    """Send booking data to n8n webhook in a background thread."""
    url = os.environ.get("N8N_WEBHOOK_URL", N8N_WEBHOOK_URL)
    if not url:
        print("[n8n] N8N_WEBHOOK_URL not set, skipping webhook")
        return

    def _send():
        try:
            payload = json.dumps(data).encode()
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            print(f"[n8n] webhook sent → {resp.status}")
        except Exception as e:
            print(f"[n8n] webhook failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


def _cors_headers(handler):
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        _cors_headers(self)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        _cors_headers(self)
        self.end_headers()

    def do_GET(self):
        if self.path != "/room-bookings":
            self._send_json(404, {"error": "not found"})
            return
        data = sorted(room_bookings.values(), key=lambda r: r["created_at"], reverse=True)
        self._send_json(200, data)

    def do_POST(self):
        if self.path != "/room-bookings":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))

        required = ["guest_name", "room_id", "room_name", "check_in", "check_out", "guests", "price_per_night"]
        for field in required:
            if not body.get(field):
                self._send_json(400, {"error": f"Missing field: {field}"})
                return

        code = uuid.uuid4().hex[:6].upper()
        booking = {
            "confirmation_code": code,
            "guest_name":        body["guest_name"],
            "room_id":           body["room_id"],
            "room_name":         body["room_name"],
            "room_type":         body.get("room_type", ""),
            "check_in":          body["check_in"],
            "check_out":         body["check_out"],
            "guests":            body["guests"],
            "price_per_night":   body["price_per_night"],
            "special_requests":  body.get("special_requests", ""),
            "created_at":        datetime.now().isoformat(),
        }
        room_bookings[code] = booking
        _fire_webhook(booking)
        self._send_json(201, booking)

    def do_DELETE(self):
        if not self.path.startswith("/room-bookings/"):
            self._send_json(404, {"error": "not found"})
            return
        code = self.path.split("/room-bookings/")[-1].strip().upper()
        if code in room_bookings:
            del room_bookings[code]
            self._send_json(200, {"deleted": code})
        else:
            self._send_json(404, {"error": f"No booking {code}"})


if __name__ == "__main__":
    print(f"Rooms server listening on http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
