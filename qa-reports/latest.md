# burnctl Daily QA — 2026-04-20 10:12 UTC

**Version:** v4.0.11   **Summary:** 14/14 WOW · 0 OK · 0 DOD

```
burnctl Daily QA — 2026-04-20 10:12 UTC
v4.0.11 | 14/14 WOW | 0 OK | 0 DOD

audit                WOW  184 sessions analyzed
resume-audit         WOW  4/178 flagged (2.2%)
peak-hours           WOW  Off-peak  10:11 UTC
version-check        WOW  v2.1.114 clean
variance             WOW  clean 'no database' message
subagent-audit       WOW  clean 'no database' message
overhead-audit       WOW  clean 'no database' message
compact-audit        WOW  clean 'no database' message
fix-scoreboard       WOW  clean 'no database' message
work-timeline        WOW  no-DB message correct
work-timeline 7d     WOW  no-DB message correct
api/health           WOW  v4.0.11
api/stats            WOW  $9,445.15 across 24,143 turns
api/projects         WOW  7 projects, no Claudash leak

REGRESSIONS vs previous run: none
```

Full elapsed: 65.9s

## Details

### audit — WOW
- kind: `npx`  arg: `audit`  exit: `0`  elapsed: 7.19s
- evidence: 184 sessions analyzed

### resume-audit — WOW
- kind: `npx`  arg: `resume-audit`  exit: `0`  elapsed: 5.99s
- evidence: 4/178 flagged (2.2%)

### peak-hours — WOW
- kind: `npx`  arg: `peak-hours`  exit: `0`  elapsed: 2.53s
- evidence: Off-peak  10:11 UTC

### version-check — WOW
- kind: `npx`  arg: `version-check`  exit: `0`  elapsed: 3.01s
- evidence: v2.1.114 clean

### variance — WOW
- kind: `npx`  arg: `variance`  exit: `0`  elapsed: 2.61s
- evidence: clean 'no database' message

### subagent-audit — WOW
- kind: `npx`  arg: `subagent-audit`  exit: `0`  elapsed: 2.79s
- evidence: clean 'no database' message

### overhead-audit — WOW
- kind: `npx`  arg: `overhead-audit`  exit: `0`  elapsed: 3.39s
- evidence: clean 'no database' message

### compact-audit — WOW
- kind: `npx`  arg: `compact-audit`  exit: `0`  elapsed: 5.86s
- evidence: clean 'no database' message

### fix-scoreboard — WOW
- kind: `npx`  arg: `fix-scoreboard`  exit: `0`  elapsed: 9.92s
- evidence: clean 'no database' message

### work-timeline — WOW
- kind: `npx`  arg: `work-timeline`  exit: `0`  elapsed: 10.03s
- evidence: no-DB message correct

### work-timeline 7d — WOW
- kind: `npx`  arg: `work-timeline --days 7`  exit: `0`  elapsed: 11.31s
- evidence: no-DB message correct

### api/health — WOW
- kind: `curl`  arg: `/api/health`  exit: `200`  elapsed: 0.12s
- evidence: v4.0.11

### api/stats — WOW
- kind: `curl`  arg: `/api/stats`  exit: `200`  elapsed: 0.04s
- evidence: $9,445.15 across 24,143 turns

### api/projects — WOW
- kind: `curl`  arg: `/api/projects`  exit: `200`  elapsed: 1.07s
- evidence: 7 projects, no Claudash leak

<!-- trend-metrics:start -->
api_health_version=4.0.11
api_stats_cost_usd=9445.15
api_stats_total_turns=24143
dod_count=0
fix_improving_count=7
fix_monthly_savings_usd=1708.52
fix_tokens_saved=1347285
ok_count=0
resume_audit_flag_pct=2.20
work_browser_pct=54
work_cc_pct=46
wow_count=14
<!-- trend-metrics:end -->