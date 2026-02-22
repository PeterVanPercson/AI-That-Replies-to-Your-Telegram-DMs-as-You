#!/usr/bin/env bash
set -euo pipefail

# ══════════════════════════════════════════════════════════
#  Telegram DM Agent — Start Script
#  Starts both the MLX server and the agent
# ══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODEL="${MLX_MODEL_NAME:-mlx-community/Qwen3-8B-4bit}"
PORT="${MLX_PORT:-8080}"
LOG_FILE="$SCRIPT_DIR/agent.log"

BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Activate venv
if [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
else
    echo "No venv found. Run setup.sh first."
    exit 1
fi

# Check if MLX server is already running
if curl -s "http://127.0.0.1:$PORT/v1/models" &>/dev/null; then
    echo -e "${GREEN}✓${NC} MLX server already running on port $PORT"
else
    echo -e "${CYAN}→${NC} Starting MLX server ($MODEL on port $PORT)..."
    mlx_lm.server --model "$MODEL" --port "$PORT" &>/dev/null &
    MLX_PID=$!
    echo "$MLX_PID" > "$SCRIPT_DIR/.mlx.pid"

    # Wait for server to be ready
    echo -n "  Waiting for model to load"
    for i in $(seq 1 60); do
        if curl -s "http://127.0.0.1:$PORT/v1/models" &>/dev/null; then
            echo ""
            echo -e "  ${GREEN}✓${NC} MLX server ready (PID: $MLX_PID)"
            break
        fi
        echo -n "."
        sleep 2
    done

    if ! curl -s "http://127.0.0.1:$PORT/v1/models" &>/dev/null; then
        echo ""
        echo "MLX server failed to start. Check if model is downloaded."
        exit 1
    fi
fi

# Start the agent
echo -e "${CYAN}→${NC} Starting DM agent..."
echo -e "  Logs: ${CYAN}$LOG_FILE${NC}"
echo -e "  Stop: ${CYAN}Ctrl+C${NC} or ${CYAN}./stop.sh${NC}"
echo ""

python dm_agent.py 2>&1 | tee -a "$LOG_FILE"
