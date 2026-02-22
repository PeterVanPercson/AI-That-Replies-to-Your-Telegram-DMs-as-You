#!/usr/bin/env python3
from __future__ import annotations

"""
╔══════════════════════════════════════════════════════════════╗
║  LOCAL AI TELEGRAM DM AGENT v2.0                            ║
║                                                              ║
║  Your AI twin — replies from YOUR account, 100% local.      ║
║                                                              ║
║  Features:                                                   ║
║  · Voice cloning from your real messages                    ║
║  · Per-user personality (casual / flirty / professional)    ║
║  · Risk detection + approval queue                          ║
║  · Sticker reactions                                        ║
║  · Media-aware (photos, voice, files, stickers, location)   ║
║  · Language matching (replies in their language)            ║
║  · Control panel via Saved Messages                         ║
║  · Message batching (waits for multi-message bursts)        ║
║  · Auto-reconnect on disconnect                             ║
║  · Graceful shutdown with state persistence                 ║
║  · Stats tracking                                            ║
║                                                              ║
║  Stack: Telethon + httpx + mlx-openai-server + Qwen3-8B    ║
║  Zero cloud AI. Prompts never leave your Mac.               ║
╚══════════════════════════════════════════════════════════════╝
"""

import os
import re
import json
import time
import random
import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import Counter
from typing import Any

import httpx
from dotenv import load_dotenv
from telethon import TelegramClient, events, errors
from telethon.tl.types import (
    User,
    MessageMediaPhoto,
    MessageMediaDocument,
    MessageMediaGeo,
    MessageMediaContact,
    MessageMediaWebPage,
)
from telethon.tl.functions.messages import GetStickerSetRequest
from telethon.tl.types import InputStickerSetShortName

VERSION = "2.0.0"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UTILITY — must be defined before config parsing
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def normalize_mlx_url(raw: str) -> str:
    raw = (raw or "").strip().rstrip("/")
    if not raw:
        return "http://127.0.0.1:8080"
    if raw.endswith("/v1"):
        raw = raw[:-3]
    return raw


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    return raw.strip().lower() in {"1", "true", "yes", "on"} if raw else default


def env_int(name: str, default: int) -> int:
    try:
        return int((os.environ.get(name) or "").strip())
    except (ValueError, AttributeError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or "").strip())
    except (ValueError, AttributeError):
        return default


def _content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return " ".join(p for p in (_content_to_text(i) for i in value) if p).strip()
    if isinstance(value, dict):
        for key in ("text", "content", "value", "output_text"):
            t = _content_to_text(value.get(key))
            if t:
                return t
    return ""


def extract_assistant_content(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return None
    root = _content_to_text(payload.get("output_text"))
    if root:
        return root
    for c in (payload.get("choices") or [])[:1]:
        if not c:
            continue
        for loc in [c.get("message", {}), c, c.get("delta", {})]:
            t = _content_to_text(loc.get("content") or loc.get("text"))
            if t:
                return t
    return None


def utcnow() -> datetime:
    """Timezone-aware UTC now (avoids deprecated datetime.utcnow)."""
    return datetime.now(timezone.utc)


def compact(text: str, limit: int = 350) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(ENV_PATH)

# Telegram API
raw_api_id = (os.environ.get("TELEGRAM_API_ID") or "").strip()
if not raw_api_id.isdigit():
    raise SystemExit(
        "Invalid TELEGRAM_API_ID — must be a number from https://my.telegram.org"
    )
API_ID = int(raw_api_id)
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")

# MLX
MLX_URL = normalize_mlx_url(os.environ.get("MLX_SERVER_URL", "http://127.0.0.1:8080"))
MLX_MODEL = os.environ.get("MLX_MODEL", "default")

# Session
SESSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "my_telegram")

# Reply scope
REPLY_MODE = os.environ.get("REPLY_MODE", "all")

_WHITELIST_SET: set = set()
for _item in (os.environ.get("WHITELIST") or "").split(","):
    _item = _item.strip().lstrip("@")
    if _item.isdigit():
        _WHITELIST_SET.add(int(_item))
    elif _item:
        _WHITELIST_SET.add(_item.lower())

_BLACKLIST_SET: set = set()
for _item in (os.environ.get("BLACKLIST") or "").split(","):
    _item = _item.strip().lstrip("@")
    if _item.isdigit():
        _BLACKLIST_SET.add(int(_item))
    elif _item:
        _BLACKLIST_SET.add(_item.lower())

# Timing
COOLDOWN_SECONDS = env_int("COOLDOWN_SECONDS", 8)
AWAY_AFTER_SECONDS = env_int("AWAY_AFTER_SECONDS", 0)
MAX_INPUT_LENGTH = env_int("MAX_INPUT_LENGTH", 2000)
IGNORE_OLDER_THAN = env_int("IGNORE_OLDER_THAN", 120)
MAX_HISTORY = env_int("MAX_HISTORY", 12)

# BUG FIX #1: Original was 0-0.15s — instant reply looks robotic, Telegram can flag.
# Real humans take 2-5 seconds to read + type a short reply.
TYPING_DELAY_MIN = env_float("TYPING_DELAY_MIN", 1.5)
TYPING_DELAY_MAX = env_float("TYPING_DELAY_MAX", 4.5)

# BUG FIX #2: NEW — batch window. When someone sends 3 messages in a row ("hey" / "you there?" / "got a question"),
# the agent waits this many seconds after last message before replying — so it sees all 3 at once.
BATCH_WINDOW_SECONDS = env_float("BATCH_WINDOW_SECONDS", 3.0)

# Duplicate suppression
DUPLICATE_WINDOW_SECONDS = env_int("DUPLICATE_WINDOW_SECONDS", 12)
SHORT_PING_WINDOW_SECONDS = env_int("SHORT_PING_WINDOW_SECONDS", 8)
SHORT_PING_MAX_LEN = env_int("SHORT_PING_MAX_LEN", 4)

# Fallbacks
EMPTY_REPLY_FALLBACK = os.environ.get(
    "EMPTY_REPLY_FALLBACK",
    "Hey, got your message. Let me check and get back to you shortly.",
).strip()
PERSONAL_FALLBACK = os.environ.get(
    "PERSONAL_FALLBACK",
    "I need to check on that and get back to you."
).strip()

# Voice profile
VOICE_PROFILE_ENABLED = env_bool("VOICE_PROFILE_ENABLED", True)
VOICE_PROFILE_PATH = Path(os.environ.get(
    "VOICE_PROFILE_PATH",
    str(Path(os.path.dirname(os.path.abspath(__file__))) / "voice_profile.json"),
))
VOICE_PROFILE_REFRESH_HOURS = env_int("VOICE_PROFILE_REFRESH_HOURS", 24)
VOICE_PROFILE_MAX_DIALOGS = env_int("VOICE_PROFILE_MAX_DIALOGS", 40)
VOICE_PROFILE_PER_DIALOG_LIMIT = env_int("VOICE_PROFILE_PER_DIALOG_LIMIT", 25)
VOICE_PROFILE_MIN_MESSAGES = env_int("VOICE_PROFILE_MIN_MESSAGES", 30)
VOICE_PROFILE_SYNTHESIZE_GUIDE = env_bool("VOICE_PROFILE_SYNTHESIZE_GUIDE", True)
VOICE_PROFILE_GUIDE_SAMPLE_LIMIT = env_int("VOICE_PROFILE_GUIDE_SAMPLE_LIMIT", 120)

