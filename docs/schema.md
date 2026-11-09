<!-- Auto-generated from the repo by a deterministic extractor: CREATE TABLE
     (balanced-paren scan, db.py parsed first), literal ALTER TABLE ADD COLUMN,
     and the `for col, typedef in [...]` migration loops in db.py. Verified
     column-for-column against the live DB. Regenerate, do not hand-edit. -->
# burnctl — canonical DB schema

Extracted at commit `73de957` on 2026-11-09.

**24 tables.** The database is authoritative; code bends to it.

> **`db.py` is not the whole schema.** Most columns arrive through `ALTER TABLE`
> migration loops rather than the original `CREATE TABLE`, so reading a
> `CREATE TABLE` block alone understates a table by as much as 20 columns
> (`sessions`). Four further tables exist in a live DB that `db.py` never creates
> — see the section below.

## Tables

| Table | Columns | Created in |
|---|---|---|
| [`account_emails`](#account_emails) | 5 | `db.py` |
| [`account_ignore_list`](#account_ignore_list) | 4 | `db.py` |
| [`account_projects`](#account_projects) | 4 | `db.py` |
| [`accounts`](#accounts) | 15 | `db.py` |
| [`alerts`](#alerts) | 6 | `db.py` |
| [`baseline_readings`](#baseline_readings) | 5 | `db.py` |
| [`browser_chat_daily`](#browser_chat_daily) | 13 | `db.py` |
| [`browser_chat_sessions`](#browser_chat_sessions) | 10 | `db.py` |
| [`browser_samples`](#browser_samples) | 15 | `db.py` |
| [`claude_ai_accounts`](#claude_ai_accounts) | 12 | `db.py` |
| [`claude_ai_snapshots`](#claude_ai_snapshots) | 16 | `db.py` |
| [`claude_ai_usage`](#claude_ai_usage) | 10 | `db.py` |
| [`daily_snapshots`](#daily_snapshots) | 8 | `db.py` |
| [`extension_connections`](#extension_connections) | 6 | `db.py` |
| [`fix_measurements`](#fix_measurements) | 6 | `db.py` |
| [`fixes`](#fixes) | 16 | `db.py` |
| [`insights`](#insights) | 8 | `db.py` |
| [`lifecycle_events`](#lifecycle_events) | 8 | `db.py` |
| [`mcp_warnings`](#mcp_warnings) | 9 | `db.py` |
| [`scan_state`](#scan_state) | 4 | `db.py` |
| [`sessions`](#sessions) | 31 | `db.py` |
| [`settings`](#settings) | 4 | `db.py` |
| [`waste_events`](#waste_events) | 10 | `db.py` |
| [`window_burns`](#window_burns) | 8 | `db.py` |

## account_emails

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_id` | TEXT NOT NULL | CREATE TABLE |
| `email` | TEXT UNIQUE NOT NULL | CREATE TABLE |
| `is_primary` | INTEGER DEFAULT 0 | CREATE TABLE |
| `created_at` | INTEGER NOT NULL | CREATE TABLE |

## account_ignore_list

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_email` | TEXT UNIQUE NOT NULL | CREATE TABLE |
| `reason` | TEXT | CREATE TABLE |
| `created_at` | INTEGER NOT NULL | CREATE TABLE |

## account_projects

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_id` | TEXT | CREATE TABLE |
| `project_name` | TEXT | CREATE TABLE |
| `keywords` | TEXT | CREATE TABLE |

Table constraints: `UNIQUE(account_id, project_name)`

## accounts

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_id` | TEXT UNIQUE | CREATE TABLE |
| `label` | TEXT | CREATE TABLE |
| `plan` | TEXT | CREATE TABLE |
| `monthly_cost_usd` | REAL | CREATE TABLE |
| `window_token_limit` | INTEGER | CREATE TABLE |
| `color` | TEXT | CREATE TABLE |
| `data_paths` | TEXT | CREATE TABLE |
| `active` | INTEGER DEFAULT 1 | CREATE TABLE |
| `created_at` | INTEGER | CREATE TABLE |
| `daily_budget_usd` | REAL DEFAULT 0 | migration in `db.py` |
| `source` | TEXT DEFAULT 'manual' | migration in `db.py` |
| `auto_tag` | INTEGER DEFAULT 0 | migration in `db.py` |
| `display_label` | TEXT | migration in `db.py` |
| `archived_at` | INTEGER | migration in `db.py` |

## alerts

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `created_at` | INTEGER | CREATE TABLE |
| `level` | TEXT | CREATE TABLE |
| `project` | TEXT | CREATE TABLE |
| `message` | TEXT | CREATE TABLE |
| `seen` | INTEGER DEFAULT 0 | CREATE TABLE |

## baseline_readings

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `timestamp` | TEXT NOT NULL | CREATE TABLE |
| `total_tokens` | INTEGER NOT NULL | CREATE TABLE |
| `sources_json` | TEXT NOT NULL | CREATE TABLE |
| `snapshot_date` | TEXT NOT NULL | CREATE TABLE |

## browser_chat_daily

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `date_local` | TEXT NOT NULL | CREATE TABLE |
| `chat_uuid` | TEXT NOT NULL | CREATE TABLE |
| `account_id` | TEXT | CREATE TABLE |
| `account_email` | TEXT | CREATE TABLE |
| `sample_count` | INTEGER DEFAULT 0 | CREATE TABLE |
| `input_chars` | INTEGER DEFAULT 0 | CREATE TABLE |
| `output_chars` | INTEGER DEFAULT 0 | CREATE TABLE |
| `cost_usd` | REAL | CREATE TABLE |
| `first_ts` | INTEGER | CREATE TABLE |
| `last_ts` | INTEGER | CREATE TABLE |
| `model` | TEXT | CREATE TABLE |
| `rolled_up_at` | INTEGER NOT NULL | CREATE TABLE |

Table constraints: `UNIQUE(chat_uuid, date_local)`

## browser_chat_sessions

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `chat_uuid` | TEXT PRIMARY KEY | CREATE TABLE |
| `title` | TEXT NOT NULL | CREATE TABLE |
| `account` | TEXT NOT NULL | CREATE TABLE |
| `browser` | TEXT NOT NULL | CREATE TABLE |
| `first_visit` | INTEGER NOT NULL | CREATE TABLE |
| `last_visit` | INTEGER NOT NULL | CREATE TABLE |
| `duration_min` | INTEGER NOT NULL | CREATE TABLE |
| `page_visits` | INTEGER NOT NULL DEFAULT 1 | CREATE TABLE |
| `pushed_at` | INTEGER NOT NULL DEFAULT (strftime('%s','now')) | CREATE TABLE |
| `cost_est_usd` | REAL | CREATE TABLE |

## browser_samples

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `connection_id` | INTEGER REFERENCES extension_connections(id) | CREATE TABLE |
| `message_uuid` | TEXT UNIQUE | CREATE TABLE |
| `chat_uuid` | TEXT NOT NULL | CREATE TABLE |
| `account_email` | TEXT | CREATE TABLE |
| `account_id` | TEXT | CREATE TABLE |
| `user_override_account_id` | TEXT | CREATE TABLE |
| `role` | TEXT | CREATE TABLE |
| `model` | TEXT | CREATE TABLE |
| `input_chars` | INTEGER DEFAULT 0 | CREATE TABLE |
| `output_chars` | INTEGER DEFAULT 0 | CREATE TABLE |
| `cost_usd` | REAL | CREATE TABLE |
| `timestamp` | INTEGER NOT NULL | CREATE TABLE |
| `date_local` | TEXT NOT NULL | CREATE TABLE |
| `received_at` | INTEGER NOT NULL | CREATE TABLE |

## claude_ai_accounts

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_id` | TEXT UNIQUE | CREATE TABLE |
| `label` | TEXT | CREATE TABLE |
| `org_id` | TEXT | CREATE TABLE |
| `session_key` | TEXT | CREATE TABLE |
| `plan` | TEXT | CREATE TABLE |
| `status` | TEXT DEFAULT 'unconfigured' | CREATE TABLE |
| `last_polled` | INTEGER | CREATE TABLE |
| `last_error` | TEXT | CREATE TABLE |
| `created_at` | INTEGER | CREATE TABLE |
| `updated_at` | INTEGER | CREATE TABLE |
| `mac_sync_mode` | INTEGER DEFAULT 0 | migration in `db.py` |

## claude_ai_snapshots

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_id` | TEXT | CREATE TABLE |
| `polled_at` | INTEGER | CREATE TABLE |
| `window_start` | INTEGER | CREATE TABLE |
| `window_end` | INTEGER | CREATE TABLE |
| `tokens_used` | INTEGER | CREATE TABLE |
| `tokens_limit` | INTEGER | CREATE TABLE |
| `messages_used` | INTEGER | CREATE TABLE |
| `messages_limit` | INTEGER | CREATE TABLE |
| `pct_used` | REAL | CREATE TABLE |
| `plan` | TEXT | CREATE TABLE |
| `raw_response` | TEXT | CREATE TABLE |
| `five_hour_utilization` | REAL DEFAULT 0 | migration in `db.py` |
| `seven_day_utilization` | REAL DEFAULT 0 | migration in `db.py` |
| `extra_credits_used` | REAL DEFAULT 0 | migration in `db.py` |
| `extra_credits_limit` | REAL DEFAULT 0 | migration in `db.py` |

Table constraints: `UNIQUE(account_id, polled_at)`

## claude_ai_usage

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account_label` | TEXT | CREATE TABLE |
| `timestamp` | INTEGER | CREATE TABLE |
| `tokens_used` | INTEGER | CREATE TABLE |
| `tokens_limit` | INTEGER | CREATE TABLE |
| `window_pct` | REAL | CREATE TABLE |
| `window_start` | INTEGER | CREATE TABLE |
| `window_end` | INTEGER | CREATE TABLE |
| `status` | TEXT DEFAULT 'ok' | CREATE TABLE |
| `raw_json` | TEXT | CREATE TABLE |

## daily_snapshots

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `date` | TEXT | CREATE TABLE |
| `account` | TEXT | CREATE TABLE |
| `project` | TEXT | CREATE TABLE |
| `total_tokens` | INTEGER | CREATE TABLE |
| `total_cost_usd` | REAL | CREATE TABLE |
| `cache_hit_rate` | REAL | CREATE TABLE |
| `session_count` | INTEGER | CREATE TABLE |

Table constraints: `UNIQUE(date, account, project)`

## extension_connections

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `token_hash` | TEXT UNIQUE NOT NULL | CREATE TABLE |
| `connection_label` | TEXT | CREATE TABLE |
| `created_at` | INTEGER NOT NULL | CREATE TABLE |
| `last_seen_at` | INTEGER | CREATE TABLE |
| `revoked_at` | INTEGER | CREATE TABLE |

## fix_measurements

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `fix_id` | INTEGER REFERENCES fixes(id) | CREATE TABLE |
| `measured_at` | INTEGER | CREATE TABLE |
| `metrics_json` | TEXT | CREATE TABLE |
| `delta_json` | TEXT | CREATE TABLE |
| `verdict` | TEXT | CREATE TABLE |

## fixes

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `created_at` | INTEGER | CREATE TABLE |
| `project` | TEXT | CREATE TABLE |
| `waste_pattern` | TEXT | CREATE TABLE |
| `title` | TEXT | CREATE TABLE |
| `fix_type` | TEXT | CREATE TABLE |
| `fix_detail` | TEXT | CREATE TABLE |
| `baseline_json` | TEXT | CREATE TABLE |
| `status` | TEXT DEFAULT 'applied' | CREATE TABLE |
| `generated_by` | TEXT DEFAULT 'human' | migration in `db.py` |
| `generation_prompt` | TEXT | migration in `db.py` |
| `generation_response` | TEXT | migration in `db.py` |
| `applied_to_path` | TEXT | migration in `db.py` |
| `waste_event_id` | INTEGER | migration in `db.py` |
| `baseline_corrupted` | INTEGER DEFAULT 0 | migration in `db.py` |
| `applied_at` | INTEGER | migration in `db.py` |

## insights

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `created_at` | INTEGER | CREATE TABLE |
| `account` | TEXT | CREATE TABLE |
| `project` | TEXT | CREATE TABLE |
| `insight_type` | TEXT | CREATE TABLE |
| `message` | TEXT | CREATE TABLE |
| `detail_json` | TEXT | CREATE TABLE |
| `dismissed` | INTEGER DEFAULT 0 | CREATE TABLE |

## lifecycle_events

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `session_id` | TEXT NOT NULL | CREATE TABLE |
| `project` | TEXT NOT NULL | CREATE TABLE |
| `event_type` | TEXT NOT NULL | CREATE TABLE |
| `timestamp` | INTEGER NOT NULL | CREATE TABLE |
| `context_pct_at_event` | REAL | CREATE TABLE |
| `event_metadata` | TEXT | CREATE TABLE |
| `created_at` | INTEGER DEFAULT (strftime('%s','now')) | CREATE TABLE |

Table constraints: `UNIQUE(session_id, event_type, timestamp)`

## mcp_warnings

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `project` | TEXT NOT NULL | CREATE TABLE |
| `session_id` | TEXT | CREATE TABLE |
| `warning_type` | TEXT NOT NULL | CREATE TABLE |
| `message` | TEXT NOT NULL | CREATE TABLE |
| `severity` | TEXT NOT NULL DEFAULT 'amber' | CREATE TABLE |
| `created_at` | INTEGER DEFAULT (strftime('%s','now')) | CREATE TABLE |
| `acknowledged_at` | INTEGER | CREATE TABLE |
| `acknowledged_by` | TEXT | CREATE TABLE |

## scan_state

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `file_path` | TEXT PRIMARY KEY | CREATE TABLE |
| `last_offset` | INTEGER DEFAULT 0 | CREATE TABLE |
| `last_scanned` | INTEGER | CREATE TABLE |
| `lines_processed` | INTEGER DEFAULT 0 | CREATE TABLE |

## sessions

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `session_id` | TEXT | CREATE TABLE |
| `timestamp` | INTEGER | CREATE TABLE |
| `project` | TEXT | CREATE TABLE |
| `account` | TEXT | CREATE TABLE |
| `model` | TEXT | CREATE TABLE |
| `input_tokens` | INTEGER | CREATE TABLE |
| `output_tokens` | INTEGER | CREATE TABLE |
| `cache_read_tokens` | INTEGER | CREATE TABLE |
| `cache_creation_tokens` | INTEGER | CREATE TABLE |
| `cost_usd` | REAL | CREATE TABLE |
| `source_path` | TEXT | migration in `db.py` |
| `compaction_detected` | INTEGER DEFAULT 0 | migration in `db.py` |
| `tokens_before_compact` | INTEGER | migration in `db.py` |
| `tokens_after_compact` | INTEGER | migration in `db.py` |
| `is_subagent` | INTEGER DEFAULT 0 | migration in `db.py` |
| `parent_session_id` | TEXT | migration in `db.py` |
| `compact_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `subagent_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `compact_timing_pct` | REAL | migration in `db.py` |
| `tool_call_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `bash_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `read_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `write_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `grep_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `mcp_count` | INTEGER DEFAULT 0 | migration in `db.py` |
| `max_output_tokens` | INTEGER DEFAULT 0 | migration in `db.py` |
| `work_classification` | TEXT | migration in `db.py` |
| `prompt_quality` | TEXT | migration in `db.py` |
| `inferred_project` | TEXT | migration in `db.py` |
| `request_id` | TEXT | migration in `db.py` |

Table constraints: `UNIQUE(session_id, timestamp, model)`

## settings

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `key` | TEXT PRIMARY KEY | CREATE TABLE |
| `value` | TEXT | CREATE TABLE |
| `updated_at` | INTEGER | CREATE TABLE |
| `updated_at` | INTEGER | migration in `db.py` |

## waste_events

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `session_id` | TEXT | CREATE TABLE |
| `project` | TEXT | CREATE TABLE |
| `account` | TEXT | CREATE TABLE |
| `pattern_type` | TEXT | CREATE TABLE |
| `severity` | TEXT | CREATE TABLE |
| `turn_count` | INTEGER | CREATE TABLE |
| `token_cost` | REAL | CREATE TABLE |
| `detected_at` | INTEGER | CREATE TABLE |
| `detail_json` | TEXT | CREATE TABLE |

Table constraints: `UNIQUE(session_id, pattern_type)`

## window_burns

Created in `db.py`.

| Column | Type | Origin |
|---|---|---|
| `id` | INTEGER PRIMARY KEY AUTOINCREMENT | CREATE TABLE |
| `account` | TEXT | CREATE TABLE |
| `window_start` | INTEGER | CREATE TABLE |
| `window_end` | INTEGER | CREATE TABLE |
| `tokens_used` | INTEGER | CREATE TABLE |
| `tokens_limit` | INTEGER | CREATE TABLE |
| `pct_used` | REAL | CREATE TABLE |
| `hit_limit` | INTEGER DEFAULT 0 | CREATE TABLE |

## Tables present in a live DB but created by no shipped code

Found 2026-11-09 by diffing the live `data/usage.db` (28 tables) against a fresh
`db.init_db()` (24 tables + `sqlite_sequence`). Column parity for the 24 shared
tables is **exact** — fresh and live differ in zero columns — so the only drift is
these four whole tables.

| Table | Live rows | Created by | Read by | Status |
|---|---|---|---|---|
| `compliance_events` | 127 | **nothing in the repo** | `cli.py:1355` (`cmd_realstory`), `fix_rules.py` | **shipping bug** — see below |
| `burnctl_fix_measurements` | 1 | `fix_measurement.py`, via an f-string on `_TABLE` | `fix_measurement.py` | works, but invisible to a name-based grep |
| `generated_hooks` | 0 | nothing | nothing | orphan — safe to drop |
| `skill_usage` | 0 | nothing | nothing | orphan — safe to drop |

### `compliance_events` — fresh-install crash

`cli.py:1355` runs an **unguarded** query:

    SELECT pattern_id, status, COUNT(*) FROM compliance_events WHERE project=? ...

No code in the repo creates the table. Reproduced by pointing `db.DB_PATH` at an
empty directory and calling `db.init_db()`:

    sqlite3.OperationalError: no such table: compliance_events

It survives because this DB has held the table, and 127 rows, since before it was
dropped from `db.py`. `tests/test_fresh_env_commands.py` cannot catch it: it runs
commands in a fresh *environment* against the *existing* database, so no test ever
sees an empty DB.

The live DDL, for whoever restores it:

```sql
CREATE TABLE compliance_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at INTEGER NOT NULL,
    session_id TEXT,
    project TEXT NOT NULL,
    pattern_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    status TEXT NOT NULL,
    evidence TEXT,
    auto_fix_available INTEGER DEFAULT 0,
    hook_generated INTEGER DEFAULT 0
);
```

Not fixed here: `db.py` schema changes belong to `burnctl-fixer` per the pipeline in
`CLAUDE.md`.

## Known drift — and the three entries that are NOT drift

Corrected 2026-11-09. Column names are **table-scoped**; a bare identifier is not
resolvable on its own. The earlier flat list caused a standing false positive in
`burnctl-auditor` Check 4 across ~150 legitimate lines, which held the gate at NO-GO
on process grounds.

### Real drift — flag these

| Wrong name | Real name | Table |
|---|---|---|
| `start_time` | `timestamp` | `sessions` |
| `end_time` | (no such column — compute from turns) | — |
| `waste_type` | `pattern_type` | `waste_events` |
| `browser_activity` (table) | `claude_ai_snapshots` | — |
| `baseline_waste_events` | (not a column — lives in `baseline_json`) | `fixes` |
| `measured_waste_events` | (not a column — measure at runtime) | `fixes` |

`start_time` and `browser_activity` both appear legitimately in the repo as a local
dict key (`browser_sessions.py`) and a function name
(`work_timeline.get_browser_activity`). Neither is a DB reference. A drift check must
look at SQL strings, not identifiers.

### NOT drift — these are real columns

| Name | Verdict | Where it really lives |
|---|---|---|
| `token_cost` | **real column** | `waste_events.token_cost REAL` — attributed *wasted* cost. Distinct from `sessions.cost_usd`, which is session cost. |
| `fix_id` | **real column** | `fix_measurements.fix_id INTEGER REFERENCES fixes(id)`. `fixes.id` is the PK; `fix_id` is the FK that names it. |
| `cost_usd` | **real column** | `sessions.cost_usd REAL`. `waste_events` has no `cost_usd`. |

Both namings are correct in their own table. Any drift check must resolve
`(table, column)` against the tables above, never match a bare identifier.

## Regenerating this file

Two traps, both hit on 2026-11-09 while generating it:

1. **Parse `db.py` first.** Files are otherwise walked alphabetically, and
   `burnctl_test_runner.py:440` contains a single-line
   `CREATE TABLE settings (key TEXT PRIMARY KEY, ...)` inside a test. It won the
   table name over `db.py` and put ~7 KB of test source into this document.
2. **Scan balanced parens, not `\((.*?)\n\s*\)`.** That pattern requires a newline
   before the closing paren, so a single-line `CREATE TABLE` makes it run past the
   real terminator into unrelated code.

Validate every column name against `^\w+$` and reject the whole match if one fails.
A self-check that only parses rows matching `` | `\w+` | `` will skip the corrupted
rows and report PASS — that is exactly how the bad version got committed.
