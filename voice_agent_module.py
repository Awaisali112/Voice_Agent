"""
voice-agent.py
==============
LiveKit restaurant reservation voice agent.
Every confirmed booking is:
  1. Saved as its own PDF receipt  →  reservations/RES-<CODE>.pdf
  2. Appended to a running log     →  reservations/reservations_log.pdf
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, date
from dotenv import load_dotenv

from livekit import agents, rtc
from livekit.agents import AgentServer, AgentSession, Agent, room_io, llm
from livekit.plugins import noise_cancellation, silero, deepgram
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.plugins import openai

from edge_tts_plugin import EdgeTTS

# PDF libraries
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from pypdf import PdfReader, PdfWriter

load_dotenv(".env")

MENU_SUMMARY = """
MENU HIGHLIGHTS:
Starters: Seekh Kebab $14, Chicken Tikka $13, Samosa Chaat $11, Dahi Bhalle $10
Mains: Nihari $28, Karahi Gosht $26, Butter Chicken $24, Dal Makhani $18, Biryani $27, Palak Paneer $19
Breads: Tandoori Naan $4, Garlic Naan $5, Paratha $4, Peshwari Naan $6
Desserts: Gulab Jamun $8, Kheer $8, Gajar Halwa $9
Drinks: Mango Lassi $7, Rose Sharbat $6, Masala Chai $5
"""

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("restaurant-agent")


# ---------------------------------------------------------------------------
# Restaurant configuration
# ---------------------------------------------------------------------------

RESTAURANT_NAME  = "Lahore Hotel And Restaurant"
RESTAURANT_ADDR  = "Mall Road, Lahore, Punjab, Pakistan"
RESTAURANT_PHONE = "+92 42 3636 0000"
OPENING_HOUR     = 7       # 7 AM (Breakfast)
CLOSING_HOUR     = 23      # 11 PM (end of Dinner)
MAX_PARTY_SIZE   = 20
MIN_PARTY_SIZE   = 1
ADVANCE_DAYS     = 60

RESERVATIONS_DIR = "reservations"
LOG_PDF_PATH     = os.path.join(RESERVATIONS_DIR, "reservations_log.pdf")


# ---------------------------------------------------------------------------
# In-memory reservation store
# ---------------------------------------------------------------------------

reservations: dict[str, dict] = {}
pending_confirmations: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def _ensure_dir() -> None:
    os.makedirs(RESERVATIONS_DIR, exist_ok=True)


def _build_receipt_pdf(res: dict, path: str) -> None:
    """Generate a styled single-page reservation receipt PDF."""
    _ensure_dir()

    doc = SimpleDocTemplate(
        path,
        pagesize=A4,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
    )

    styles = getSampleStyleSheet()

    gold  = colors.HexColor("#B8955A")
    dark  = colors.HexColor("#2E2720")
    muted = colors.HexColor("#7A7068")
    cream = colors.HexColor("#FAF7F2")

    title_style = ParagraphStyle(
        "RestTitle",
        parent=styles["Title"],
        fontSize=26,
        leading=32,
        textColor=dark,
        fontName="Times-BoldItalic",
        alignment=1,
    )
    sub_style = ParagraphStyle(
        "RestSub",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=muted,
        alignment=1,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        textColor=muted,
        fontName="Helvetica",
    )
    value_style = ParagraphStyle(
        "Value",
        parent=styles["Normal"],
        fontSize=11,
        leading=15,
        textColor=dark,
        fontName="Helvetica-Bold",
    )
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=muted,
        alignment=1,
    )
    code_style = ParagraphStyle(
        "Code",
        parent=styles["Normal"],
        fontSize=22,
        leading=28,
        textColor=gold,
        fontName="Courier-Bold",
        alignment=1,
    )

    story = []

    # ── Header ──
    story.append(Paragraph(RESTAURANT_NAME, title_style))
    story.append(Spacer(1, 4))
    story.append(Paragraph(RESTAURANT_ADDR, sub_style))
    story.append(Paragraph(RESTAURANT_PHONE, sub_style))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=gold))
    story.append(Spacer(1, 6))
    story.append(Paragraph("RESERVATION CONFIRMATION", sub_style))
    story.append(Spacer(1, 18))

    # ── Confirmation code ──
    story.append(Paragraph(res["confirmation_code"], code_style))
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#E0D8CA")))
    story.append(Spacer(1, 20))

    # ── Details table ──
    rows = [
        ("GUEST NAME",       res["guest_name"]),
        ("DATE",             res["date_str"]),
        ("TIME",             res["time_str"]),
        ("PARTY SIZE",       f"{res['party_size']} guest{'s' if res['party_size'] > 1 else ''}"),
        ("SPECIAL REQUESTS", res["special_requests"] or "None"),
        ("BOOKED AT",        datetime.fromisoformat(res["created_at"]).strftime("%d %b %Y, %I:%M %p")),
    ]

    table_data = [
        [Paragraph(label, label_style), Paragraph(value, value_style)]
        for label, value in rows
    ]

    tbl = Table(table_data, colWidths=[4.5 * cm, 11 * cm])
    tbl.setStyle(TableStyle([
        ("VALIGN",         (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [cream, colors.white]),
        ("TOPPADDING",     (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING",  (0, 0), (-1, -1), 8),
        ("LEFTPADDING",    (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",   (0, 0), (-1, -1), 10),
        ("LINEBELOW",      (0, -1), (-1, -1), 0.5, colors.HexColor("#E0D8CA")),
    ]))
    story.append(tbl)

    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=1, color=gold))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Thank you for choosing Lahore Hotel And Restaurant. We look forward to welcoming you.",
        footer_style,
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        "Please quote your confirmation code if you need to make any changes.",
        footer_style,
    ))

    doc.build(story)
    logger.info(f"[PDF] Receipt saved → {path}")


def _append_to_log(receipt_path: str) -> None:
    """Append the receipt to the running reservations_log.pdf."""
    _ensure_dir()
    writer = PdfWriter()

    if os.path.exists(LOG_PDF_PATH):
        for page in PdfReader(LOG_PDF_PATH).pages:
            writer.add_page(page)

    for page in PdfReader(receipt_path).pages:
        writer.add_page(page)

    with open(LOG_PDF_PATH, "wb") as f:
        writer.write(f)

    logger.info(f"[PDF] Log updated → {LOG_PDF_PATH}  ({len(writer.pages)} total pages)")


def _save_reservation_pdf(res: dict) -> str:
    """Create receipt PDF and append to log. Returns receipt path."""
    receipt_path = os.path.join(RESERVATIONS_DIR, f"RES-{res['confirmation_code']}.pdf")
    _build_receipt_pdf(res, receipt_path)
    _append_to_log(receipt_path)
    return receipt_path


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_time(time_str: str) -> int | None:
    """Parse a time string into an hour (0-23). Handles many spoken formats."""
    s = time_str.strip().upper()

    # Try standard strptime formats first
    for fmt in ("%I:%M %p", "%I %p", "%I:%M%p", "%I%p", "%H:%M", "%H:%M:%S", "%H"):
        try:
            return datetime.strptime(s, fmt).hour
        except ValueError:
            continue

    # Handle formats like "7PM", "7 PM", "19:00", "7:30PM"
    import re
    m = re.match(r'^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$', s)
    if m:
        hour = int(m.group(1))
        meridiem = m.group(3)
        if meridiem == 'PM' and hour != 12:
            hour += 12
        elif meridiem == 'AM' and hour == 12:
            hour = 0
        if 0 <= hour <= 23:
            return hour

    return None


def _validate_booking(date_str: str, time_str: str, party_size: int) -> str | None:
    parsed_date = _parse_date(date_str)
    if not parsed_date:
        return f"I couldn't understand the date '{date_str}'. Try 'June 15 2025' or '2025-06-15'."

    today = date.today()
    if parsed_date < today:
        return "That date is in the past. Please choose a future date."
    if (parsed_date - today).days > ADVANCE_DAYS:
        return f"We only accept reservations up to {ADVANCE_DAYS} days in advance."

    parsed_hour = _parse_time(time_str)
    if parsed_hour is None:
        return f"I couldn't understand the time '{time_str}'. Try '7 PM' or '7:30 PM'."
    if not (OPENING_HOUR <= parsed_hour <= CLOSING_HOUR):
        return (
            f"Our dinner service runs from {OPENING_HOUR % 12 or 12} PM "
            f"to {CLOSING_HOUR % 12 or 12} PM. Please choose a time in that range."
        )

    if not (MIN_PARTY_SIZE <= party_size <= MAX_PARTY_SIZE):
        return f"We accommodate parties of {MIN_PARTY_SIZE} to {MAX_PARTY_SIZE} guests."

    return None


def _generate_code() -> str:
    return uuid.uuid4().hex[:6].upper()


def _format_reservation(res: dict) -> str:
    req = f" Special requests: {res['special_requests']}." if res.get("special_requests") else ""
    return (
        f"Reservation {res['confirmation_code']}: "
        f"{res['guest_name']}, party of {res['party_size']}, "
        f"on {res['date_str']} at {res['time_str']}.{req}"
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class RestaurantAgent(Agent):
    """Voice reservation agent for Johny & Jugnu."""

    def __init__(self) -> None:
        super().__init__(
            instructions=f"""