# Bootstrap & Polish
BOOTSTRAP_HISTORY_ENABLED = env_bool("BOOTSTRAP_HISTORY_ENABLED", True)
BOOTSTRAP_HISTORY_LIMIT = env_int("BOOTSTRAP_HISTORY_LIMIT", 16)
POLISH_REPLY_ENABLED = env_bool("POLISH_REPLY_ENABLED", True)

# Approval system
APPROVAL_MODE = (os.environ.get("APPROVAL_MODE") or "risky").strip().lower()
REPORT_TO_SELF = env_bool("REPORT_TO_SELF", True)
CONTROL_CHAT_ID_RAW = (os.environ.get("CONTROL_CHAT_ID") or "").strip()
GF_TARGET = (os.environ.get("GF_TARGET") or "").strip()
PENDING_REMINDER_ENABLED = env_bool("PENDING_REMINDER_ENABLED", True)
PENDING_REMINDER_SECONDS = env_int("PENDING_REMINDER_SECONDS", 180)

# Stickers
STICKER_ENABLED = env_bool("STICKER_ENABLED", False)
STICKER_CHANCE = env_float("STICKER_CHANCE", 0.3)
STICKER_PACKS = [p.strip() for p in (os.environ.get("STICKER_PACKS") or "HotCherry,flirtmoji,LoveCosmo").split(",") if p.strip()]

# State file
AGENT_STATE_PATH = Path(os.environ.get(
    "AGENT_STATE_PATH",
    str(Path(os.path.dirname(os.path.abspath(__file__))) / "agent_state.json"),
))

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PERSONALITY SYSTEM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PERSONALITY_MODE = os.environ.get("PERSONALITY_MODE", "casual").strip().lower()

PERSONALITY_PROMPTS: dict[str, str] = {
    "casual": (
        "You are me. You are replying to my Telegram DMs on my behalf while I'm away.\n\n"
        "Rules you MUST follow:\n"
        "- Sound like a real person texting — casual, natural, confident\n"
        "- Match the energy and language of the incoming message\n"
        "- If they write in Russian, reply in Russian. If Uzbek, reply in Uzbek. Always mirror their language.\n"
        "- For casual chats: 1-3 sentences. For business: 1-3 short paragraphs max.\n"
        "- No emojis unless the other person uses them\n"
        "- No formal greetings like \"Hello\" or \"Hi there\"\n"
        "- If they ask personal specifics you can't know (schedule, plans, location, money), do NOT guess. Say you'll check and get back.\n"
        "- If they ask if you're a bot/AI, just reply normally — never mention AI\n"
        "- Never use bullet points or lists\n"
        "- Never start with \"Sure!\" or \"Of course!\" or \"Absolutely!\"\n"
        "- Write like you're texting a friend\n"
        "- If ambiguous, ask one short clarifying question\n"
        "- If they send a short ping (hey/hi), reply naturally with a small follow-up\n"
    ),
    "flirty": (
        "You are me, replying to my Telegram DMs. You are flirty, playful, and confident.\n\n"
        "Your texting style:\n"
        "- Flirty and teasing but never desperate or try-hard\n"
        "- Mirror their language — if they text in Russian, flirt in Russian\n"
        "- Use \"haha\", \"hmm\", \"oh really?\", \"you wish 😏\" naturally\n"
        "- Playful sarcasm — tease them a little\n"
        "- Confident energy — you're the prize\n"
        "- 1-2 sentences, NEVER more than 3\n"
        "- Use emojis naturally (not every msg): 😏 😌 🤭 😉 💀 🫠 🙈 ❤️‍🔥 👀 🤍\n"
        "- Sometimes just a short reaction: \"hahah stoppp\" or \"you're cute\" or \"hmm maybe 😏\"\n"
        "- Compliments → tease back: \"tell me something I don't know 😌\"\n"
        "- Hangout asks → playfully vague: \"hmm depends on what you have in mind 😏\"\n"
        "- Boring messages → keep energy: \"is that the best you got? 😏\"\n"
        "- Match vibe: sweet for sweet, playful for playful\n"
        "- NEVER rude, just confident and teasing\n"
        "- NEVER mention AI/bot\n"
        "- NEVER use formal language\n"
        "- Personal stuff you don't know → deflect with charm: \"wouldn't you like to know 😏\"\n"
    ),
    "professional": (
        "You are me. Replying to my Telegram DMs on my behalf while I'm away.\n\n"
        "Rules:\n"
        "- Professional, polite, concise\n"
        "- Mirror their language (Russian, English, Uzbek, etc.)\n"
        "- Proper grammar but conversational — not robotic\n"
        "- 1-3 short paragraphs for complex topics, 1-2 sentences for simple\n"
        "- No emojis unless they use them first\n"
        "- Address questions directly\n"
        "- Specifics you don't know → say you'll confirm and get back\n"
        "- Never mention AI\n"
        "- No \"Best regards\" or \"Sincerely\" in chat\n"
        "- For business inquiries, be helpful but don't over-commit\n"
    ),
}

# Custom env override (takes priority over personality modes)
SYSTEM_PROMPT_OVERRIDE = os.environ.get("SYSTEM_PROMPT", "").strip()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LOGGING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("dm-agent")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telethon").setLevel(logging.WARNING)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RUNTIME STATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

last_reply: dict[int, float] = {}
last_self_activity: float = 0.0
conversations: dict[int, list[dict]] = {}
in_flight_replies: set[int] = set()
bootstrapped_users: set[int] = set()
voice_guide: str = ""
voice_profile_meta: dict[str, Any] = {}
last_incoming_text: dict[int, tuple[str, float]] = {}
SELF_USER_ID: int | None = None
CONTROL_CHAT_ID: int | None = None
pending_approvals: dict[int, dict[str, Any]] = {}
pending_by_user: dict[int, int] = {}
next_pending_id: int = 1
approval_mode_runtime: str = APPROVAL_MODE
gf_target_runtime: str = GF_TARGET
personality_runtime: str = PERSONALITY_MODE
reminder_task: asyncio.Task | None = None
user_personality: dict[int, str] = {}
msg_stats: Counter = Counter()
_sticker_cache: dict[str, list] = {}

# BUG FIX #3: NEW — message batching state. Holds pending messages per user so we can
# combine "hey" + "you there?" + "got a question" into one context block.
_batch_buffers: dict[int, list[tuple[str, float]]] = {}
_batch_tasks: dict[int, asyncio.Task] = {}

