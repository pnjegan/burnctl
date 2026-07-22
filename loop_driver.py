"""burnctl LOOP-DRIVER — autonomous outer control layer over loop_runner.py.

EXTENDS, never replaces, loop_runner.py. loop_runner owns a single worker->checker
ATTEMPT (STATE1->2->3, the six axes, post-write auto-rollback, abort_ceiling=3, the
hardcoded no-push). This driver wraps that as the INNER loop and adds, ON TOP:

  * a ROUTER that classifies each blocking failure by docs/RULE-CLASSIFICATION.md
    (GATE / FRICTION / FIXED POLICY) and decides retry vs iterate vs escalate;
  * hard BUDGET caps (max_iterations / max_tokens / max_usd) — all REQUIRED, no
    default-infinite (the money-furnace guard);
  * a STALL detector on the high-water mark of green-axis count.

Remedy execution DEFAULTS to DRY-RUN: a FRICTION remedy is LOGGED ("I would run:
<remedy>") and never executed. GOAL-FRICTION-REMEDIES adds an OPT-IN wet mode
(`wet=True`) that executes exactly ONE class of remedy — allow-listed FRICTION
rules (initially {A3, A8} = `bash deploy.sh`) — via an INJECTED command_runner;
everything else stays dry-run/escalate (default-deny). This module spawns NO
process itself: the real executor lives in wet_exec.py and must be explicitly wired.
A3->A9 escalates on the remedy's non-zero exit, zero retries. No push, ever.

DETECT-NOT-ENFORCE holds: the driver stops ITS OWN loop and escalates a structured
"why I stopped" record to the human accept gate. It never pushes, never self-ships.

── KNOWN LIMITATION (escalation-record docs; NOT fixed in this goal) ─────────────
The real budget probe (`telemetry_budget_probe`) sums cost/tokens from the `sessions`
table for all rows with timestamp >= run_start. That is MACHINE-WIDE: in wet/live
mode, concurrent UNRELATED Claude Code sessions are counted too, so the probe
OVER-counts this loop's own spend. Consequences:
  * it is fail-safe — it never under-counts, never lets the loop burn past budget;
  * but it can raise a FALSE budget escalation when other sessions run concurrently.
Precise per-loop attribution is deferred to the wet-run goal. Carried, not fixed.

Stdlib only (plus lazy `db` import inside the real probe).
"""

from __future__ import annotations

import dataclasses

import loop_runner


# The machine-wide-attribution caveat, surfaced IN the escalation record so the
# human reading a budget stop is never misled about what the number measures.
KNOWN_LIMITATIONS = [
    "budget attribution is machine-wide: the telemetry probe sums ALL sessions "
    "with timestamp >= run_start, not just this loop's own spend. In wet/live mode "
    "concurrent unrelated sessions over-count -> possible FALSE budget escalation. "
    "Fail-safe (never under-counts, never burns past budget). Precise per-loop "
    "attribution is deferred to the wet-run goal (GOAL-FRICTION-REMEDIES).",
]


# ─────────────────────────── router data model ───────────────────────────

@dataclasses.dataclass(frozen=True)
class Rule:
    """One row of docs/RULE-CLASSIFICATION.md the router routes on."""
    rule_id: str
    klass: str                 # "GATE" | "FRICTION" | "FIXED POLICY"
    resolves_by: str = ""      # GATE only: "human" | "loop-iteration"
    remedy: str = ""           # FRICTION only: the (dry-run) remedy command
    escalates_to: str = ""     # FRICTION whose remedy trips a GATE (A3 -> "A9")


@dataclasses.dataclass(frozen=True)
class Decision:
    action: str                # "DRY_RUN_REMEDY" | "WET_EXECUTE" | "ITERATE" | "ESCALATE"
    rule_id: str
    reason: str
    remedy_logged: str = ""    # the dry-run log line, if action == DRY_RUN_REMEDY
    escalate_to: str = ""      # the GATE a friction remedy escalates to, if any


