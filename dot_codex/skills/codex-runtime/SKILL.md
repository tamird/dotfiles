---
name: codex-runtime
description: Maintain the local Codex backup and network-monitor services using skill-owned Python programs, Google-Drive-backed operational state, and verifiable macOS LaunchAgents.
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
`run`, `restore --missing`, or `install`. The backup uses consistent SQLite
snapshots and includes only explicitly approved state.

Use `/usr/bin/python3 "${runtime_scripts}/codex-network-monitor"` for `status`,
`diagnose`, or `install`. Network diagnosis performs real transport probes;
it does not authenticate notification providers or establish notification
coverage.

Use `/usr/bin/python3 "${runtime_scripts}/codex-migrate-memories"` only when
the user authorizes durable migration. It verifies the entire memory Git
repository and atomically keeps `~/.codex/memories` pointing at
`~/Google Drive/My Drive/Codex/memories`.

Run the focused regression tests without creating an environment:

```sh
/usr/bin/python3 -B -m unittest discover \
  -s "${runtime_scripts}/tests" -p 'test_codex_*.py'
```

LaunchAgent labels are `local.codex.state-backup` and
`local.codex.network-monitor`. Installers must point at the skill-owned
scripts, retain the existing operational state, and never bypass permissions.
