# Notification watcher

Portable, dependency-free intake for authenticated source notifications.
Provider authentication, identities, routing, and operational data stay in
private runtime configuration rather than this public skill.

Run the existing database without installing a package or creating an
environment:

```sh
PYTHONPATH="$HOME/.codex/skills/notification-watcher/scripts/src" \
  python3 -B -m codex_notification_watcher health --limit 12
```

Use `pending`, `stats`, and `replay` to inspect durable state. Use `ingest`,
`source-register`, `source-failure`, `claim`, `resolve`, and `heartbeat` only
with a verified observation and authorized source owner. `bootstrap` creates
a new database from an explicitly selected private source manifest; registered
sources remain degraded until an authenticated provider page is actually read.
Neither `init` nor `bootstrap` replaces an existing database.

Run the independent, temporary-database regression tests and strict type checks:

```sh
PYTHONPATH="$HOME/.codex/skills/notification-watcher/scripts/src" \
  python3 -B -m unittest discover \
    -s "$HOME/.codex/skills/notification-watcher/scripts/tests" -p 'test_*.py'
basedpyright --project \
  "$HOME/.codex/skills/notification-watcher/scripts/pyproject.toml"
```