def route(rule_id, rule_table, *, wet=False, allow_list=frozenset()):
    """PURE router: (rule_id, table, wet, allow_list) -> Decision. No I/O, no
    clock, no randomness, so identical inputs always yield the identical Decision
    (determinism). Defaults (wet=False, empty allow_list) reproduce the original
    dry-run routing exactly — the only NEW behaviour is the WET_EXECUTE branch,
    reachable ONLY for an allow-listed FRICTION rule in an explicit wet run."""
    rule = rule_table.get(rule_id)
    if rule is None:
        # Default-to-GATE: an unknown rule is treated as a human hard-stop, never
        # silently retried. Misclassifying a GATE as FRICTION is the worst error.
        return Decision("ESCALATE", rule_id, "unknown rule -> default-to-GATE (human)")

    if rule.klass == "FIXED POLICY":
        # Category B is the loop's own brakes; routing one is a category error.
        return Decision("ESCALATE", rule_id, "FIXED POLICY routed -> category error, escalate")

    if rule.klass == "FRICTION":
        if wet and rule_id in allow_list:
            # ARMED: an explicitly allow-listed FRICTION rule in a wet run EXECUTES.
            # Runtime escalation is decided by run() from the exit code (A3 deploy.sh
            # exit 1 -> A9); escalate_to is carried for that failure branch.
            return Decision("WET_EXECUTE", rule_id,
                            "armed wet remedy -> execute (allow-listed)",
                            remedy_logged=f"run: {rule.remedy}",
                            escalate_to=rule.escalates_to)
        if rule.escalates_to:
            # NOT armed + known to trip a GATE (A3 deploy.sh -> A9 version-mismatch):
            # ESCALATE to that GATE — do NOT retry, do NOT pretend-run.
            return Decision("ESCALATE", rule_id,
                            f"FRICTION remedy trips GATE {rule.escalates_to} -> escalate, no retry",
                            escalate_to=rule.escalates_to)
        return Decision("DRY_RUN_REMEDY", rule_id,
                        "FRICTION -> dry-run remedy then re-run",
                        remedy_logged=f"I would run: {rule.remedy}")

    # GATE
    if rule.resolves_by == "human":
        return Decision("ESCALATE", rule_id, "GATE resolves_by=human -> stop, zero retries")
    if rule.resolves_by == "loop-iteration":
        return Decision("ITERATE", rule_id,
                        "GATE resolves_by=loop-iteration -> feed reason back, iterate")
    # A GATE with an unrecognised resolves_by is ambiguous -> default-to-GATE(human).
    return Decision("ESCALATE", rule_id, "GATE unknown resolves_by -> default stop (human)")


# ─────────────────────────── attempt result ───────────────────────────

@dataclasses.dataclass
class AttemptResult:
    """The outcome of ONE outer attempt (one loop_runner.run_loop, or a mock).

    axes_green / axes_total feed the stall high-water mark; overall_green +
    the driver's DONE-checks decide DONE; failure_rule_id (when not green, or
    when a DONE-check blocks) is what the router routes."""
    axes_green: int
    axes_total: int
    overall_green: bool
    failure_rule_id: str = None
    inner_iterations: int = 1        # how many INNER (abort_ceiling) attempts ran
    halted_by_brake: bool = False
    axes: list = None


def attempt_from_run_loop(goal, artifacts_fn, failure_rule_id="A14"):
    """Adapter: run the REAL loop_runner.run_loop (the inner loop) and map its
    ledger to an AttemptResult. This is the seam proving the driver EXTENDS
    loop_runner rather than reimplementing it. A red inner run defaults its
    routing to A14 (tester PASS, a loop-iteration GATE) unless overridden."""
    led = loop_runner.run_loop(goal, artifacts_fn)
    axes = led.get("axes") or []
    green = sum(1 for a in axes if a["pass"])
    return AttemptResult(
        axes_green=green,
        axes_total=len(axes) or len(loop_runner.AXES),
        overall_green=led["overall_green"],
        failure_rule_id=None if led["overall_green"] else failure_rule_id,
        inner_iterations=led["iterations"],
        halted_by_brake=led["halted_by_brake"],
        axes=axes,
    )


# ─────────────────────────── budget probes ───────────────────────────

