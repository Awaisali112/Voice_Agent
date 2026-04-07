"""
reservations_server.py
======================
Exposes the in-memory reservation store over HTTP so the frontend can display them.
Shares the same `reservations` dict as voice_agent_module.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv
import os

load_dotenv(".env")

PORT = int(os.environ.get("RESERVATIONS_SERVER_PORT", 8082))

# Imported lazily so voice_agent_module is only loaded once
_reservations_ref = None

def set_reservations(ref: dict):
    global _reservations_ref
    _reservations_ref = ref


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path != "/reservations":
            self._send_json(404, {"error": "not found"})
            return
        data = list(_reservations_ref.values()) if _reservations_ref else []
        # Sort newest first
        data.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        self._send_json(200, data)

    def do_DELETE(self):
        if not self.path.startswith("/reservations/"):
            self._send_json(404, {"error": "not found"})
            return
        code = self.path.split("/reservations/")[-1].strip().upper()
        if _reservations_ref and code in _reservations_ref:
            del _reservations_ref[code]
            self._send_json(200, {"deleted": code})
        else:
            self._send_json(404, {"error": f"No reservation {code}"})


if __name__ == "__main__":
    # Standalone mode — import the shared store
    from voice_agent_module import reservations
    set_reservations(reservations)
    print(f"Reservations server listening on http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
