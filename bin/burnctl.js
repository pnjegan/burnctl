#!/usr/bin/env node

const { execSync, spawn } = require('child_process');
const path = require('path');
const fs = require('fs');
const os = require('os');
const net = require('net');

const { version: VERSION } = require('../package.json');
const REPO = 'https://github.com/pnjegan/burnctl';
const INSTALL_DIR = path.join(os.homedir(), '.burnctl');

// Subcommands that pass through to python cli.py.
// First-arg match wins; we pipe stdio and exit with the child's code.
const SUBCOMMANDS = new Set([
  'audit', 'burnrate', 'loops', 'block', 'statusline',
  'fix', 'scan', 'stats', 'measure', 'backup', 'restore',
  'realstory', 'insights', 'waste', 'show-other', 'window',
  'export', 'fixes', 'init', 'mcp', 'keys', 'claude-ai',
  'sync-daemon',
  // v4.0.4 additions
  'version-check', 'peak-hours', 'resume-audit', 'variance',
  // v4.0.7 additions
  'subagent-audit', 'overhead-audit', 'compact-audit',
  'fix-scoreboard', 'scoreboard',
  // v4.0.9 additions
  'work-timeline',
  // v4.0.11 additions
  'qa',
  // v4.1 additions
  'claudemd-audit', 'mcp-audit',
]);

const args = process.argv.slice(2);
const first = args[0];

// ── Subcommand pass-through (must run BEFORE --help so `burnctl audit --help` reaches cli.py)
if (first && SUBCOMMANDS.has(first)) {
  checkPython();
  const { cli, cwd } = getCliPath();
  const proc = spawn('python3', [cli, ...args], { stdio: 'inherit', cwd });
  proc.on('exit', code => process.exit(code == null ? 0 : code));
  process.on('SIGINT', () => { try { proc.kill('SIGINT'); } catch {} process.exit(130); });
  process.on('SIGTERM', () => { try { proc.kill('SIGTERM'); } catch {} process.exit(143); });
  return; // leaves the spawn alive — node stays up via the child's stdio handles
}

// ── Top-level help / version (only when no subcommand)
if (args.includes('--help') || args.includes('-h')) {
  printHelp();
  process.exit(0);
}
if (args.includes('--version') || args.includes('-v')) {
  console.log(VERSION);
  process.exit(0);
}

// ── Default: dashboard mode (no subcommand, or first arg is "dashboard")
if (!first || first === 'dashboard') {
  dashboardMode().catch(err => {
    console.error('burnctl: ' + err.message);
    process.exit(1);
  });
} else {
  // ── Anything else with a non-flag first arg = unknown command. Don't fall
  // through to dashboard mode — that hides typos behind a server start.
  if (first.startsWith('-')) {
    console.error('burnctl: unrecognized option ' + first);
  } else {
    console.error('burnctl: unknown command "' + first + '"');
  }
  console.error('Run `burnctl --help` for the command list.');
  process.exit(1);
}


// ──────────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────────

function printHelp() {
  console.log('burnctl v' + VERSION + ' — AI burn rate monitor for Claude Code');
  console.log('');
  console.log('Usage: burnctl [<subcommand> ...] [--port <n>] [--no-browser]');
  console.log('');
  console.log('Dashboard mode (default — auto-detects free port from 8080):');
  console.log('  burnctl                       Start dashboard, open browser');
  console.log('  burnctl --port 9090           Force a specific port');
  console.log('  burnctl --no-browser          Skip browser auto-open');
  console.log('');
  console.log('Subcommands (pass through to cli.py):');
  console.log('  burnctl burnrate              Live tokens/min, $/hr');
  console.log('  burnctl loops                 Detect retry-loop activity');
  console.log('  burnctl block                 5-hour block totals (observed)');
  console.log('  burnctl statusline            One-line statusline output');
  console.log('  burnctl peak-hours            Mon-Fri 13:00-19:00 UTC peak status');
  console.log('  burnctl version-check         Flag known-bad Claude Code versions');
  console.log('  burnctl audit [project]       JSONL waste-pattern audit');
  console.log('  burnctl resume-audit [days]   Detect cache-bust signals (5m TTL etc)');
  console.log('  burnctl variance [project]    Session cost variance profiler (CV)');
  console.log('  burnctl subagent-audit        Subagent cost split + chain-depth');
  console.log('  burnctl overhead-audit        Session startup overhead per project');
  console.log('  burnctl compact-audit         Compaction rate per project');
  console.log('  burnctl fix-scoreboard        Detect → fix → measure → prove loop');
  console.log('  burnctl work-timeline [--days N]  Unified CC + browser work timeline');
  console.log('  burnctl qa                    Daily QA suite — WOW/OK/DOD per command');
  console.log('  burnctl claudemd-audit        Find dead CLAUDE.md rules (0 matching waste events)');
  console.log('  burnctl mcp-audit             Find orphan MCP servers (configured but never called)');
  console.log('  burnctl fix apply <id>        Append fix to CLAUDE.md, mark measuring');
  console.log('  burnctl fix start "desc" --project X    Start measurement');
  console.log('  burnctl fix result <id>       Show before/after delta');
  console.log('  burnctl measure --auto        Re-measure all pending fixes');
  console.log('  burnctl scan                  Scan new sessions');
  console.log('  burnctl stats                 Per-account stats');
  console.log('  burnctl backup                Hot-copy DB');
  console.log('');
  console.log('  --version, -v   Print version and exit');
  console.log('  --help, -h      Show this help');
  console.log('');
  console.log('GitHub: https://github.com/pnjegan/burnctl');
  console.log('npm:    npm install -g burnctl');
}