def telemetry_budget_probe(run_start, conn_factory=None):
    """REAL budget source: cumulative (tokens, usd) from burnctl's own telemetry
    for every `sessions` row with timestamp >= run_start.

    Machine-wide by construction (see KNOWN_LIMITATIONS) — conservative/fail-safe.
    conn_factory defaults to db.get_conn (canonical resolver, no hardcoded path);
    tests inject a factory over a seeded sessions table to exercise this real SQL."""
    if conn_factory is None:
        import db  # lazy: keep the driver importable without touching the real DB
        conn_factory = db.get_conn
    conn = conn_factory()
    if conn is None:                     # no DB yet -> nothing spent
        return (0, 0.0)
    row = conn.execute(
        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0), "
        "       COALESCE(SUM(cost_usd), 0.0) "
        "FROM sessions WHERE timestamp >= ?",
        (run_start,),
    ).fetchone()
    return (int(row[0]), float(row[1]))


def make_telemetry_probe(run_start, conn_factory=None):
    """Bind the real probe into the zero-arg callable the driver expects."""
    return lambda: telemetry_budget_probe(run_start, conn_factory)


# ─────────────────────────── A11 identical-DB-path proof (built, NOT armed) ───
def verify_identical_db_path(prior_path, resolver=None):
    """A11's identical-DB-path proof obligation. The A11 FRICTION remedy replaces
    a hardcoded DB literal with `db.resolved_db_path()`; that is only safe if the
    resolver returns the IDENTICAL path the literal resolved to. Returns True iff
    resolver() == prior_path — a False reclassifies A11 -> GATE (no blind edit).

    Built and tested this goal, but A11 stays OFF the wet allow-list: this helper
    is NEVER invoked by an armed remedy here. `resolver` is injectable for tests;
    it defaults to db.resolved_db_path (the single source get_conn() also uses)."""
    if resolver is None:
        import db  # lazy; keep the driver importable without touching the real DB
        resolver = db.resolved_db_path
    return resolver() == prior_path


# ─────────────────────────── the driver ───────────────────────────

