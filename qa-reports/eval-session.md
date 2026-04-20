# burnctl Daily QA — 2026-04-20 10:37 UTC

**Version:** v4.0.12   **Summary:** 4/14 WOW · 2 OK · 8 DOD

```
burnctl Daily QA — 2026-04-20 10:37 UTC
v4.0.12 | 4/14 WOW | 2 OK | 8 DOD

audit                DOD  crash or non-zero exit
resume-audit         DOD  crash or non-zero exit
peak-hours           DOD  crash or non-zero exit
version-check        DOD  crash or non-zero exit
variance             DOD  exit -1
subagent-audit       DOD  exit -1
overhead-audit       DOD  exit -1
compact-audit        WOW  clean 'no database' message
fix-scoreboard       DOD  exit -1
work-timeline        OK   ran without expected marker
work-timeline 7d     OK   ran without expected marker
api/health           WOW  v4.0.12
api/stats            WOW  $9,472.38 across 24,229 turns
api/projects         WOW  7 projects, no Claudash leak

REGRESSIONS vs previous run:
  [WARN] audit was WOW, now DOD
  [WARN] resume-audit was WOW, now DOD
  [WARN] peak-hours was WOW, now DOD
  [WARN] version-check was WOW, now DOD
  [WARN] variance was WOW, now DOD
  [WARN] subagent-audit was WOW, now DOD
  [WARN] overhead-audit was WOW, now DOD
  [WARN] fix-scoreboard was WOW, now DOD
```

Full elapsed: 946.1s

## Details

### audit — DOD
- kind: `npx`  arg: `audit`  exit: `-1`  elapsed: 90.24s
- evidence: crash or non-zero exit

### resume-audit — DOD
- kind: `npx`  arg: `resume-audit`  exit: `-1`  elapsed: 90.42s
- evidence: crash or non-zero exit

### peak-hours — DOD
- kind: `npx`  arg: `peak-hours`  exit: `-1`  elapsed: 90.62s
- evidence: crash or non-zero exit

### version-check — DOD
- kind: `npx`  arg: `version-check`  exit: `-1`  elapsed: 90.6s
- evidence: crash or non-zero exit

### variance — DOD
- kind: `npx`  arg: `variance`  exit: `-1`  elapsed: 90.4s
- evidence: exit -1

### subagent-audit — DOD
- kind: `npx`  arg: `subagent-audit`  exit: `-1`  elapsed: 90.65s
- evidence: exit -1

### overhead-audit — DOD
- kind: `npx`  arg: `overhead-audit`  exit: `-1`  elapsed: 90.87s
- evidence: exit -1

### compact-audit — WOW
- kind: `npx`  arg: `compact-audit`  exit: `0`  elapsed: 35.92s
- evidence: clean 'no database' message

### fix-scoreboard — DOD
- kind: `npx`  arg: `fix-scoreboard`  exit: `-1`  elapsed: 90.48s
- evidence: exit -1

### work-timeline — OK
- kind: `npx`  arg: `work-timeline`  exit: `-1`  elapsed: 90.46s
- evidence: ran without expected marker

### work-timeline 7d — OK
- kind: `npx`  arg: `work-timeline --days 7`  exit: `-1`  elapsed: 90.46s
- evidence: ran without expected marker

### api/health — WOW
- kind: `curl`  arg: `/api/health`  exit: `200`  elapsed: 1.14s
- evidence: v4.0.12

### api/stats — WOW
- kind: `curl`  arg: `/api/stats`  exit: `200`  elapsed: 0.99s
- evidence: $9,472.38 across 24,229 turns

### api/projects — WOW
- kind: `curl`  arg: `/api/projects`  exit: `200`  elapsed: 2.88s
- evidence: 7 projects, no Claudash leak

<!-- trend-metrics:start -->
api_health_version=4.0.12
api_stats_cost_usd=9472.38
api_stats_total_turns=24229
dod_count=8
fix_improving_count=7
fix_monthly_savings_usd=1708.52
fix_tokens_saved=1347285
ok_count=2
work_browser_pct=52
work_cc_pct=48
wow_count=4
<!-- trend-metrics:end -->