function checkPython() {
  try {
    const ver = execSync('python3 --version 2>&1').toString().trim();
    const m = ver.match(/(\d+)\.(\d+)/);
    if (m && parseInt(m[1]) >= 3 && parseInt(m[2]) >= 8) return true;
    console.error('Python 3.8+ required. Found: ' + ver);
    process.exit(1);
  } catch (e) {
    console.error('Python 3 not found. Install from https://python.org');
    process.exit(1);
  }
}

function checkClaudeData() {
  const candidates = [
    path.join(os.homedir(), '.claude', 'projects'),
    path.join(os.homedir(), 'AppData', 'Roaming', 'Claude', 'projects'),
    path.join(os.homedir(), 'Library', 'Application Support', 'Claude', 'projects'),
  ];
  const found = candidates.filter(p => fs.existsSync(p));
  if (found.length === 0) {
    console.log('Warning: No Claude Code data found.');
    console.log('   Run at least one Claude Code session first.');
    console.log('   Looked in:');
    candidates.forEach(c => console.log('     ' + c));
    console.log('   Starting dashboard anyway — it will show instructions.');
  }
  return found;
}

// Find cli.py: prefer the local checkout (dev/clone install), else clone to INSTALL_DIR.
function getCliPath() {
  const localCli = path.join(__dirname, '..', 'cli.py');
  if (fs.existsSync(localCli)) {
    return { cli: localCli, cwd: path.dirname(localCli) };
  }
  installBurnctl();
  return { cli: path.join(INSTALL_DIR, 'cli.py'), cwd: INSTALL_DIR };
}

function installBurnctl() {
  if (fs.existsSync(path.join(INSTALL_DIR, 'cli.py'))) {
    if (process.argv.includes('--update')) {
      try {
        execSync('git -C "' + INSTALL_DIR + '" pull --quiet 2>/dev/null');
        console.log('burnctl updated');
      } catch (e) {
        console.error('Update failed (offline or not a git repo)');
      }
    }
    return;
  }
  console.log('Installing burnctl to ' + INSTALL_DIR + '...');
  try {
    execSync('git clone --depth=1 --quiet "' + REPO + '" "' + INSTALL_DIR + '"');
    console.log('burnctl installed');
  } catch (e) {
    console.error('Failed to clone from GitHub: ' + e.message);
    console.error('Check your internet connection or visit: ' + REPO);
    process.exit(1);
  }
}

function openBrowser(port) {
  const url = 'http://localhost:' + port;
  const platform = process.platform;
  setTimeout(() => {
    try {
      if (platform === 'darwin') execSync('open "' + url + '"');
      else if (platform === 'win32') execSync('start "" "' + url + '"');
      else execSync('xdg-open "' + url + '" 2>/dev/null || true');
    } catch (e) { /* headless — no browser */ }
  }, 1500);
}

// Native, cross-platform port-free check — no lsof/netstat dependency.
function isPortFree(port) {
  return new Promise(resolve => {
    const srv = net.createServer();
    srv.unref();
    srv.once('error', () => resolve(false));
    srv.once('listening', () => srv.close(() => resolve(true)));
    srv.listen(port, '127.0.0.1');
  });
}

async function findFreePort(start, end) {
  for (let p = start; p <= end; p++) {
    if (await isPortFree(p)) return p;
  }
  return null;
}

function parseExplicitPort() {
  const portEq = args.find(a => a.startsWith('--port='));
  if (portEq) return portEq.split('=')[1];
  const idx = args.indexOf('--port');
  if (idx !== -1 && args[idx + 1]) return args[idx + 1];
  return null;
}

async function dashboardMode() {
  let port;
  const explicit = parseExplicitPort();

  if (explicit !== null) {
    if (!/^\d{1,5}$/.test(explicit) || +explicit < 1 || +explicit > 65535) {
      console.error('Invalid port number: ' + explicit);
      process.exit(1);
    }
    if (!(await isPortFree(+explicit))) {
      console.error(`Port ${explicit} is in use. Try: burnctl --port ${+explicit + 1}`);
      process.exit(1);
    }
    port = +explicit;
  } else {
    port = await findFreePort(8080, 8090);
    if (port == null) {
      console.error('No free port found in 8080-8090. Try: burnctl --port <N>');
      process.exit(1);
    }
  }

  const noBrowser = args.includes('--no-browser');

  console.log('burnctl v' + VERSION);
  console.log('-'.repeat(40));

  checkPython();
  checkClaudeData();
  const { cli, cwd } = getCliPath();

  console.log(`burnctl dashboard → http://localhost:${port}`);
  if (!noBrowser) openBrowser(port);

  const proc = spawn(
    'python3',
    [cli, 'dashboard', '--port', String(port), '--no-browser'],
    { stdio: 'inherit', cwd }
  );
  proc.on('exit', code => process.exit(code == null ? 0 : code));
  process.on('SIGINT', () => { try { proc.kill('SIGINT'); } catch {} process.exit(130); });
  process.on('SIGTERM', () => { try { proc.kill('SIGTERM'); } catch {} process.exit(143); });
}
