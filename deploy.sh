#!/bin/bash
# burnctl deploy script
# Run after every npm publish to update the live dashboard.
#
# pm2 keeps the daemon's Python process alive in memory; on-disk code
# changes (server.py, cli.py, new *_audit.py modules, _version.py via
# package.json bumps) do not take effect until pm2 restarts the process.
# This script restarts and verifies.

set -e

PROC=burnctl
URL=http://localhost:8080/api/health

echo "=== burnctl deploy ==="
echo "Restarting pm2 process: $PROC"
pm2 restart "$PROC" >/dev/null

EXPECTED=$(python3 -c "import json; print(json.load(open('/root/projects/burnctl/package.json'))['version'])")
echo "Expected version (package.json): $EXPECTED"

# Poll /api/health for up to 30s — daemon needs scanner + DB init time
LIVE="unreachable"
for i in $(seq 1 15); do
  sleep 2
  LIVE=$(curl -s --max-time 2 "$URL" | python3 -c "import json,sys; print(json.load(sys.stdin).get('version','?'))" 2>/dev/null || echo "unreachable")
  if [ "$LIVE" = "$EXPECTED" ]; then break; fi
done
echo "Live version (/api/health):     $LIVE   (after ${i} polls × 2s)"

if [ "$EXPECTED" = "$LIVE" ]; then
  echo "✓ Deploy OK"
  pm2 show "$PROC" 2>/dev/null | grep -E "status|uptime|restarts" | head -3
  exit 0
else
  echo "✗ Version mismatch — daemon did not pick up new code."
  echo "Diagnose:"
  echo "  pm2 logs $PROC --lines 30"
  echo "  pm2 restart $PROC --update-env   # force full reload"
  exit 1
fi
