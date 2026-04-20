# burnctl Daily QA — 2026-04-20 10:03 UTC

**Version:** v4.0.10   **Summary:** 14/14 WOW · 0 OK · 0 DOD

```
burnctl Daily QA — 2026-04-20 10:03 UTC
v4.0.10 | 14/14 WOW | 0 OK | 0 DOD

audit                WOW  184 sessions analyzed
resume-audit         WOW  4/178 flagged (2.2%)
peak-hours           WOW  Off-peak  10:03 UTC
version-check        WOW  v2.1.114 clean
variance             WOW  clean 'no database' message
subagent-audit       WOW  clean 'no database' message
overhead-audit       WOW  clean 'no database' message
compact-audit        WOW  clean 'no database' message
fix-scoreboard       WOW  clean 'no database' message
work-timeline        WOW  no-DB message correct
work-timeline 7d     WOW  no-DB message correct
api/health           WOW  v4.0.10
api/stats            WOW  $9,424.45 across 24,099 turns
api/projects         WOW  7 projects, no Claudash leak

REGRESSIONS vs previous run: none
```

Full elapsed: 42.8s

## Details

### audit — WOW
- kind: `npx`  arg: `audit`  exit: `0`  elapsed: 7.36s
- evidence: 184 sessions analyzed

### resume-audit — WOW
- kind: `npx`  arg: `resume-audit`  exit: `0`  elapsed: 7.25s
- evidence: 4/178 flagged (2.2%)

### peak-hours — WOW
- kind: `npx`  arg: `peak-hours`  exit: `0`  elapsed: 2.49s
- evidence: Off-peak  10:03 UTC

### version-check — WOW
- kind: `npx`  arg: `version-check`  exit: `0`  elapsed: 2.94s
- evidence: v2.1.114 clean

### variance — WOW
- kind: `npx`  arg: `variance`  exit: `0`  elapsed: 2.49s
- evidence: clean 'no database' message

### subagent-audit — WOW
- kind: `npx`  arg: `subagent-audit`  exit: `0`  elapsed: 5.87s
- evidence: clean 'no database' message

### overhead-audit — WOW
- kind: `npx`  arg: `overhead-audit`  exit: `0`  elapsed: 2.72s
- evidence: clean 'no database' message

### compact-audit — WOW
- kind: `npx`  arg: `compact-audit`  exit: `0`  elapsed: 2.67s
- evidence: clean 'no database' message

### fix-scoreboard — WOW
- kind: `npx`  arg: `fix-scoreboard`  exit: `0`  elapsed: 2.79s
- evidence: clean 'no database' message

### work-timeline — WOW
- kind: `npx`  arg: `work-timeline`  exit: `0`  elapsed: 2.76s
- evidence: no-DB message correct

### work-timeline 7d — WOW
- kind: `npx`  arg: `work-timeline --days 7`  exit: `0`  elapsed: 2.79s
- evidence: no-DB message correct

### api/health — WOW
- kind: `curl`  arg: `/api/health`  exit: `200`  elapsed: 0.07s
- evidence: v4.0.10

### api/stats — WOW
- kind: `curl`  arg: `/api/stats`  exit: `200`  elapsed: 0.06s
- evidence: $9,424.45 across 24,099 turns

### api/projects — WOW
- kind: `curl`  arg: `/api/projects`  exit: `200`  elapsed: 0.58s
- evidence: 7 projects, no Claudash leak
