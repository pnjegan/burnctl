---
name: Bug report
about: Something is broken
---

**Command that failed:**
```
npx burnctl@latest <command>
```

**Expected:**

**Actual output:**

**Claude Code version:** (run `claude --version`)
**Python version:** (run `python3 --version`)
**OS:** Mac / Linux / Other

**Fresh install test:**
Did it also fail from a clean /tmp directory?
```
cd /tmp && rm -rf bc-bug && mkdir bc-bug && cd bc-bug
npx burnctl@latest <command>
```
