"""
chat_server.py
==============
Simple HTTP endpoint for text chat with Sofia.
Run alongside voice-agent.py and token_server.py:
    python chat_server.py
"""

import os
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

load_dotenv(".env")

PORT = int(os.environ.get("CHAT_SERVER_PORT", 8081))

SYSTEM_PROMPT = """You are Parveen, the elegant Digital Maître D' for 'Lahore Hotel And Restaurant', an upscale Pakistani restaurant.
Your tone is poised, professional, and warm.
You assist guests with reservations, menu inquiries, and special requests.
Keep responses concise and helpful.
If a guest wants to book, ask for their name, preferred date/time, and party size.
The restaurant is open daily. Breakfast: 7:00 AM–11:00 AM, Lunch: 12:00 PM–4:00 PM, Dinner: 6:00 PM–11:00 PM.
Location: Mall Road, Lahore, Punjab, Pakistan.

MENU HIGHLIGHTS:
Starters: Seekh Kebab $14, Chicken Tikka $13, Samosa Chaat $11, Dahi Bhalle $10
Mains: Nihari $28, Karahi Gosht $26, Butter Chicken $24, Dal Makhani $18, Biryani $27, Palak Paneer $19
Breads: Tandoori Naan $4, Garlic Naan $5, Paratha $4, Peshwari Naan $6
Desserts: Gulab Jamun $8, Kheer $8, Gajar Halwa $9
Drinks: Mango Lassi $7, Rose Sharbat $6, Masala Chai $5"""


def _get_reply(prompt: str, history: list) -> str:
    """Call Ollama (or fallback to a simple echo) to get Sofia's reply."""
    try:
        import urllib.request
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for h in history:
            messages.append(h)
        messages.append({"role": "user", "content": prompt})

        payload = json.dumps({
            "model": "gemini-3-flash-preview:cloud",
            "messages": messages,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            "http://localhost:11434/v1/chat/completions",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"I'm sorry, I'm having trouble connecting right now. Please call us at (555) 820-3300."


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, code: int, data: dict):
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

    def do_POST(self):
        if self.path != "/chat":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        prompt = body.get("prompt", "").strip()
        history = body.get("history", [])

        if not prompt:
            self._send_json(400, {"error": "prompt required"})
            return

        reply = _get_reply(prompt, history)
        self._send_json(200, {"text": reply})


if __name__ == "__main__":
    print(f"Chat server listening on http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
