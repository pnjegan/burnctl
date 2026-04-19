# burnctl

**Real-time burn-rate monitor for Claude Code.**
Tokens/min, $/hr, retry-loop detection, waste-pattern analysis — local-only,
zero pip dependencies.

> Renamed and rebooted from `claudash` 3.x. Same engine; sharper focus.

![Dashboard screenshot](docs/screenshots/dashboard.png)

---

## What it does

```bash
burnctl statusline
# ⚡ 142t/min | $0.84/hr | 5hr: 12.3k tok / $0.41 | Loop: ✓
```

Reads the JSONL files Claude Code writes locally to `~/.claude/projects/`,
parses sessions into a SQLite DB, and surfaces:

- **Live burn rate** — tokens/min and $/min observed in the last 5 minutes
- **5-hour rolling block** — observed token + cost totals (no quota guess; see note below)
- **Retry-loop detection** — flags any project firing 5+ sessions in 10 min with avg gap < 60s
- **Waste-pattern analysis** — repeated reads, stuck loops, late compactions, cost outliers (22 detectors)
- **Fix tracker** — capture a baseline, apply a CLAUDE.md rule, re-measure outcomes
- **Web dashboard** — http://localhost:8080 with charts + per-project breakdown

### A note on rate-limit math

Anthropic does **not** publish per-plan token-budget limits for the 5-hour
block. burnctl deliberately does not invent an "X% of limit used" number,
because making one up would mislead you. We show observed local burn and
let you apply your own intuition.

---

## vs ccusage

|                              | ccusage | burnctl |
|------------------------------|:-------:|:-------:|
| Token + cost reports         |   ✅    |   ✅    |
| 5-hour block totals (observed) |   ✅    |   ✅    |
| Live tokens/min + $/hr       |   ❌    |   ✅    |
| Retry-loop detection         |   ❌    |   ✅    |
| Web dashboard                |   ❌    |   ✅    |
| Waste-pattern detection (22 rules) |   ❌    |   ✅    |
| Fix tracker (before/after)   |   ❌    |   ✅    |
| Statusline hook output       |   ❌    |   ✅    |
| Inferred ETA to limit        |   —    |   —    |

(Neither tool can show a real ETA-to-limit because Anthropic does not publish the limit. ccusage estimates it; we don't.)

---

## Install

### npx (no install)
```bash
npx burnctl@latest
```

### npm global
```bash
npm install -g burnctl
burnctl dashboard
```

### Homebrew (macOS / Linux)
```bash
brew tap pnjegan/burnctl
brew install burnctl
burnctl dashboard
```

### Git clone
```bash
git clone https://github.com/pnjegan/burnctl.git
cd burnctl
python3 cli.py dashboard
```

---

## Requirements

| Requirement | Why | Check |
|---|---|---|
| Claude Code | burnctl reads its session files | `claude --version` |
| Python 3.8+ | Engine is Python (no pip deps) | `python3 --version` |
| Node.js 16+ | Required only for npx / npm install | `node --version` |

Run at least one Claude Code session before launching burnctl — sessions are
stored in:
- macOS / Linux: `~/.claude/projects/`
- Windows (WSL2): `/mnt/c/Users/<username>/AppData/Roaming/Claude/projects/`

---

## Common commands

```bash
burnctl dashboard       # web UI on http://localhost:8080
burnctl burnrate        # tokens/min, $/min, $/hr (last 5 min)
burnctl loops           # show retry-loop activity in last 10 min
burnctl block           # 5-hour rolling block totals
burnctl statusline      # one-line output for Claude Code statusline hook
burnctl scan            # one-shot scan of new JSONL sessions
burnctl waste           # waste-pattern detector summary
burnctl fixes           # list recorded fixes + verdict
burnctl backup          # hot-copy DB + JSON fixes export
```

Full command list: `burnctl --help`.

---

## Statusline hook

Add to `~/.claude/settings.json` (or per-project `.claude/settings.json`):

```json
{
  "statusLine": {
    "type": "command",
    "command": "burnctl statusline"
  }
}
```

Then your Claude Code statusline shows live burn whenever you're working.

---

## Privacy

- **Nothing leaves your machine.** No telemetry, no analytics, no cloud sync.
- DB lives at `data/usage.db` (mode 0600 on Unix).
- burnctl reads session JSONL for token counts and tool-call metadata only —
  it does not store conversation content.
- API keys you paste for fix-generation are stored locally in the same SQLite DB.

For team / cloud deployment guidance: [SECURITY.md](SECURITY.md).

---

## Troubleshooting

**Dashboard shows no data**
Run `burnctl scan`. Confirm `~/.claude/projects/` contains `.jsonl` files.

**Port 8080 already in use**
```bash
burnctl dashboard --port 9090
```

**Python not found**
```bash
brew install python@3.11           # macOS
sudo apt install python3            # Ubuntu / Debian
```

**WSL2 can't find Windows sessions**
burnctl looks at `/mnt/c/Users/<username>/AppData/Roaming/Claude/projects/`.
Confirm the path with `ls /mnt/c/Users/`.

**Upgrading from `@jeganwrites/claudash` 3.x**
- Existing DB at `data/usage.db` keeps working unchanged
- Env vars: `BURNCTL_VPS_IP`, `BURNCTL_VPS_PORT`, `BURNCTL_BACKUP_DIR`
  (legacy `CLAUDASH_*` variants still honored)
- `/tmp/claudash.pid` → `/tmp/burnctl.pid` — kill the old daemon if it's still running
- MCP server key in `~/.claude/settings.json` renames from `"claudash"` to `"burnctl"`
- Backup default path stays `/root/backups/claudash` so existing rclone offsite
  sync keeps working through the rebrand

---

## Contributing

PRs welcome. Especially:
- Native Windows support (without WSL2)
- More waste-pattern detectors
- Statusline output formats for other shells / editors

```bash
git clone https://github.com/pnjegan/burnctl.git
cd burnctl
python3 cli.py dashboard   # no install needed
```

---

## License

MIT — fork it, ship it, build on it.

---

*All data stays on your machine. Zero pip dependencies. One command install.*
