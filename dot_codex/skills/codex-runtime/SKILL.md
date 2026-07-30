---
name: codex-runtime
description: Maintain portable Codex sessions, leader-only backups, and removable background services using skill-owned Python programs and Google-Drive-backed operational state.
---

# Codex Runtime

Keep implementation in `scripts/` and mutable state under
`~/Google Drive/My Drive/Codex/runtime`. Do not copy credentials, run an unbounded backup,
move native Codex state, or change a service without first checking its current
LaunchAgent and status.

Resolve the skill-owned scripts independently of the current checkout:

```sh
runtime_scripts="${CODEX_HOME:-$HOME/.codex}/skills/codex-runtime/scripts"
```

Use `/usr/bin/python3 "${runtime_scripts}/codex-state-backup"` for `status`,
`run`, `restore --missing`, `install --leader`, or `install --follower`.
Only the explicitly elected leader publishes consistent, standalone SQLite
snapshots. A follower never runs the backup writer; transfer leadership with
`install --leader --takeover` only after the previous leader has stopped.
Use `restore --missing --repair-empty` on a follower to replace a verified empty
thread index only when no process has the database open.

Use `/usr/bin/python3 "${runtime_scripts}/codex-migrate-session-state" --dry-run`
to inspect global session-state migration. Leader bootstrap atomically moves the
complete rotated-segment, archived-session, attachment, and session-index stores
into Google Drive without copying them or interrupting their native paths.
Follower bootstrap invokes the same script with `--link` to connect all those
stores without discarding nonempty local state or claiming backup leadership.
It waits briefly for Google Drive and reports which shared artifacts are still
missing; override the wait with `--wait SECONDS` when needed.

Use `/usr/bin/python3 "${runtime_scripts}/codex-migrate-memories"` only when
the user authorizes durable migration. It verifies the entire memory Git
repository and atomically keeps `~/.codex/memories` pointing at
`~/Google Drive/My Drive/Codex/memories`.

Run the focused regression tests without creating an environment:

```sh
/usr/bin/python3 -B -m unittest discover \
  -s "${runtime_scripts}/tests" -p 'test_codex_*.py'
```

The backup LaunchAgent label is `local.codex.state-backup`. Run
`codex-bootstrap leader` on the one active writer and `codex-bootstrap follower`
on other machines. Run `codex-bootstrap stop` to remove scheduled background
work. Only the leader may run shared-state writers or the notification
operator. Never resume the same session concurrently on multiple machines.
