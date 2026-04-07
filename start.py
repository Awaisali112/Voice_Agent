"""
start.py
========
Starts all backend services in one terminal:
  - Token server        (port 8080)
  - Chat server         (port 8081)
  - Reservations server (port 8082)
  - Voice agent         (LiveKit)

Usage:
    python start.py dev
"""

import sys
import threading
from http.server import HTTPServer
from dotenv import load_dotenv

load_dotenv(".env")

# Import voice_agent_module ONCE here so all threads share the same instance
import voice_agent_module

# Wire the shared reservations dict into the reservations server
from reservations_server import set_reservations
set_reservations(voice_agent_module.reservations)


# ── Token server ──────────────────────────────────────────────────────────────
def run_token_server():
    from token_server import Handler, PORT
    print(f"[token]        listening on http://localhost:{PORT}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


# ── Chat server ───────────────────────────────────────────────────────────────
def run_chat_server():
    from chat_server import Handler as ChatHandler, PORT as CHAT_PORT
    print(f"[chat]         listening on http://localhost:{CHAT_PORT}")
    HTTPServer(("0.0.0.0", CHAT_PORT), ChatHandler).serve_forever()


# ── Reservations server ───────────────────────────────────────────────────────
def run_reservations_server():
    from reservations_server import Handler as ResHandler, PORT as RES_PORT
    print(f"[reservations] listening on http://localhost:{RES_PORT}")
    HTTPServer(("0.0.0.0", RES_PORT), ResHandler).serve_forever()


# ── Rooms server ──────────────────────────────────────────────────────────────
def run_rooms_server():
    from rooms_server import Handler as RoomsHandler, PORT as ROOMS_PORT
    print(f"[rooms]        listening on http://localhost:{ROOMS_PORT}")
    HTTPServer(("0.0.0.0", ROOMS_PORT), RoomsHandler).serve_forever()


# ── Voice agent ───────────────────────────────────────────────────────────────
def run_voice_agent():
    from livekit import agents
    print("[agent]        starting LiveKit voice agent...")
    agents.cli.run_app(voice_agent_module.server)


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    threading.Thread(target=run_token_server,       daemon=True).start()
    threading.Thread(target=run_chat_server,         daemon=True).start()
    threading.Thread(target=run_reservations_server, daemon=True).start()
    threading.Thread(target=run_rooms_server,        daemon=True).start()

    # Voice agent runs in the main thread (it owns the event loop)
    run_voice_agent()