class LoopDriver:
    """Outer control layer. Reuses loop_runner's inner brakes; adds router + caps
    + stall. Caps are REQUIRED — a driver you can build without a budget is the
    money-furnace failure, so construction without one raises."""

    def __init__(self, *, max_iterations, max_tokens, max_usd, stall_patience,
                 budget_probe, rule_table, done_checks, budget_source="sessions-table",
                 wet=False, wet_allow_list=frozenset(),
                 command_runner=None, tree_status=None):
        # Money-furnace structural guard: no default-infinite budget, ever.
        for name, val in (("max_iterations", max_iterations),
                          ("max_tokens", max_tokens),
                          ("max_usd", max_usd),
                          ("stall_patience", stall_patience)):
            if val is None:
                raise ValueError(f"{name} is REQUIRED (no default-infinite budget)")
            if val <= 0:
                raise ValueError(f"{name} must be > 0 (got {val!r})")
        if budget_probe is None:
            raise ValueError("budget_probe is REQUIRED")
        self.max_iterations = max_iterations
        self.max_tokens = max_tokens
        self.max_usd = max_usd
        self.stall_patience = stall_patience
        self.budget_probe = budget_probe          # () -> (tokens:int, usd:float)
        self.rule_table = dict(rule_table)
        self.done_checks = dict(done_checks)      # name -> callable(AttemptResult)->bool
        self.budget_source = budget_source

        # ── WET-MODE (opt-in; dry-run is the DEFAULT) ──────────────────────────
        # Default-deny executor: this module spawns no process itself. A wet run
        # requires the caller to EXPLICITLY inject a command_runner (cmd)->(code, out)
        # and a tree_status ()->porcelain-string. Tests inject mocks so the suite
        # never restarts pm2 / runs deploy.sh; the real wrappers live in wet_exec.py.
        self.wet = bool(wet)
        self.wet_allow_list = frozenset(wet_allow_list)   # default-deny: empty = run nothing
        if self.wet:
            if command_runner is None:
                raise ValueError("wet=True REQUIRES an explicit command_runner "
                                 "(default-deny: no built-in executor)")
            if tree_status is None:
                raise ValueError("wet=True REQUIRES an explicit tree_status "
                                 "(the dirty-tree preflight cannot be skipped)")
        self.command_runner = command_runner      # (cmd:str) -> (exit_code:int, output:str)
        self.tree_status = tree_status            # () -> `git status --porcelain` string

    # -- DONE = goal-green AND every injected check (auditor/reviewer/invariants) --
    # An AND-gate: it must block in the FAILING direction too (a single False -> not done).
    def _all_done_checks(self, attempt):
        return all(chk(attempt) for chk in self.done_checks.values())

    def run(self, attempt_fn):
        """Drive `attempt_fn(iteration, feedback) -> AttemptResult` to DONE or a
        structured escalation. Never pushes; never interrupts an in-flight inner run.

        INNER vs OUTER composition (non-masking, by construction):
          * INNER (loop_runner.abort_ceiling) is authoritative WITHIN one attempt; a
            brake-halted attempt returns as a RED RESULT the router handles — it never
            stops the outer loop directly, and it consumes EXACTLY ONE outer iteration
            regardless of how many inner attempts (1..ceiling) it ran.
          * OUTER caps/stall are checked ONLY BETWEEN attempts, so the inner
            post-write-assert -> auto-rollback always completes — an outer stop can
            never strand a half-committed tree.
          * outer_iterations_used and inner_iterations_total are recorded separately;
            neither can hide inside the other."""
        best_green = -1                # high-water mark of green-axis count
        stall_counter = 0              # outer iters since best_green last IMPROVED
        outer = 0
        inner_total = 0
        feedback = None
        last = None
        dry_run_remedies = []
        wet_executions = []            # real commands actually run (armed remedies only)

        # ── WET PREFLIGHT (before any attempt or execution) ──
        # loop_runner's rollback is `git reset --hard HEAD~1`, which DISCARDS
        # uncommitted tracked changes. A wet run against a dirty tree risks data
        # loss, so refuse to start one. Unbypassable: checked before the loop.
        if self.wet and self.tree_status().strip():
            return self._record("dirty-tree", 0, 0, -1, None, 0, 0,
                                wet_executions=wet_executions)

        base_tok, base_usd = self.budget_probe()
        used_tok, used_usd = 0, 0

        while True:
            # ── OUTER CAPS (between attempts, before spending another) ──
            if outer >= self.max_iterations:
                return self._record("cap-iterations", outer, inner_total, best_green,
                                    last, used_tok, used_usd, dry_run_remedies=dry_run_remedies,
                                    wet_executions=wet_executions)
            tok, usd = self.budget_probe()
            used_tok, used_usd = tok - base_tok, usd - base_usd
            if used_tok >= self.max_tokens:
                return self._record("cap-tokens", outer, inner_total, best_green,
                                    last, used_tok, used_usd, dry_run_remedies=dry_run_remedies,
                                    wet_executions=wet_executions)
            if used_usd >= self.max_usd:
                return self._record("cap-usd", outer, inner_total, best_green,
                                    last, used_tok, used_usd, dry_run_remedies=dry_run_remedies,
                                    wet_executions=wet_executions)

            # ── ONE OUTER ATTEMPT (inner run_loop is authoritative within) ──
            attempt = attempt_fn(outer, feedback)
            last = attempt
            outer += 1
            inner_total += attempt.inner_iterations

            # ── STALL high-water mark: reset ONLY on a STRICT improvement ──
            if attempt.axes_green > best_green:
                best_green = attempt.axes_green
                stall_counter = 0
            else:
                stall_counter += 1

            # ── DONE (four-way AND-gate; nothing softer) ──
            if attempt.overall_green and self._all_done_checks(attempt):
                return self._record("done", outer, inner_total, best_green,
                                    last, used_tok, used_usd, dry_run_remedies=dry_run_remedies,
                                    wet_executions=wet_executions)

            # ── ROUTE the blocking failure by its class ──
            if attempt.failure_rule_id is not None:
                decision = route(attempt.failure_rule_id, self.rule_table,
                                 wet=self.wet, allow_list=self.wet_allow_list)
                if decision.action == "ESCALATE":
                    stopped = "gate-remedy-escalation" if decision.escalate_to else "gate-human"
                    return self._record(stopped, outer, inner_total, best_green, last,
                                        used_tok, used_usd, decision=decision,
                                        dry_run_remedies=dry_run_remedies,
                                        wet_executions=wet_executions)
                if decision.action == "WET_EXECUTE":
                    # The ONLY path that runs a real command — reached solely for an
                    # allow-listed FRICTION rule in an explicit wet run.
                    rule = self.rule_table.get(decision.rule_id)
                    exit_code, output = self.command_runner(rule.remedy)
                    wet_executions.append({"rule_id": decision.rule_id, "cmd": rule.remedy,
                                           "exit_code": exit_code})
                    if exit_code != 0:
                        # Non-zero -> escalate per escalates_to (A3->A9), ZERO retries.
                        stopped = ("gate-remedy-escalation" if decision.escalate_to
                                   else "remedy-failed")
                        return self._record(stopped, outer, inner_total, best_green, last,
                                            used_tok, used_usd, decision=decision,
                                            dry_run_remedies=dry_run_remedies,
                                            wet_executions=wet_executions)
                    feedback = f"wet remedy ok (exit 0): {rule.remedy}"   # re-run
                elif decision.action == "DRY_RUN_REMEDY":
                    dry_run_remedies.append(decision.remedy_logged)   # LOG ONLY, never run
                    if self.wet:
                        # Wet mode + this rule is NOT allow-listed (default-deny): log
                        # the intent and STOP — never silently spin on an un-armed remedy.
                        return self._record("remedy-not-armed", outer, inner_total, best_green,
                                            last, used_tok, used_usd, decision=decision,
                                            dry_run_remedies=dry_run_remedies,
                                            wet_executions=wet_executions)
                    feedback = decision.remedy_logged                 # dry-run default: re-run
                else:  # ITERATE
                    feedback = f"iterate:{decision.rule_id}:{decision.reason}"
            else:
                feedback = "iterate:no-rule (not green)"

            # ── STALL terminate (after routing, so a routed-but-stuck loop ends) ──
            if stall_counter >= self.stall_patience:
                return self._record("stall", outer, inner_total, best_green,
                                    last, used_tok, used_usd, dry_run_remedies=dry_run_remedies,
                                    wet_executions=wet_executions)

    # -- the structured "why I stopped" escalation record --
    def _record(self, stopped_by, outer, inner_total, best_green, last,
                used_tokens, used_usd, decision=None, dry_run_remedies=(),
                wet_executions=()):
        return {
            # done | cap-iterations | cap-tokens | cap-usd | stall | gate-human |
            # gate-remedy-escalation | remedy-not-armed | remedy-failed | dirty-tree
            "stopped_by": stopped_by,
            "done": stopped_by == "done",
            "pushed": False,            # invariant: no branch of this driver pushes
            "rule_id": (decision.rule_id if decision else None),
            "decision_reason": (decision.reason if decision else None),
            "escalate_to": (decision.escalate_to if decision else None),
            "outer_iterations_used": outer,
            "inner_iterations_total": inner_total,
            "max_iterations": self.max_iterations,
            "best_green": best_green,
            "stall_patience": self.stall_patience,
            "last_green": (last.axes_green if last else None),
            "last_axes": (last.axes if last else None),
            "budget": {
                "tokens_used": used_tokens,
                "usd_used": used_usd,
                "max_tokens": self.max_tokens,
                "max_usd": self.max_usd,
                "source": self.budget_source,
                "attribution": "machine-wide-since-run_start (conservative, over-counts)",
            },
            "dry_run_remedies": list(dry_run_remedies),
            "wet_executions": list(wet_executions),   # real commands actually run (armed only)
            "wet": self.wet,
            "wet_allow_list": sorted(self.wet_allow_list),
            "known_limitations": KNOWN_LIMITATIONS,
            "accept_out": "HUMAN-GATED — driver escalates; never self-ships, never pushes",
        }
