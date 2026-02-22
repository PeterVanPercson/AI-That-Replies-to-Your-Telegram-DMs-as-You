#!/usr/bin/env bash

# ══════════════════════════════════════════════════════════
#  Telegram DM Agent — Stop Script
# ══════════════════════════════════════════════════════════

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping DM agent..."

# Kill agent (Python process)
pkill -f "python.*dm_agent.py" 2>/dev/null && echo "✓ Agent stopped" || echo "→ Agent not running"

# Kill MLX server
if [ -f "$SCRIPT_DIR/.mlx.pid" ]; then
    MLX_PID=$(cat "$SCRIPT_DIR/.mlx.pid")
    if kill -0 "$MLX_PID" 2>/dev/null; then
        kill "$MLX_PID"
        echo "✓ MLX server stopped (PID: $MLX_PID)"
    fi
    rm -f "$SCRIPT_DIR/.mlx.pid"
else
    pkill -f "mlx_lm.server" 2>/dev/null && echo "✓ MLX server stopped" || echo "→ MLX server not running"
fi

echo "Done."
