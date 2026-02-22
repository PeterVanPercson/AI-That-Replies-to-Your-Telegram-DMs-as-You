#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════
#  Telegram DM Agent — Setup Script
# ══════════════════════════════════════════════════════════

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}  🤖 Telegram DM Agent — Setup${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo ""

# ── Check Python ──
echo -e "${CYAN}[1/5]${NC} Checking Python..."
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        echo -e "  ${GREEN}✓${NC} Python $PY_VERSION"
    else
        echo -e "  ${RED}✗${NC} Python $PY_VERSION found but 3.10+ required"
        echo "  Install: brew install python@3.12"
        exit 1
    fi
else
    echo -e "  ${RED}✗${NC} Python 3 not found"
    echo "  Install: brew install python@3.12"
    exit 1
fi

# ── Create virtual environment ──
echo -e "${CYAN}[2/5]${NC} Creating virtual environment..."
if [ -d "venv" ]; then
    echo -e "  ${YELLOW}→${NC} venv already exists, skipping"
else
    python3 -m venv venv
    echo -e "  ${GREEN}✓${NC} Created venv/"
fi
source venv/bin/activate

# ── Install dependencies ──
echo -e "${CYAN}[3/5]${NC} Installing dependencies..."
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
echo -e "  ${GREEN}✓${NC} telethon, httpx, python-dotenv installed"

# ── Check MLX ──
echo -e "${CYAN}[4/5]${NC} Checking MLX..."
if pip show mlx-lm &>/dev/null; then
    MLX_VER=$(pip show mlx-lm | grep Version | awk '{print $2}')
    echo -e "  ${GREEN}✓${NC} mlx-lm $MLX_VER"
else
    echo -e "  ${YELLOW}→${NC} mlx-lm not installed"
    read -p "  Install mlx-lm now? (recommended) [Y/n]: " INSTALL_MLX
    if [[ "${INSTALL_MLX:-Y}" =~ ^[Yy]$ ]]; then
        pip install --quiet mlx-lm
        echo -e "  ${GREEN}✓${NC} mlx-lm installed"
    else
        echo -e "  ${YELLOW}→${NC} Skipped. Install later: pip install mlx-lm"
    fi
fi

# ── Setup .env ──
echo -e "${CYAN}[5/5]${NC} Configuring .env..."
if [ -f ".env" ]; then
    echo -e "  ${YELLOW}→${NC} .env already exists, skipping"
    echo -e "  ${YELLOW}→${NC} Edit manually: nano .env"
else
    cp .env.example .env
    echo ""
    echo -e "  ${BOLD}Enter your Telegram API credentials${NC}"
    echo -e "  (Get them from ${CYAN}https://my.telegram.org${NC} → API development tools)"
    echo ""

    read -p "  API ID (number): " API_ID
    read -p "  API Hash (hex string): " API_HASH

    if [ -n "$API_ID" ] && [ -n "$API_HASH" ]; then
        # macOS sed requires empty string after -i
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s/^TELEGRAM_API_ID=$/TELEGRAM_API_ID=$API_ID/" .env
            sed -i '' "s/^TELEGRAM_API_HASH=$/TELEGRAM_API_HASH=$API_HASH/" .env
        else
            sed -i "s/^TELEGRAM_API_ID=$/TELEGRAM_API_ID=$API_ID/" .env
            sed -i "s/^TELEGRAM_API_HASH=$/TELEGRAM_API_HASH=$API_HASH/" .env
        fi
        echo -e "  ${GREEN}✓${NC} Saved to .env"
    else
        echo -e "  ${YELLOW}→${NC} Skipped. Edit .env manually: nano .env"
    fi
fi

# ── Done ──
echo ""
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ Setup complete!${NC}"
echo -e "${BOLD}══════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${BOLD}Next steps:${NC}"
echo ""
echo -e "  1. Start the AI server (in a separate terminal):"
echo -e "     ${CYAN}source venv/bin/activate${NC}"
echo -e "     ${CYAN}mlx_lm.server --model mlx-community/Qwen3-8B-4bit --port 8080${NC}"
echo ""
echo -e "  2. Start the agent (in another terminal):"
echo -e "     ${CYAN}source venv/bin/activate${NC}"
echo -e "     ${CYAN}python dm_agent.py${NC}"
echo ""
echo -e "  3. First run: enter your phone number + verification code"
echo ""
echo -e "  4. Control the agent from Telegram → Saved Messages → type ${CYAN}/help${NC}"
echo ""
