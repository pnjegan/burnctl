# Contributing to burnctl

burnctl is actively maintained. Contributions welcome.

## Before opening a PR

- Run the audit on your own sessions first: `npx burnctl@latest audit`
- Check that your change doesn't break the fresh-install test:
  ```bash
  cd /tmp && rm -rf bc-test && mkdir bc-test && cd bc-test
  npx burnctl@latest audit
  ```

## What we need most

- Bug reports with JSONL schema details (Claude Code version + actual field names)
- Fixes to waste pattern detection accuracy
- Platform testing on different macOS versions
- Native Windows support (without WSL2)
- More waste-pattern detectors
- Statusline output formats for other shells / editors

## What we're not building yet

- Windows native support (WSL2 only for now)
- Team / multi-user features
- Cloud sync or accounts

Open an issue before starting large features.

## Development setup

```bash
git clone https://github.com/pnjegan/burnctl
cd burnctl
python3 cli.py dashboard   # zero deps, just run it
```

## Code style

- Python 3.8+ stdlib only — no pip dependencies
- Type hints encouraged but not required
- Debug logs prefixed with `[module_name]`

## Reporting bugs

Use the bug report template at `.github/ISSUE_TEMPLATE/bug_report.md`. Include:
- Your OS and Python version
- Claude Code version (`claude --version`)
- Steps to reproduce from a fresh `/tmp` directory
- Expected vs actual output
