# burnctl — canonical DB schema

Authoritative reference for every column in `data/usage.db`. If code references a name not in this document, it is a bug.

Extracted from `data/usage.db` on 2026-04-20 (v4.0.9).

## Known drift — frozen list

| ❌ Wrong name | ✅ Real name | Table |
|---|---|---|
| `token_cost` | `cost_usd` | `sessions` |
| `token_cost` | `token_cost` | `waste_events` (this column **is** `token_cost` — the name differs per table) |
| `start_time` | `timestamp` | `sessions`, `lifecycle_events`, `waste_events (detected_at)`, `claude_ai_usage (timestamp)` |
| `end_time` | *(no such column — derive from `MAX(timestamp)` per `session_id`)* | — |
| `waste_type` | `pattern_type` | `waste_events` |
| `fix_id` | `id` | `fixes` (FK on `fix_measurements.fix_id`) |
| `browser_activity` table | `claude_ai_snapshots` table | — |
| `baseline_waste_events` | *(not a column — stored inside `baseline_json` blob)* | `fixes` |
| `measured_waste_events` | *(not a column — computed at runtime)* | — |

## Tables

### sessions
One row per Claude Code turn. 24k+ rows typical.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `session_id` | TEXT | UUID from the JSONL filename |
| `timestamp` | INTEGER | Unix seconds, turn start |
| `project` | TEXT | Dir-derived name. May need `_remap_project_name()` remap |
| `account` | TEXT | `personal_max`, `work_pro`, etc. |
| `model` | TEXT | `claude-opus`, `claude-sonnet`, … |
| `input_tokens` | INTEGER | |
| `output_tokens` | INTEGER | |
| `cache_read_tokens` | INTEGER | Cache hits |
| `cache_creation_tokens` | INTEGER | Cache writes (CLAUDE.md + MCP + tools) |
| `cost_usd` | REAL | Turn cost — **NOT** `token_cost` |
| `source_path` | TEXT | Absolute JSONL path (local only) |
| `compaction_detected` | INTEGER | 0/1 |
| `tokens_before_compact` | INTEGER | |
| `tokens_after_compact` | INTEGER | |
| `is_subagent` | INTEGER | 0/1 |
| `parent_session_id` | TEXT | For subagents, points at the spawning session |
| `compact_count` | INTEGER | Compactions in this session so far |
| `subagent_count` | INTEGER | Subagents spawned this session so far |
| `compact_timing_pct` | REAL | Where in the window compaction hit |
| `tool_call_count` | INTEGER | |
| `bash_count` | INTEGER | |
| `read_count` | INTEGER | |
| `write_count` | INTEGER | |
| `grep_count` | INTEGER | |
| `mcp_count` | INTEGER | |
| `max_output_tokens` | INTEGER | |
| `work_classification` | TEXT | `mechanical` / `reasoning` |
| `prompt_quality` | TEXT | `terse` / `normal` / `verbose` |

### waste_events
One row per detected waste pattern per session.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `session_id` | TEXT | |
| `project` | TEXT | |
| `account` | TEXT | |
| `pattern_type` | TEXT | **NOT** `waste_type`. Values: `retry_error`, `dead_end`, `file_reread`, `oververbose_tool`, `browser_wall`, `cost_outlier`, `compaction_thrash`, etc. |
| `severity` | TEXT | `low` / `medium` / `high` / `critical` |
| `turn_count` | INTEGER | How many turns the pattern spanned |
| `token_cost` | REAL | Tokens wasted — this column **is** `token_cost` on this table |
| `detected_at` | INTEGER | Unix seconds |
| `detail_json` | TEXT | Pattern-specific context |

### fixes
One row per proposed/applied fix.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | FK target for `fix_measurements.fix_id`. **NOT** `fix_id` on this table |
| `created_at` | INTEGER | |
| `project` | TEXT | |
| `waste_pattern` | TEXT | Mirrors `waste_events.pattern_type` |
| `title` | TEXT | Dedup key with `(project, fix_type, title)` for AI-generated fixes |
| `fix_type` | TEXT | `claude_md`, `claude_md_rule`, `settings_json`, `prompt`, `architecture` |
| `fix_detail` | TEXT | The actual text to apply |
| `baseline_json` | TEXT | Pre-fix metrics snapshot |
| `status` | TEXT | `proposed` / `measuring` / `confirmed` / `rejected` |
| `generated_by` | TEXT | `burnctl` (AI) or user |
| `generation_prompt` | TEXT | |
| `generation_response` | TEXT | |
| `applied_to_path` | TEXT | File the fix was written to |
| `waste_event_id` | INTEGER | Which waste_events row triggered this fix |
| `applied_at` | INTEGER | |

### fix_measurements
Before/after deltas per fix, captured over time.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `fix_id` | INTEGER | FK → `fixes.id` |
| `measured_at` | INTEGER | |
| `metrics_json` | TEXT | Raw metrics snapshot |
| `delta_json` | TEXT | Computed delta vs baseline |
| `verdict` | TEXT | `improving` / `worsened` / `no_change` |

### sessions-adjacent telemetry

| Table | Purpose |
|---|---|
| `lifecycle_events` | Compaction + context-overflow events with `timestamp` (NOT `start_time`) |
| `compliance_events` | CLAUDE.md rule violations |
| `skill_usage` | Skill loads per session (JIT analysis) |
| `insights` | Generated insights (22 rules today) |
| `alerts` | User-visible alerts |
| `waste_events` | See above |
| `mcp_warnings` | MCP integration issues |

### Browser sync (claude.ai window utilization)

| Table | Purpose | Notes |
|---|---|---|
| `claude_ai_snapshots` | Point-in-time polls of claude.ai window. Source of truth for `work-timeline`. | **Use this, NOT `browser_activity` (no such table)** |
| `claude_ai_accounts` | Per-account session keys + poll status | |
| `claude_ai_usage` | **DEPRECATED — 0 rows, never written.** Superseded by `claude_ai_snapshots`. Scheduled for removal. | |
| `window_burns` | Rolling 5h window burns derived from snapshots | |

### Accounts + projects

| Table | Purpose |
|---|---|
| `accounts` | Per-account config (plan, budget, token limit) |
| `account_projects` | Project-to-account assignments via keyword matching |
| `daily_snapshots` | Daily rollups for trends |

### Operational

| Table | Purpose |
|---|---|
| `scan_state` | JSONL incremental-scan cursor |
| `settings` | Key-value runtime settings |
| `generated_hooks` | Auto-generated shell hooks |

## Rules for new code

1. Open the DB via the canonical pattern — `overhead_audit.py::load_db()`. Only two candidates: `./data/usage.db`, `~/.burnctl/data/usage.db`. No maintainer paths.
2. When in doubt about a column name, `PRAGMA table_info(<table>)` — don't guess from training data.
3. Project names visible to the user go through `_remap_project_name()` in `server.py`.
4. The `waste_events.token_cost` vs `sessions.cost_usd` naming is historical. Do not rename either — downstream queries depend on both.
5. Session "duration" is not stored — compute from `MIN/MAX(timestamp)` per `session_id`.