You are Parveen, the reservations host at {RESTAURANT_NAME}, a warm and upscale Pakistani restaurant.

Your job is to help guests make, look up, and cancel dinner reservations, and answer menu questions.

RESTAURANT DETAILS:
- Name: {RESTAURANT_NAME}
- Address: {RESTAURANT_ADDR}
- Phone: {RESTAURANT_PHONE}
- Dining hours: Breakfast 7:00 AM–11:00 AM, Lunch 12:00 PM–4:00 PM, Dinner 6:00 PM–11:00 PM, 7 days a week
- Max party size: {MAX_PARTY_SIZE}

{MENU_SUMMARY}

RULES:
1. To make a reservation you need: guest name, date, time, and party size.
   Special requests (dietary needs, celebrations, seating preferences) are optional.
2. Always collect all required information before calling make_reservation.
3. Before confirming a booking or cancellation, read back the details and ask
   the guest to confirm with "yes" or "no", then call confirm_action.
4. To look up a reservation, ask for the guest's last name or confirmation code.
5. Keep all spoken responses concise and warm — no bullet points or markdown.
6. When asking for time, ask the guest to say it like "7 PM" or "half past 7".
7. If asked about the menu, describe dishes warmly and briefly.
""",
        )

    # -----------------------------------------------------------------------
    # TOOL: check_availability
    # -----------------------------------------------------------------------
    @llm.function_tool
    async def check_availability(self, date_str: str, party_size: int) -> str:
        """Check whether a date is valid and within the booking window.

        Args:
            date_str: Requested date (e.g. 'June 15 2025' or '2025-06-15').
            party_size: Number of guests.
        """
        parsed_date = _parse_date(date_str)
        if not parsed_date:
            return f"Could not parse date '{date_str}'."

        today = date.today()
        if parsed_date < today:
            return "That date is in the past."
        if (parsed_date - today).days > ADVANCE_DAYS:
            return f"We only book up to {ADVANCE_DAYS} days ahead."
        if not (MIN_PARTY_SIZE <= party_size <= MAX_PARTY_SIZE):
            return f"Party size must be between {MIN_PARTY_SIZE} and {MAX_PARTY_SIZE}."

        return (
            f"{parsed_date.strftime('%A, %B %d')} is available. "
            f"Dinner runs 5 PM to 10 PM. What time works for a party of {party_size}?"
        )

    # -----------------------------------------------------------------------
    # TOOL: make_reservation  ← requires confirmation
    # -----------------------------------------------------------------------
    @llm.function_tool
    async def make_reservation(
        self,
        guest_name: str,
        date_str: str,
        time_str: str,
        party_size: int,
        special_requests: str = "",
    ) -> str:
        """Stage a new reservation for guest confirmation. Always confirm before calling.

        Args:
            guest_name: Full name of the guest.
            date_str: Reservation date (e.g. 'June 15 2025').
            time_str: Reservation time (e.g. '7 PM' or '7:30 PM').
            party_size: Number of guests.
            special_requests: Optional dietary needs, celebrations, or seating preferences.
        """
        error = _validate_booking(date_str, time_str, party_size)
        if error:
            return error

        action_id = f"book_{uuid.uuid4().hex[:8]}"
        pending_confirmations[action_id] = {
            "action": "book",
            "args": {
                "guest_name":       guest_name,
                "date_str":         date_str,
                "time_str":         time_str,
                "party_size":       party_size,
                "special_requests": special_requests,
            },
        }
        req_line = f" Special requests: {special_requests}." if special_requests else ""
        return (
            f"PENDING_CONFIRMATION:{action_id} — "
            f"To confirm: a table for {party_size} under {guest_name} "
            f"on {date_str} at {time_str}.{req_line} "
            f"Shall I go ahead and book this? Please say yes or no."
        )

    # -----------------------------------------------------------------------
    # TOOL: get_reservation
    # -----------------------------------------------------------------------
    @llm.function_tool
    async def get_reservation(
        self,
        confirmation_code: str = "",
        guest_last_name: str = "",
    ) -> str:
        """Look up a reservation by confirmation code or guest last name.

        Args:
            confirmation_code: The 6-character code given at booking time.
            guest_last_name: Guest's last name, used if no code is available.
        """
        if confirmation_code:
            code = confirmation_code.strip().upper()
            res = reservations.get(code)
            if res:
                return _format_reservation(res)
            return f"No reservation found for code {code}."

        if guest_last_name:
            last = guest_last_name.strip().lower()
            matches = [
                r for r in reservations.values()
                if r["guest_name"].split()[-1].lower() == last
            ]
            if not matches:
                return f"No reservation found under '{guest_last_name}'."
            if len(matches) == 1:
                return _format_reservation(matches[0])
            summary = "; ".join(
                f"{r['confirmation_code']} on {r['date_str']} at {r['time_str']}"
                for r in matches
            )
            return f"Found {len(matches)} reservations for {guest_last_name}: {summary}. Which code is correct?"

        return "Please provide a confirmation code or last name."

    # -----------------------------------------------------------------------
    # TOOL: cancel_reservation  ← requires confirmation
    # -----------------------------------------------------------------------
    @llm.function_tool
    async def cancel_reservation(self, confirmation_code: str) -> str:
        """Stage a cancellation for guest confirmation. Always confirm before calling.

        Args:
            confirmation_code: The 6-character confirmation code.
        """
        code = confirmation_code.strip().upper()
        res = reservations.get(code)
        if not res:
            return f"No reservation found for code {code}."

        action_id = f"cancel_{uuid.uuid4().hex[:8]}"
        pending_confirmations[action_id] = {
            "action": "cancel",
            "args": {"confirmation_code": code},
        }
        return (
            f"PENDING_CONFIRMATION:{action_id} — "
            f"I found: {_format_reservation(res)} "
            f"Are you sure you want to cancel? Please say yes or no."
        )

    # -----------------------------------------------------------------------
    # TOOL: confirm_action  ← resolves pending confirmations
    # -----------------------------------------------------------------------
    @llm.function_tool
    async def confirm_action(self, action_id: str, confirmed: bool) -> str:
        """Execute or cancel a pending booking or cancellation after the guest confirms.

        Args:
            action_id: The ID returned by the pending action tool.
            confirmed: True if the guest said yes, False if no.
        """
        entry = pending_confirmations.pop(action_id, None)
        if not entry:
            return "No pending action found with that ID."

        if not confirmed:
            label = "booking" if entry["action"] == "book" else "cancellation"
            return f"No problem, I've cancelled that {label} request. Is there anything else I can help you with?"

        action = entry["action"]
        args   = entry["args"]

        if action == "book":
            code = _generate_code()
            res = {
                "confirmation_code": code,
                "guest_name":        args["guest_name"],
                "date_str":          args["date_str"],
                "time_str":          args["time_str"],
                "party_size":        args["party_size"],
                "special_requests":  args.get("special_requests", ""),
                "created_at":        datetime.now().isoformat(),
            }
            reservations[code] = res

            # ── Save to PDF ──
            try:
                _save_reservation_pdf(res)
                pdf_note = f" A PDF receipt has been saved as RES-{code}.pdf."
            except Exception as e:
                logger.error(f"[PDF] Failed to save receipt: {e}")
                pdf_note = ""

            req_line = f" We've noted: {args['special_requests']}." if args.get("special_requests") else ""
            return (
                f"Your reservation is confirmed! Confirmation code: {code}. "
                f"We look forward to welcoming {args['guest_name']} on {args['date_str']} "
                f"at {args['time_str']} for {args['party_size']}.{req_line}{pdf_note} "
                f"Is there anything else I can help you with?"
            )

        if action == "cancel":
            code = args["confirmation_code"]
            res  = reservations.pop(code, None)
            if res:
                logger.info(f"[CANCELLED] {code} — {res}")
                return (
                    f"Done, the reservation for {res['guest_name']} on {res['date_str']} "
                    f"at {res['time_str']} has been cancelled. We hope to see you another time."
                )
            return "That reservation had already been removed."

        return "Action executed."


# ---------------------------------------------------------------------------
# RTC session entry point
# ---------------------------------------------------------------------------

server = AgentServer()


@server.rtc_session()
async def my_agent(ctx: agents.JobContext):

    agent = RestaurantAgent()

    session = AgentSession(
        stt=deepgram.STT(model="nova-2"),
        llm=openai.LLM.with_ollama(
            model="gemini-3-flash-preview:cloud",
            base_url="http://localhost:11434/v1",
        ),
        tts=EdgeTTS(voice="en-US-AriaNeural"),
        vad=silero.VAD.load(),
        turn_detection=MultilingualModel(),
    )

    await session.start(
        room=ctx.room,
        agent=agent,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: (
                    noise_cancellation.BVCTelephony()
                    if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                    else noise_cancellation.BVC()
                ),
            ),
        ),
    )

    await session.generate_reply(
        user_input=(
            f"Greet the guest warmly as Parveen, the reservations host at {RESTAURANT_NAME}. "
            "Tell them you can help make, look up, or cancel a reservation. "
            "Keep it to two friendly sentences."
        )
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agents.cli.run_app(server)