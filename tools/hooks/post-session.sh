#!/bin/bash
# burnctl post-session hook
# Add to ~/.claude/settings.json PostToolUse hooks
# Records session cost after each Claude Code session

BURNCTL_DIR="${BURNCTL_DIR:-$HOME/.burnctl}"
DASHBOARD_URL="${BURNCTL_URL:-http://localhost:8080}"

# Trigger a scan to pick up the new session
KEY=$(python3 "$BURNCTL_DIR/cli.py" keys 2>/dev/null | grep dashboard_key | awk '{print $3}')
curl -s -X POST "$DASHBOARD_URL/api/scan" \
  -H "X-Dashboard-Key: $KEY" \
  > /dev/null 2>&1

echo "[burnctl] Session recorded"