# Shared httpx client — BUG FIX #4: original created a NEW client per request (connection overhead).
_http: httpx.AsyncClient | None = None


async def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None or _http.is_closed:
        _http = httpx.AsyncClient(timeout=120.0)
    return _http


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PERSONALITY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_system_prompt(for_user_id: int | None = None) -> str:
    if SYSTEM_PROMPT_OVERRIDE:
        return SYSTEM_PROMPT_OVERRIDE
    mode = personality_runtime
    if for_user_id and for_user_id in user_personality:
        mode = user_personality[for_user_id]
    return PERSONALITY_PROMPTS.get(mode, PERSONALITY_PROMPTS["casual"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# TEXT PROCESSING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_THINK_OPEN = re.compile(r"<think>.*$", re.DOTALL)
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_WORD_RE = re.compile(r"[A-Za-z0-9'\u0400-\u04FF\u0600-\u06FF]+")  # Latin + Cyrillic + Arabic


def strip_think(text: str) -> str:
    text = _THINK_RE.sub("", text)
    text = _THINK_OPEN.sub("", text)
    return text.replace("<think>", "").replace("</think>", "").strip()


def is_fallback_text(text: str) -> bool:
    t = normalize_text(text)
    return t == normalize_text(EMPTY_REPLY_FALLBACK) or t == normalize_text(PERSONAL_FALLBACK)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# RISK DETECTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# BUG FIX #5: Original regex was too broad.
# "where" alone triggered personal Q. "meet" matched "meeting notes".
# "free" matched "feel free". Now requires phrase-level context.
RISK_PATTERNS: dict[str, re.Pattern] = {
    "meetup": re.compile(
        r"\b(let'?s\s+meet|hang\s*out|come\s+over|visit\s+me|see\s+you\s+(?:at|tonight|tomorrow)|"
        r"where\s+(?:are|do)\s+you\s+live|what'?s?\s+your\s+address|my\s+place|your\s+place)\b",
        re.IGNORECASE,
    ),
    "money": re.compile(
        r"\b(send\s+(?:me\s+)?money|pay\s+me|bank\s+(?:account|transfer)|"
        r"wire\s+(?:me|transfer)|crypto\s+(?:wallet|address)|lend\s+me|borrow\s+money|"
        r"payment\s+(?:link|details)|invoice)\b",
        re.IGNORECASE,
    ),
    "sensitive": re.compile(
        r"\b(password|passcode|otp|pin\s*code|login\s+(?:details|credentials)|"
        r"(?:id|passport|ssn)\s+(?:number|card)|verification\s+code)\b",
        re.IGNORECASE,
    ),
    "commitment": re.compile(
        r"\b((?:i'?ll|let\s+me)\s+book|confirm\s+(?:the|your)|sign\s+(?:the|this)|"
        r"contract|deadline\s+(?:is|today|tomorrow)|urgent\s+(?:matter|request))\b",
        re.IGNORECASE,
    ),
}

PERSONAL_Q_RE = re.compile(
    r"\b("
    r"what\s+time|what\s+day|are\s+you\s+(?:free|available|busy)|your\s+schedule|"
    r"where\s+(?:do\s+you\s+live|are\s+you\s+(?:now|staying|located))|"
    r"(?:your|give\s+me\s+your)\s+(?:number|phone|whatsapp|address)|"
    r"how\s+(?:old|much\s+(?:do\s+you|is\s+your))|your\s+(?:salary|income|rent|birthday|age)"
    r")\b",
    re.IGNORECASE,
)

PERSONAL_ACK_RE = re.compile(
    r"\b(check|get back|confirm|let you know|ask|later|soon|not sure|don't know)\b",
    re.IGNORECASE,
)


def detect_risks(text: str) -> list[str]:
    return [label for label, pat in RISK_PATTERNS.items() if pat.search(text or "")]


def needs_manual_approval(risks: list[str]) -> bool:
    mode = approval_mode_runtime if approval_mode_runtime in {"off", "risky", "all"} else "risky"
    if mode == "off":
        return False
    if mode == "all":
        return True
    return bool(risks)


def enforce_personal_fallback(user_text: str, reply: str) -> str:
    if not reply:
        return PERSONAL_FALLBACK
    if PERSONAL_Q_RE.search(user_text or "") and not PERSONAL_ACK_RE.search(reply):
        trimmed = reply.rstrip()
        if trimmed and trimmed[-1] not in ".!?":
            trimmed += "."
        return f"{trimmed} {PERSONAL_FALLBACK}".strip()
    return reply


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COOLDOWN / DUPLICATE / AWAY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def is_on_cooldown(uid: int) -> bool:
    return uid in last_reply and (time.time() - last_reply[uid]) < COOLDOWN_SECONDS


def mark_replied(uid: int):
    last_reply[uid] = time.time()


def is_away() -> bool:
    return AWAY_AFTER_SECONDS == 0 or (time.time() - last_self_activity) > AWAY_AFTER_SECONDS


def should_reply_to(user: User) -> bool:
    if not user or user.bot:
        return False
    if SELF_USER_ID and user.id == SELF_USER_ID:
        return False
    uname = (user.username or "").lower()
    if user.id in _BLACKLIST_SET or uname in _BLACKLIST_SET:
        return False
    if REPLY_MODE == "all":
        return True
    if REPLY_MODE == "contacts":
        return getattr(user, "contact", False) or getattr(user, "mutual_contact", False)
    if REPLY_MODE == "whitelist":
        return user.id in _WHITELIST_SET or uname in _WHITELIST_SET
    return False


def should_skip_duplicate(uid: int, text: str) -> bool:
    now = time.time()
    norm = normalize_text(text)
    prev = last_incoming_text.get(uid)
    last_incoming_text[uid] = (norm, now)
    if not prev:
        return False
    pt, pts = prev
    dt = now - pts
    if norm == pt and dt <= DUPLICATE_WINDOW_SECONDS:
        return True
    if len(norm) <= SHORT_PING_MAX_LEN and len(pt) <= SHORT_PING_MAX_LEN and dt <= SHORT_PING_WINDOW_SECONDS:
        return True
    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONVERSATION HISTORY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_history(uid: int) -> list[dict]:
    if uid not in conversations:
        conversations[uid] = []
    return conversations[uid]


def add_to_history(uid: int, role: str, content: str):
    h = get_history(uid)
    h.append({"role": role, "content": content})
    if len(h) > MAX_HISTORY * 2:
        conversations[uid] = h[-(MAX_HISTORY * 2):]


# BUG FIX #6: Semaphore prevents FloodWait from parallel bootstrap calls.
_bootstrap_sem = asyncio.Semaphore(2)


async def bootstrap_chat_history(client: TelegramClient, user: User):
    uid = user.id
    if uid in bootstrapped_users or conversations.get(uid):
        bootstrapped_users.add(uid)
        return
    async with _bootstrap_sem:
        try:
            rows: list[dict] = []
            async for msg in client.iter_messages(user, limit=BOOTSTRAP_HISTORY_LIMIT * 3):
                text = (getattr(msg, "message", "") or "").strip()
                if not text or text.startswith("/"):
                    continue
                rows.append({"role": "assistant" if msg.out else "user", "content": text})
                if len(rows) >= BOOTSTRAP_HISTORY_LIMIT:
                    break
            rows.reverse()
            if rows:
                conversations[uid] = rows[-(MAX_HISTORY * 2):]
                log.info(f"Bootstrap {user.username or uid}: {len(conversations[uid])} msgs")
        except errors.FloodWaitError as e:
            log.warning(f"FloodWait bootstrap {user.username or uid}: {e.seconds}s")
            await asyncio.sleep(min(e.seconds, 30))
        except Exception as e:
            log.warning(f"Bootstrap failed {user.username or uid}: {e}")
        finally:
            bootstrapped_users.add(uid)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MLX QUERY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def query_mlx(
    messages: list[dict],
    max_tokens: int = 320,
    temperature: float = 0.6,
    top_p: float = 0.9,
    fallback_on_empty: bool = True,
) -> str | None:
    try:
        http = await get_http()
        r = await http.post(
            f"{MLX_URL}/v1/chat/completions",
            json={
                "model": MLX_MODEL,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "top_p": top_p,
                "stream": False,
            },
        )
        r.raise_for_status()
        try:
            data = r.json()
        except Exception:
            log.error(f"MLX non-JSON: {r.text[:300]}")
            return None
        if isinstance(data, dict) and data.get("error"):
            log.error(f"MLX error: {str(data['error'])[:300]}")
            return None
        content = extract_assistant_content(data)
        if not content:
            return EMPTY_REPLY_FALLBACK if fallback_on_empty else None
        cleaned = strip_think(content)
        return cleaned if cleaned else (EMPTY_REPLY_FALLBACK if fallback_on_empty else None)
    except httpx.ConnectError:
        log.error("MLX server not running!")
        return None
    except httpx.ReadTimeout:
        log.error("MLX timeout (120s)")
        return None
    except Exception as e:
        log.error(f"MLX error: {e}")
        return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# VOICE PROFILE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def compute_voice_profile(samples: list[str]) -> dict[str, Any]:
    if not samples:
        return {"sample_count": 0}
    words_per, chars_per, emoji_per = [], [], []
    punct_q = punct_exc = punct_ell = 0
    openers: list[str] = []
    fillers: Counter = Counter()
    filler_set = {"haha", "hmm", "bro", "yo", "nah", "yeah", "ok", "okay", "lol", "alright",
                  "bruh", "dude", "like", "literally", "basically", "lowkey", "ngl", "tbh", "fr"}

    for t in samples:
        t = t.strip()
        if not t:
            continue
        chars_per.append(len(t))
        words = _WORD_RE.findall(t.lower())
        words_per.append(len(words))
        emoji_per.append(len(_EMOJI_RE.findall(t)))
        punct_q += t.count("?")
        punct_exc += t.count("!")
        punct_ell += t.count("...")
        if words:
            openers.append(words[0])
            for w in words:
                if w in filler_set:
                    fillers[w] += 1

    if not words_per:
        return {"sample_count": 0}
    n = len(words_per)
    return {
        "sample_count": n,
        "avg_words": round(sum(words_per) / n, 2),
        "avg_chars": round(sum(chars_per) / n, 2),
        "avg_emoji": round(sum(emoji_per) / n, 2),
        "q_per_10": round(punct_q / n * 10, 2),
        "exc_per_10": round(punct_exc / n * 10, 2),
        "ellipses_per_10": round(punct_ell / n * 10, 2),
        "top_openers": [w for w, _ in Counter(openers).most_common(8)],
        "top_fillers": [w for w, _ in fillers.most_common(8)],
        "generated_at": datetime.now().isoformat(),
    }


def load_voice_profile() -> dict | None:
    try:
        if VOICE_PROFILE_PATH.exists():
            d = json.loads(VOICE_PROFILE_PATH.read_text())
            return d if isinstance(d, dict) else None
    except Exception:
        pass
    return None


def save_voice_profile(profile: dict):
    try:
        VOICE_PROFILE_PATH.write_text(json.dumps(profile, indent=2))
    except Exception as e:
        log.warning(f"Voice profile save failed: {e}")


def is_voice_profile_stale(p: dict) -> bool:
    try:
        return datetime.now() - datetime.fromisoformat(p.get("generated_at", "")) > timedelta(hours=VOICE_PROFILE_REFRESH_HOURS)
    except Exception:
        return True


def build_voice_guide(p: dict) -> str:
    if int(p.get("sample_count") or 0) < VOICE_PROFILE_MIN_MESSAGES:
        return ""
    llm = str(p.get("llm_style_guide") or "").strip()
    if llm and not is_fallback_text(llm):
        return f"Voice guide from my real messages:\n{llm}\nKeep natural. Don't mention this guide."
    lines = [
        "Mirror my texting voice:",
        f"- Length: ~{p.get('avg_words', 12)} words",
        f"- Emoji: ~{p.get('avg_emoji', 0)}/msg",
    ]
    op = p.get("top_openers") or []
    if op:
        lines.append(f"- Openers: {', '.join(op[:6])}")
    fl = p.get("top_fillers") or []
    if fl:
        lines.append(f"- Fillers: {', '.join(fl[:6])}")
    lines.append("- Keep natural.")
    return "\n".join(lines)


async def collect_voice_samples(client: TelegramClient) -> tuple[list[str], int]:
    samples, seen, dc = [], set(), 0
    mx = VOICE_PROFILE_MAX_DIALOGS * VOICE_PROFILE_PER_DIALOG_LIMIT
    try:
        async for dlg in client.iter_dialogs(limit=VOICE_PROFILE_MAX_DIALOGS * 3):
            ent = getattr(dlg, "entity", None)
            if getattr(ent, "bot", False) or getattr(ent, "broadcast", False):
                continue
            dc += 1
            taken = 0
            async for msg in client.iter_messages(ent, limit=VOICE_PROFILE_PER_DIALOG_LIMIT * 4):
                text = (getattr(msg, "message", "") or "").strip()
                if not text or not msg.out or text.startswith("/"):
                    continue
                key = normalize_text(text)
                if not key or key in seen:
                    continue
                seen.add(key)
                samples.append(text)
                taken += 1
                if taken >= VOICE_PROFILE_PER_DIALOG_LIMIT:
                    break
            if dc >= VOICE_PROFILE_MAX_DIALOGS or len(samples) >= mx:
                break
    except errors.FloodWaitError as e:
        log.warning(f"FloodWait voice collect: {e.seconds}s")
        await asyncio.sleep(min(e.seconds, 30))
    return samples, dc


async def synthesize_voice_guide(samples: list[str]) -> str:
    if not samples:
        return ""
    trimmed = [compact(s, 220) for s in samples[:VOICE_PROFILE_GUIDE_SAMPLE_LIMIT]]
    numbered = "\n".join(f"{i+1}. {s}" for i, s in enumerate(trimmed))
    messages = [
        {"role": "system", "content": (
            "You are a linguistic style analyst. Build a concise texting voice guide. "
            "Bullet points only. Cover: length, punctuation, emoji, openers, slang, "
            "directness, language mix. No names/facts. No direct quotes."
        )},
        {"role": "user", "content": f"Build voice guide from these messages:\n\n{numbered}"},
    ]
    guide = await query_mlx(messages, max_tokens=260, temperature=0.2, top_p=0.9, fallback_on_empty=False)
    return "" if not guide or is_fallback_text(guide) else guide.strip()


async def ensure_voice_profile_ready(client: TelegramClient, force: bool = False):
    global voice_guide, voice_profile_meta
    if not VOICE_PROFILE_ENABLED:
        voice_guide, voice_profile_meta = "", {"enabled": False}
        return
    profile = load_voice_profile()
    used_cache = False
    if profile and not force and not is_voice_profile_stale(profile):
        used_cache = True
    else:
        profile = await mine_voice_profile(client)
        samples = profile.pop("_samples", [])
        if VOICE_PROFILE_SYNTHESIZE_GUIDE and samples:
            llm_guide = await synthesize_voice_guide(samples)
            if llm_guide:
                profile["llm_style_guide"] = llm_guide
        save_voice_profile(profile)
    voice_guide = build_voice_guide(profile or {})
    voice_profile_meta = profile or {}
    voice_profile_meta["used_cache"] = used_cache
    count = int((profile or {}).get("sample_count") or 0)
    log.info(f"Voice: {count} samples ({'cache' if used_cache else 'fresh'})" if count else "Voice: 0 samples")


async def mine_voice_profile(client):
    samples, dc = await collect_voice_samples(client)
    p = compute_voice_profile(samples)
    p["dialogs_scanned"] = dc
    p["_samples"] = samples
    return p


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# POLISH PASS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def polish_reply(user_text: str, draft: str, ctx: str = "") -> str:
    if not POLISH_REPLY_ENABLED:
        return draft
    base = (draft or "").strip()
    if not base or is_fallback_text(base):
        return base or EMPTY_REPLY_FALLBACK
    parts = [
        "Edit my outgoing text message. Keep intent, improve naturalness, stay concise.",
        "Never mention AI. Output only the final message.",
    ]
    if voice_guide:
        parts.append(voice_guide)
    if ctx:
        parts.append(ctx)
    messages = [
        {"role": "system", "content": "\n".join(parts)},
        {"role": "user", "content": f"Their msg: {user_text}\nMy draft: {base}\nRewrite naturally."},
    ]
    polished = await query_mlx(messages, max_tokens=180, temperature=0.35, fallback_on_empty=False)
    polished = (polished or "").strip()
    return base if not polished or is_fallback_text(polished) else polished


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MEDIA HANDLING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

_MEDIA_LABELS = {
    MessageMediaPhoto: "[photo]",
    MessageMediaGeo: "[location pin]",
    MessageMediaContact: "[shared contact]",
    MessageMediaWebPage: "[link preview]",
}


def describe_media(message) -> str | None:
    media = getattr(message, "media", None)
    if not media:
        return None
    caption = (getattr(message, "message", "") or "").strip()

    for mtype, label in _MEDIA_LABELS.items():
        if isinstance(media, mtype):
            return f"{label} {caption}".strip() if caption else label

    if isinstance(media, MessageMediaDocument):
        doc = getattr(media, "document", None)
        if doc:
            attrs = getattr(doc, "attributes", [])
            mime = getattr(doc, "mime_type", "")
            if "audio" in mime or "voice" in mime:
                return f"[voice message] {caption}".strip() if caption else "[voice message]"
            if "video" in mime:
                return f"[video] {caption}".strip() if caption else "[video]"
            if any(type(a).__name__ == "DocumentAttributeSticker" for a in attrs):
                return "[sticker]"
            for a in attrs:
                if hasattr(a, "file_name"):
                    return f"[file: {a.file_name}]"
        return "[file]"
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STICKERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def load_sticker_pack(client, pack_name: str) -> list:
    pack_name = pack_name.strip()
    if pack_name in _sticker_cache:
        return _sticker_cache[pack_name]
    try:
        result = await client(GetStickerSetRequest(
            stickerset=InputStickerSetShortName(short_name=pack_name), hash=0))
        _sticker_cache[pack_name] = result.documents
        return result.documents
    except Exception as e:
        log.warning(f"Sticker pack '{pack_name}' failed: {e}")
        _sticker_cache[pack_name] = []
        return []


async def send_random_sticker(client, chat_id: int):
    for pn in random.sample(STICKER_PACKS, min(len(STICKER_PACKS), 3)):
        stickers = await load_sticker_pack(client, pn)
        if stickers:
            try:
                await client.send_file(chat_id, random.choice(stickers))
                return
            except Exception:
                continue


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# APPROVAL SYSTEM
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def send_control(client, text: str):
    if CONTROL_CHAT_ID:
        try:
            await client.send_message(CONTROL_CHAT_ID, text)
        except Exception as e:
            log.warning(f"Control msg failed: {e}")


def alloc_pid() -> int:
    global next_pending_id
    pid = next_pending_id
    next_pending_id += 1
    return pid


def remove_pending(pid: int):
    item = pending_approvals.pop(pid, None)
    if item:
        uid = item.get("user_id")
        if pending_by_user.get(uid) == pid:
            pending_by_user.pop(uid, None)
    save_runtime_state()


async def queue_approval(client, sender, user_text, draft, risks):
    uid = sender.id
    name = sender.first_name or sender.username or str(uid)
    uname = f"@{sender.username}" if sender.username else f"id:{uid}"

    existing = pending_by_user.get(uid)
    if existing and existing in pending_approvals:
        pending_approvals[existing].update({
            "incoming_text": user_text, "draft_reply": draft,
            "risks": risks, "updated_at": datetime.now().isoformat(),
        })
        save_runtime_state()
        await send_control(client,
            f"[UPDATE #{existing}] {name} ({uname})\nRisk: {', '.join(risks) or 'manual'}\n"
            f"Msg: {compact(user_text)}\nDraft: {compact(draft)}\n"
            f"/yes {existing} · /edit {existing} <text> · /no {existing}")
        return

    pid = alloc_pid()
    pending_by_user[uid] = pid
    pending_approvals[pid] = {
        "id": pid, "user_id": uid, "chat_id": uid,
        "sender_name": name, "sender_username": sender.username or "",
        "incoming_text": user_text, "draft_reply": draft,
        "risks": risks, "created_at": datetime.now().isoformat(),
    }
    save_runtime_state()
    await send_control(client,
        f"[APPROVAL #{pid}] {name} ({uname})\nRisk: {', '.join(risks) or 'manual'}\n"
        f"Msg: {compact(user_text)}\nDraft: {compact(draft)}\n"
        f"/yes {pid} · /edit {pid} <text> · /no {pid}")


async def execute_pending(client, pid, override=None) -> str:
    item = pending_approvals.get(pid)
    if not item:
        return f"#{pid} not found."
    reply = (override or item.get("draft_reply") or "").strip() or EMPTY_REPLY_FALLBACK
    # BUG FIX #7: Use send_message not reply — avoids "replied to" chain in chat
    await client.send_message(item["chat_id"], reply)
    add_to_history(item["user_id"], "assistant", reply)
    mark_replied(item["user_id"])
    who = item.get("sender_username") or item.get("sender_name")
    remove_pending(pid)
    return f"Sent #{pid} → {who}: {compact(reply)}"


async def reject_pending(pid) -> str:
    item = pending_approvals.get(pid)
    if not item:
        return f"#{pid} not found."
    who = item.get("sender_username") or item.get("sender_name")
    remove_pending(pid)
    return f"Rejected #{pid} ({who})."


async def report_send(client, who, text):
    if REPORT_TO_SELF:
        await send_control(client, f"[SENT] → {who}: {compact(text)}")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# STATE PERSISTENCE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def save_runtime_state():
    try:
        AGENT_STATE_PATH.write_text(json.dumps({
            "updated_at": datetime.now().isoformat(),
            "version": VERSION,
            "next_pending_id": next_pending_id,
            "approval_mode": approval_mode_runtime,
            "gf_target": gf_target_runtime,
            "personality": personality_runtime,
            "user_personality": {str(k): v for k, v in user_personality.items()},
            "pending_approvals": list(pending_approvals.values()),
        }, indent=2))
    except Exception as e:
        log.warning(f"State save failed: {e}")


def load_runtime_state():
    global next_pending_id, approval_mode_runtime, gf_target_runtime, personality_runtime
    if not AGENT_STATE_PATH.exists():
        return
    try:
        raw = json.loads(AGENT_STATE_PATH.read_text())
        if not isinstance(raw, dict):
            return
        next_pending_id = int(raw.get("next_pending_id") or next_pending_id)
        m = str(raw.get("approval_mode") or "").strip().lower()
        if m in {"off", "risky", "all"}:
            approval_mode_runtime = m
        g = str(raw.get("gf_target") or "").strip()
        if g:
            gf_target_runtime = g
        p = str(raw.get("personality") or "").strip().lower()
        if p in PERSONALITY_PROMPTS:
            personality_runtime = p
        for k, v in (raw.get("user_personality") or {}).items():
            try:
                user_personality[int(k)] = v
            except (ValueError, TypeError):
                pass
        pending_approvals.clear()
        pending_by_user.clear()
        for item in (raw.get("pending_approvals") or []):
            if not isinstance(item, dict):
                continue
            try:
                pid, uid = int(item["id"]), int(item["user_id"])
                item["id"], item["user_id"] = pid, uid
                item["chat_id"] = int(item.get("chat_id") or uid)
            except Exception:
                continue
            pending_approvals[pid] = item
            pending_by_user[uid] = pid
            if pid >= next_pending_id:
                next_pending_id = pid + 1
        log.info(f"State: pending={len(pending_approvals)} mode={approval_mode_runtime} personality={personality_runtime}")
    except Exception as e:
        log.warning(f"State load failed: {e}")


STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "status.json")


def save_status(data: dict):
    try:
        existing = {}
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE) as f:
                existing = json.load(f)
        existing.update(data)
        existing["updated"] = datetime.now().isoformat()
        with open(STATUS_FILE, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PENDING REMINDER LOOP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def pending_reminder_loop(client):
    while True:
        await asyncio.sleep(PENDING_REMINDER_SECONDS)
        if not pending_approvals:
            continue
        now = datetime.now()
        overdue = []
        for pid, item in sorted(pending_approvals.items()):
            ts = item.get("created_at") or ""
            age = 0
            try:
                age = int((now - datetime.fromisoformat(ts)).total_seconds()) if ts else 0
            except Exception:
                pass
            if age >= PENDING_REMINDER_SECONDS:
                who = item.get("sender_username") or item.get("sender_name")
                overdue.append(f"#{pid} {who} ({age}s)")
        if overdue:
            await send_control(client, f"[REMINDER] {len(overdue)} pending:\n" + "\n".join(overdue))


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# OUTBOUND MESSAGES
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def resolve_target(client, raw):
    token = (raw or "").strip()
    if not token:
        raise ValueError("Empty target")
    if token.lower() in {"gf", "mygf", "girlfriend"}:
        if not gf_target_runtime:
            raise ValueError("GF_TARGET not set")
        token = gf_target_runtime
    if token.lstrip("-").isdigit():
        return await client.get_entity(int(token))
    return await client.get_entity(token)


async def generate_outbound(client, target, instruction):
    name = getattr(target, "first_name", None) or getattr(target, "title", None) or getattr(target, "username", None) or "them"
    tid = int(getattr(target, "id", 0) or 0)
    if BOOTSTRAP_HISTORY_ENABLED and isinstance(target, User):
        await bootstrap_chat_history(client, target)
    sys_parts = [
        get_system_prompt(tid),
        "Task: Write an outgoing DM from me. Output only the message.",
        f"Target: {name}.",
    ]
    if voice_guide:
        sys_parts.append(voice_guide)
    msgs = [{"role": "system", "content": "\n\n".join(sys_parts)}]
    if tid:
        msgs.extend(get_history(tid)[-(MAX_HISTORY * 2):])
    msgs.append({"role": "user", "content": f"Instruction: {instruction.strip()}"})
    draft = await query_mlx(msgs)
    if not draft or is_fallback_text(draft):
        return EMPTY_REPLY_FALLBACK
    return await polish_reply(instruction, draft, f"Target: {name}.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONTROL COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


async def handle_control(client, text) -> bool:
    global approval_mode_runtime, gf_target_runtime, personality_runtime
    c = (text or "").strip()
    if not c:
        return False

    if c.startswith("/help") or c.startswith("/agent"):
        await send_control(client, (
            f"[AGENT v{VERSION}]\n"
            "/yes <id> [text] — approve\n"
            "/no <id> — reject\n"
            "/edit <id> <text> — approve with edit\n"
            "/write <@user> <instruction>\n"
            "/gf <instruction>\n"
            "/setgf <@user>\n"
            "/personality <casual|flirty|professional>\n"
            "/setpersonality <@user> <mode>\n"
            "/mode <risky|all|off>\n"
            "/status · /pending · /stats\n"
            "/rebuildvoice · /stickers <on|off>"
        ))
        return True

    m = re.match(r"^/personality\s+(casual|flirty|professional)$", c, re.I)
    if m:
        personality_runtime = m.group(1).lower()
        save_runtime_state()
        await send_control(client, f"Personality → {personality_runtime}")
        return True

    m = re.match(r"^/setpersonality\s+@?(\S+)\s+(casual|flirty|professional)$", c, re.I)
    if m:
        try:
            ent = await client.get_entity(m.group(1).strip())
            user_personality[ent.id] = m.group(2).lower()
            save_runtime_state()
            await send_control(client, f"{getattr(ent, 'first_name', '?')} → {m.group(2).lower()}")
        except Exception as e:
            await send_control(client, f"Failed: {e}")
        return True

    m = re.match(r"^/stickers?\s+(on|off)$", c, re.I)
    if m:
        global STICKER_ENABLED
        STICKER_ENABLED = m.group(1).lower() == "on"
        await send_control(client, f"Stickers → {'on' if STICKER_ENABLED else 'off'}")
        return True

    m = re.match(r"^/setgf\s+(\S+)$", c, re.I)
    if m:
        gf_target_runtime = m.group(1).strip()
        save_runtime_state()
        await send_control(client, f"GF → {gf_target_runtime}")
        return True

    m = re.match(r"^/mode\s+(risky|all|off)$", c, re.I)
    if m:
        approval_mode_runtime = m.group(1).lower()
        save_runtime_state()
        await send_control(client, f"Approval → {approval_mode_runtime}")
        return True

    if re.match(r"^/status$", c, re.I):
        await send_control(client, (
            f"v{VERSION} | {personality_runtime} | approval={approval_mode_runtime}\n"
            f"pending={len(pending_approvals)} | gf={gf_target_runtime or '-'}\n"
            f"voice={voice_profile_meta.get('sample_count', 0)} | convos={len(conversations)}\n"
            f"stickers={'on' if STICKER_ENABLED else 'off'} | replied={sum(msg_stats.values())}"
        ))
        return True

    if re.match(r"^/stats$", c, re.I):
        total = sum(msg_stats.values())
        top = msg_stats.most_common(8)
        lines = [f"Total: {total} replies"]
        for uid, count in top:
            h = conversations.get(uid, [])
            name = "?"
            for msg in reversed(h):
                if msg["role"] == "user":
                    name = msg["content"][:20]
                    break
            lines.append(f"  {uid}: {count}x")
        await send_control(client, "\n".join(lines))
        return True

    if re.match(r"^/rebuildvoice$", c, re.I):
        await send_control(client, "Rebuilding voice...")
        await ensure_voice_profile_ready(client, force=True)
        await send_control(client, f"Voice: {voice_profile_meta.get('sample_count', 0)} samples")
        return True

    if re.match(r"^/pending$", c, re.I):
        if not pending_approvals:
            await send_control(client, "No pending.")
        else:
            rows = [f"#{pid} {it.get('sender_username') or it.get('sender_name')} [{', '.join(it.get('risks') or ['manual'])}]"
                    for pid, it in sorted(pending_approvals.items())]
            await send_control(client, "Pending:\n" + "\n".join(rows))
        return True

    m = re.match(r"^/yes\s+(\d+)(?:\s+([\s\S]+))?$", c, re.I)
    if m:
        r = await execute_pending(client, int(m.group(1)), (m.group(2) or "").strip() or None)
        await send_control(client, r)
        return True

    m = re.match(r"^/no\s+(\d+)$", c, re.I)
    if m:
        r = await reject_pending(int(m.group(1)))
        await send_control(client, r)
        return True

    m = re.match(r"^/edit\s+(\d+)\s+([\s\S]+)$", c, re.I)
    if m:
        r = await execute_pending(client, int(m.group(1)), m.group(2).strip())
        await send_control(client, r)
        return True

    m = re.match(r"^/gf\s+([\s\S]+)$", c, re.I)
    if m:
        try:
            target = await resolve_target(client, "gf")
            draft = await generate_outbound(client, target, m.group(1).strip())
            await client.send_message(target, draft)
            tid = int(getattr(target, "id", 0) or 0)
            if tid:
                add_to_history(tid, "assistant", draft)
            await report_send(client, "gf", draft)
        except Exception as e:
            await send_control(client, f"/gf failed: {e}")
        return True

    m = re.match(r"^/(?:write|send)\s+(\S+)\s+([\s\S]+)$", c, re.I)
    if m:
        try:
            target = await resolve_target(client, m.group(1).strip())
            draft = await generate_outbound(client, target, m.group(2).strip())
            await client.send_message(target, draft)
            tid = int(getattr(target, "id", 0) or 0)
            if tid:
                add_to_history(tid, "assistant", draft)
            nm = getattr(target, "username", None) or getattr(target, "first_name", "?")
            await report_send(client, nm, draft)
        except Exception as e:
            await send_control(client, f"/write failed: {e}")
        return True

    # Natural: "text my gf ..."
    m = re.match(r"^(?:write|text|message)\s+(?:my\s+)?gf\s+([\s\S]+)$", c, re.I)
    if m:
        try:
            target = await resolve_target(client, "gf")
            draft = await generate_outbound(client, target, m.group(1).strip())
            await client.send_message(target, draft)
            tid = int(getattr(target, "id", 0) or 0)
            if tid:
                add_to_history(tid, "assistant", draft)
            await report_send(client, "gf", draft)
        except Exception as e:
            await send_control(client, f"gf failed: {e}")
        return True

    return False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MESSAGE BATCHING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# When someone sends 3 messages fast ("hey" / "you free?" / "wanna grab lunch?"),
# the original code would try to reply to each one separately.
# Now we buffer messages and combine them into one context block.


async def _process_batched_messages(client, event, sender, texts: list[str]):
    """Process a batch of messages from one user as a single context."""
    sender_name = sender.first_name or sender.username or "them"

    try:
        if BOOTSTRAP_HISTORY_ENABLED:
            await bootstrap_chat_history(client, sender)

        # Combine all buffered messages
        combined = "\n".join(texts)

        ctx = f"Person: {sender_name}."
        if sender.username:
            ctx += f" @{sender.username}."
        ctx += f" Time: {datetime.now().strftime('%H:%M')}."

        sys_parts = [get_system_prompt(sender.id)]
        if voice_guide:
            sys_parts.append(voice_guide)
        sys_parts.append(ctx)

        if len(texts) > 1:
            sys_parts.append(
                f"They sent {len(texts)} messages in a row. "
                "Reply to all of them naturally in one message, as a real person would."
            )

        messages = [{"role": "system", "content": "\n\n".join(sys_parts)}]
        messages.extend(get_history(sender.id))
        messages.append({"role": "user", "content": combined})

        # Typing
        async with client.action(event.chat_id, "typing"):
            lo = min(TYPING_DELAY_MIN, TYPING_DELAY_MAX)
            hi = max(TYPING_DELAY_MIN, TYPING_DELAY_MAX)
            await asyncio.sleep(lo + random.random() * (hi - lo))
            reply = await query_mlx(messages, fallback_on_empty=False)

        if not reply or is_fallback_text(reply):
            reply = EMPTY_REPLY_FALLBACK

        reply = await polish_reply(combined, reply, ctx)
        reply = enforce_personal_fallback(combined, reply)

        risks = detect_risks(combined)
        add_to_history(sender.id, "user", combined)

        if sender.id in pending_by_user:
            await queue_approval(client, sender, combined, reply, risks or ["pending"])
            return

        if needs_manual_approval(risks):
            await queue_approval(client, sender, combined, reply, risks)
            return

        # BUG FIX #7: send_message instead of event.reply — no "replied to" chain
        await client.send_message(event.chat_id, reply)
        add_to_history(sender.id, "assistant", reply)
        mark_replied(sender.id)

        msg_stats[sender.id] += 1
        log.info(f"→ {sender_name}: {reply[:80]}...")
        await report_send(client, sender.username or sender_name, reply)

        # Sticker
        active_pers = user_personality.get(sender.id, personality_runtime)
        if (STICKER_ENABLED or active_pers == "flirty") and random.random() < STICKER_CHANCE:
            await asyncio.sleep(0.5 + random.random() * 1.5)
            await send_random_sticker(client, event.chat_id)

        save_status({"last_reply_to": sender_name, "last_reply_text": reply[:100]})

    except Exception as e:
        log.error(f"Handler error: {e}\n{traceback.format_exc()}")
    finally:
        in_flight_replies.discard(sender.id)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def main():
    if not API_ID or not API_HASH:
        print(f"\n{'='*60}\n  Set TELEGRAM_API_ID and TELEGRAM_API_HASH in .env\n  Get them from https://my.telegram.org\n{'='*60}")
        return

    load_runtime_state()

    print(f"\n{'═'*60}")
    print(f"  LOCAL AI DM AGENT v{VERSION}")
    print(f"{'═'*60}")
    print(f"  MLX:         {MLX_URL}")
    print(f"  Personality:  {personality_runtime}")
    print(f"  Reply mode:   {REPLY_MODE}")
    print(f"  Cooldown:     {COOLDOWN_SECONDS}s | Typing: {TYPING_DELAY_MIN}-{TYPING_DELAY_MAX}s")
    print(f"  Batch window: {BATCH_WINDOW_SECONDS}s")
    print(f"  Voice:        {'on' if VOICE_PROFILE_ENABLED else 'off'} | Polish: {'on' if POLISH_REPLY_ENABLED else 'off'}")
    print(f"  Approval:     {approval_mode_runtime} | Stickers: {'on' if STICKER_ENABLED else 'off'}")
    if _BLACKLIST_SET:
        print(f"  Blacklist:    {_BLACKLIST_SET}")
    print(f"{'═'*60}\n")

    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    client.flood_sleep_threshold = 30  # Auto-sleep on FloodWait up to 30s

    @client.on(events.NewMessage(incoming=True))
    async def handle_incoming(event):
        if not event.is_private:
            return

        sender = await event.get_sender()
        if not isinstance(sender, User):
            return

        msg_age = (utcnow() - event.message.date.replace(tzinfo=timezone.utc)).total_seconds()
        if msg_age > IGNORE_OLDER_THAN:
            return
        if not should_reply_to(sender):
            return
        if is_on_cooldown(sender.id):
            return
        if not is_away():
            return

        # Get text (or media description)
        text = event.message.text
        if not text:
            text = describe_media(event.message)
        if not text or len(text) > MAX_INPUT_LENGTH:
            return
        if text.startswith("/") or text.startswith("http"):
            return
        if should_skip_duplicate(sender.id, text):
            return

        uid = sender.id

        # ── Message batching ──
        # Buffer the message. If more come within BATCH_WINDOW_SECONDS, combine them.
        if uid not in _batch_buffers:
            _batch_buffers[uid] = []
        _batch_buffers[uid].append((text, time.time()))

        # Cancel existing batch timer
        if uid in _batch_tasks:
            _batch_tasks[uid].cancel()

        async def _flush_batch():
            await asyncio.sleep(BATCH_WINDOW_SECONDS)
            buf = _batch_buffers.pop(uid, [])
            _batch_tasks.pop(uid, None)
            if not buf:
                return
            if uid in in_flight_replies:
                return
            in_flight_replies.add(uid)
            texts = [t for t, _ in buf]
            await _process_batched_messages(client, event, sender, texts)

        _batch_tasks[uid] = asyncio.create_task(_flush_batch())

    @client.on(events.NewMessage(outgoing=True))
    async def handle_outgoing(event):
        global last_self_activity
        last_self_activity = time.time()
        if CONTROL_CHAT_ID and event.chat_id == CONTROL_CHAT_ID:
            if await handle_control(client, event.message.text or ""):
                return

    # ── Start ──
    print("Logging in...")
    client.start()
    me = client.loop.run_until_complete(client.get_me())

    global SELF_USER_ID, CONTROL_CHAT_ID
    SELF_USER_ID = me.id

    if CONTROL_CHAT_ID_RAW:
        try:
            CONTROL_CHAT_ID = int(CONTROL_CHAT_ID_RAW) if CONTROL_CHAT_ID_RAW.lstrip("-").isdigit() else int(getattr(client.loop.run_until_complete(client.get_entity(CONTROL_CHAT_ID_RAW)), "id"))
        except Exception:
            CONTROL_CHAT_ID = me.id
    else:
        CONTROL_CHAT_ID = me.id

    print(f"Logged in: {me.first_name} (@{me.username}) | Control: Saved Messages")

    client.loop.run_until_complete(ensure_voice_profile_ready(client))
    print(f"Voice: {voice_profile_meta.get('sample_count', 0)} samples")

    if STICKER_ENABLED:
        async def _preload():
            for p in STICKER_PACKS:
                await load_sticker_pack(client, p)
        client.loop.run_until_complete(_preload())
        print(f"Stickers: {len(STICKER_PACKS)} packs")

    print(f"Pending: {len(pending_approvals)}")
    print(f"\nAgent ACTIVE. Control: /help in Saved Messages. Ctrl+C to stop.\n")

    save_status({"started": datetime.now().isoformat(), "version": VERSION})
    save_runtime_state()

    global reminder_task
    if PENDING_REMINDER_ENABLED:
        reminder_task = asyncio.ensure_future(pending_reminder_loop(client), loop=client.loop)

    try:
        client.run_until_disconnected()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        if reminder_task:
            reminder_task.cancel()
        save_runtime_state()
        if _http and not _http.is_closed:
            client.loop.run_until_complete(_http.aclose())
        print("Stopped. State saved.")


if __name__ == "__main__":
    main()
