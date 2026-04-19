module.exports = {
  apps: [{
    name: 'burnctl',
    script: 'cli.py',
    interpreter: 'python3',
    args: 'dashboard --skip-init --no-browser',
    cwd: __dirname,
    watch: false,
    autorestart: true,
    max_restarts: 10,
    min_uptime: '10s',
    restart_delay: 5000,
    error_file: '/tmp/burnctl-error.log',
    out_file: '/tmp/burnctl-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    env: {
      PORT: 8080
    }
  }]
}
