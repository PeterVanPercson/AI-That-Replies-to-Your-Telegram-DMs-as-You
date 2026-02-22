
<div align="center">

# 🤖 AI Twin — Telegram DM Agent

### Your AI clone that replies to Telegram DMs as you.

**Not a bot account. Not a cloud API. Your real account, your voice, your Mac.**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MLX](https://img.shields.io/badge/MLX-Apple%20Silicon-black.svg)](https://github.com/ml-explore/mlx)

</div>

---

## What is this?

A Python agent that runs on your Mac and automatically replies to your Telegram DMs using a local AI model. Messages come from **your real account** — the other person sees your name, your profile pic, your typing indicator. They have no idea it's AI.

The agent mines your real outgoing messages to learn how you text — your word length, emoji habits, slang, openers — then uses that voice profile for every reply.

**Everything runs locally. Your conversations never leave your machine.**

---

## Features

| Feature | Description |
|---|---|
| 🎭 **Voice Cloning** | Scans 1000+ of your real messages to build a texting style profile |
| 🔀 **Per-User Personality** | Flirty for her, professional for clients, casual for friends |
| 🛡️ **Risk Detection** | Catches money/meetup/password requests and queues for your approval |
| 📦 **Message Batching** | Combines "hey" + "you there?" + "question" into one smart reply |
| 🌍 **Language Matching** | Replies in their language — English, Russian, Uzbek, whatever |
| 📸 **Media Awareness** | Responds to photos, voice messages, stickers, files, locations |
| 🎯 **Control Panel** | Manage everything from Telegram's Saved Messages |
| 🔒 **100% Local** | MLX + Qwen3-8B on Apple Silicon. Zero cloud. Zero cost. |

---

## Requirements

- **Mac with Apple Silicon** (M1/M2/M3/M4/M5 — any variant)
- **16GB RAM** minimum (8GB works but slower)
- **macOS 14.0+** (Sonoma or newer)
- **Python 3.10+**
- **Telegram account** (regular user account, not a bot)

---

## Quick Start (5 minutes)

### Step 1: Get Telegram API credentials

1. Go to [https://my.telegram.org](https://my.telegram.org)
2. Log in with your phone number
3. Click **"API development tools"**
4. Fill in any app name (e.g., "MyAgent") and platform ("Other")
5. Save your **API ID** (a number) and **API Hash** (a hex string)

> ⚠️ **API ID is a number like `12345678`**, not an IP address. If you see `149.154.x.x`, you're looking at the wrong field.

### Step 2: Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/telegram-dm-agent.git
cd telegram-dm-agent
```

### Step 3: Run the setup script

```bash
chmod +x setup.sh
./setup.sh
```

This will:
- Check your Python version
- Create a virtual environment
- Install all dependencies
- Create your `.env` file from the template
- Prompt you for your Telegram API credentials

**Or do it manually:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env  # fill in your API_ID and API_HASH
```

### Step 4: Start the local AI server

You need a local LLM server running. We recommend MLX with Qwen3-8B:

```bash
# Install mlx-lm (one time)
pip install mlx-lm

# Start the server
mlx_lm.server \
  --model mlx-community/Qwen3-8B-4bit \
  --port 8080
```

> **First run downloads ~5GB.** After that it starts in seconds.
>
> Leave this terminal running. Open a **new terminal** for the next step.

<details>
<summary><b>Alternative models (click to expand)</b></summary>

| Model | RAM needed | Quality | Speed |
|---|---|---|---|
| `Qwen3-8B-4bit` | ~6GB | ⭐⭐⭐⭐ | Fast |
| `Qwen3-30B-A3B-4bit` | ~8GB | ⭐⭐⭐⭐⭐ | Fast (MoE) |
| `Qwen3-4B-4bit` | ~3GB | ⭐⭐⭐ | Very fast |
| `gemma-3-4b-it-4bit` | ~3GB | ⭐⭐⭐ | Very fast |

For 16GB Macs, `Qwen3-8B-4bit` is the sweet spot. If you want smarter replies and have headroom, try `Qwen3-30B-A3B-4bit` — it's a MoE (Mixture of Experts) model that only activates 3B parameters at a time, so it runs fast despite its size.

```bash
# Example with Qwen3-30B-A3B
mlx_lm.server --model mlx-community/Qwen3-30B-A3B-4bit --port 8080
```

</details>

### Step 5: Start the agent

```bash
source venv/bin/activate
python dm_agent.py
```

**First run only:** Telegram will ask for your phone number and a verification code. This creates a session file (`my_telegram.session`) so you won't need to log in again.

You should see:

```
══════════════════════════════════════════════════════════
  LOCAL AI DM AGENT v2.0
══════════════════════════════════════════════════════════
  MLX:         http://127.0.0.1:8080
  Personality:  casual
  Reply mode:   all
  Cooldown:     8s | Typing: 1.5-4.5s
  Batch window: 3.0s
  Voice:        on | Polish: on
  Approval:     risky | Stickers: off
══════════════════════════════════════════════════════════

Voice: 847 samples (fresh)
Agent ACTIVE. Control: /help in Saved Messages. Ctrl+C to stop.
```

**That's it. Your DMs are now on autopilot.**

---

## How It Works

```
Someone DMs you
        ↓
Agent checks: should I reply? (cooldown, away mode, blacklist)
        ↓
Waits 3s for more messages (batching)
        ↓
Builds context: system prompt + voice profile + chat history
        ↓
Sends to local AI (MLX on your Mac)
        ↓
Risk check: money/meetup/passwords?
    ├── Safe → sends reply automatically
    └── Risky → queues for your approval in Saved Messages
```

### Voice Cloning

On first start, the agent scans your last 40 conversations and collects your outgoing messages. It analyzes:

- Average word count per message
- Emoji usage frequency
- Common openers ("yo", "nah", "haha")
- Filler words ("like", "basically", "ngl")
- Punctuation style (questions, exclamations, ellipses)

Then it feeds a sample of your messages to the AI to generate a detailed writing style guide. This guide is injected into every reply prompt, so the AI mimics how you actually text.

The voice profile is cached in `voice_profile.json` and refreshes every 24 hours.

### Personalities

Three built-in modes:

| Mode | Vibe | Best for |
|---|---|---|
| `casual` | Natural, confident, like texting a friend | Default for everyone |
| `flirty` | Playful, teasing, emoji-friendly | Dating, close friends |
| `professional` | Polite, concise, proper grammar | Work contacts, clients |

Switch globally:
```
/personality flirty
```

Set per person:
```
/setpersonality @sarah flirty
/setpersonality @boss professional
```

### Approval System

When someone's message contains risky content (money requests, meetup invitations, password asks, commitment language), the agent **doesn't send automatically**. Instead:

1. It drafts a reply
2. Sends both the incoming message and draft to your **Saved Messages**
3. Waits for you to approve, edit, or reject

```
[APPROVAL #3] Sarah (@sarah_xx)
Risk: meetup
Msg: let's meet up tonight at my place 😏
Draft: hmm depends on what you have in mind 😏

/yes 3 · /edit 3 <your text> · /no 3
```

Set approval strictness:
```
/mode risky   ← only flag risky messages (default)
/mode all     ← approve every message before sending
/mode off     ← full autopilot, no approvals
```

---

## Control Commands

All commands are sent to your **Saved Messages** in Telegram:

| Command | What it does |
|---|---|
| `/help` | Show all commands |
| `/status` | Current settings, pending count, stats |
| `/stats` | Reply count per user |
| `/pending` | List pending approvals |
| `/yes <id>` | Approve and send draft |
| `/yes <id> <text>` | Approve with custom text |
| `/no <id>` | Reject (don't send anything) |
| `/edit <id> <text>` | Send your edited version |
| `/personality <mode>` | Switch global personality |
| `/setpersonality @user <mode>` | Per-user personality |
| `/mode <risky\|all\|off>` | Approval strictness |
| `/stickers <on\|off>` | Toggle sticker reactions |
| `/write @user <instruction>` | Generate and send a message |
| `/gf <instruction>` | Message your GF shortcut |
| `/setgf @username` | Set GF target |
| `/rebuildvoice` | Force rebuild voice profile |

---

## Configuration

All settings are in the `.env` file. Here are the important ones:

### Who gets replies

```bash
REPLY_MODE=all          # "all" / "contacts" / "whitelist"
WHITELIST=              # comma-separated: username1,username2,12345678
BLACKLIST=              # never reply to these people
```

### Timing

```bash
COOLDOWN_SECONDS=8        # minimum gap between replies to same person
TYPING_DELAY_MIN=1.5      # simulate human typing speed (seconds)
TYPING_DELAY_MAX=4.5
BATCH_WINDOW_SECONDS=3.0  # wait for multi-message bursts
AWAY_AFTER_SECONDS=0      # 0 = always reply. 300 = only if idle 5min
```

### Voice & Quality

```bash
VOICE_PROFILE_ENABLED=true      # learn your texting style
POLISH_REPLY_ENABLED=true       # second AI pass to improve replies
PERSONALITY_MODE=casual          # casual / flirty / professional
```

### Safety

```bash
APPROVAL_MODE=risky       # risky / all / off
REPORT_TO_SELF=true       # log all sent messages to Saved Messages
```

See [.env.example](.env.example) for all options with descriptions.

---

## Project Structure

```
telegram-dm-agent/
├── dm_agent.py          # The agent (this is the only file that runs)
├── .env.example         # Config template — copy to .env
├── setup.sh             # One-click setup script
├── requirements.txt     # Python dependencies
├── README.md            # You're reading it
├── LICENSE              # MIT
│
├── my_telegram.session  # Created on first login (DO NOT SHARE)
├── voice_profile.json   # Your voice profile (auto-generated)
├── agent_state.json     # Pending approvals, settings (auto-generated)
└── status.json          # Runtime status (auto-generated)
```

---

## Running as a Background Service

To keep the agent running after closing Terminal:

### Option A: tmux (simple)

```bash
# Start a session
tmux new -s agent

# Start MLX server
mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080

# Open new pane: Ctrl+B, then %
# Start agent
source venv/bin/activate && python dm_agent.py

# Detach: Ctrl+B, then D
# Reattach later: tmux attach -t agent
```

### Option B: start.sh (one command)

```bash
chmod +x start.sh
./start.sh
```

This starts both the MLX server and the agent in the background. Logs go to `agent.log`.

---

## Security

🔴 **Never share these files:**

| File | Why |
|---|---|
| `my_telegram.session` | Full access to your Telegram account |
| `.env` | Contains your API credentials |
| `voice_profile.json` | Your writing patterns |
| `agent_state.json` | Pending messages, usernames |

🟢 **Safe to share:** `dm_agent.py`, `requirements.txt`, `setup.sh`, `.env.example`, `README.md`

> **The session file is your Telegram login.** Anyone with this file can read your messages, send messages as you, and access your account. Treat it like a password. If compromised, go to Telegram → Settings → Devices → terminate that session.

---

## Troubleshooting

### "MLX server not running!"

Make sure the MLX server is running in a separate terminal:
```bash
mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080
```

### "Invalid TELEGRAM_API_ID"

Your `.env` has a wrong API ID. It must be a **number** (like `12345678`), not an IP address. Get it from [my.telegram.org](https://my.telegram.org) → API development tools.

### Agent replies instantly (looks like a bot)

Check your `.env`:
```bash
COOLDOWN_SECONDS=8       # not 0
TYPING_DELAY_MIN=1.5     # not 0
TYPING_DELAY_MAX=4.5     # not 0.15
```

### Agent replies to old messages on startup

Normal on first boot. Set `IGNORE_OLDER_THAN=120` (ignores messages older than 2 minutes). Already set by default.

### "FloodWaitError: A wait of X seconds is required"

You're hitting Telegram's rate limit. The agent handles this automatically (waits and retries). If persistent, increase `COOLDOWN_SECONDS`.

### Voice profile has 0 samples

You need at least 30 outgoing messages across your chats. The agent scans your existing conversations — if your account is new or you rarely text first, there won't be enough data. Use the agent for a few days, then run `/rebuildvoice`.

### Replies are too long / formal

The AI model affects quality. Qwen3-8B sometimes over-explains. Try:
1. Make sure `POLISH_REPLY_ENABLED=true` (second pass shortens replies)
2. Try `Qwen3-30B-A3B-4bit` for better instruction following
3. Adjust the personality in `/personality casual`

---

## FAQ

**Q: Will the other person know it's AI?**
No. Messages come from your real account with your real name and profile picture. There's no "bot" label, no "via Bot" tag. It looks identical to you typing manually. The typing indicator even shows before sending.

**Q: Does this use ChatGPT / OpenAI / Claude API?**
No. Everything runs locally on your Mac using MLX + open-source models. Zero API costs. Your conversations are never sent to any cloud service.

**Q: Can I use this on Linux / Windows?**
The agent itself (`dm_agent.py`) runs on any OS with Python 3.10+. But MLX is Apple Silicon only. On Linux/Windows, you'd need to swap MLX for another local LLM server (like `llama.cpp` server or `ollama`). Set `MLX_SERVER_URL` to point to your server and it works the same.

**Q: Can I get banned from Telegram?**
Using the Telegram Client API (Telethon) is allowed by Telegram's terms as long as you're not spamming or abusing it. The agent has cooldowns, typing delays, and rate limiting specifically to avoid triggering anti-spam. Thousands of people use Telethon-based tools daily without issues.

**Q: Can it reply to group chats?**
Not yet. Currently DM-only. Group chat support may come in a future version.

**Q: How much RAM does it use?**
The Python agent uses ~50-100MB. The AI model uses 4-8GB depending on model size. Total: ~5-8GB for the whole stack, leaving headroom on a 16GB Mac.

---

## Roadmap

- [ ] Group chat support
- [ ] Voice message transcription + response
- [ ] Image description (describe photos before replying)
- [ ] Scheduled messages
- [ ] Web dashboard for monitoring
- [ ] Conversation export / backup
- [ ] Ollama / llama.cpp backend support

---

## Contributing

Pull requests welcome. If you add a feature, test it with at least 2 real conversations before submitting.

---

## License

MIT — do whatever you want with it.

---

<div align="center">

**Built with 🍏 MLX, 🐍 Python, and ☕ too much coffee.**

**Star ⭐ if this saved you from replying to DMs at 3am.**

</div>
