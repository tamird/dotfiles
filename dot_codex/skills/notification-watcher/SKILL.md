---
name: notification-watcher
description: Ingest, authenticate, deduplicate, and route notifications using one durable source watcher, exact event receipts, replayable watermarks, and globally verified health.
---

# Notification Watcher

Use one notification watcher for genuine human review requests, authenticated
user tasks, authored-change feedback, and continuous-integration updates.
Notification intake does not authorize implementing a request, posting a
message, reviewing code, changing provider state, or starting another scanner.

Keep the live notification SQLite database and its receipt socket in machine-local
cache, never in cloud-synchronized storage. Only the elected backup leader may
run the receipt writer; publish consistent, throttled snapshots for followers.

Read the private operator profile and notification source checklist only when
provider identity, authority, monitored subjects, source ownership, or routing
matters. Keep provider adapters, company-specific information, credentials,
databases, and live cursors outside this public skill.

## Observe once

- Authenticate the provider, source, actor, event, subject, and source owner.
- Page each configured source independently and replay at least 300 seconds.
- Follow every provider cursor to its actual terminal page. Never assume 100
  results, a fixed page count, or one reviewed-parent history is complete;
  retain event order across pages and finish every required nested history.
- Treat provider-native individual assignments and requested reviews as
  authoritative. Retain the actual author; never require a cached author
  alias, a previously seen timeline, or another source to finish before
  recording a complete domain.
- For every authorized owned pull request in every repository, fully page the
  review-thread roots and every thread's comments. Retain the first human
  root, later replies, immutable comment and review IDs, original reviewed
  commit, current head, author, creation time, and principal response. Never
  depend on mentions, issue comments, repository-local author aliases,
  pull-request update times, or personal-notification delivery.
- Record immutable event receipts, claims, and the resulting source cursor in
  one transaction. Advance a watermark only after a complete observed page.
- Resume after disconnection from the greater of the configured overlap and the
  actual outage, without relying on remembered notifications.
- Fully page authorized parent discovery without filtering parent creation by
  the reply replay floor. Include explicitly authorized roots and roots with
  recent reply activity. Independently page each root's replies from the
  actual checkpoint overlap and include discovery and every required root in
  authenticated `required_scopes` and `observed_scopes`; an incomplete scope
  must prevent a complete observation or checkpoint advance.
- Discover watched-channel activity with one fully paginated provider-native
  search across authorized channels when available. Replay beyond both the
  actual outage and plausible indexing delay; hydrate every changed or new
  root, protect unresolved and user-designated roots, and rotate bounded full
  reconciliation of dormant roots. Preserve each root's actual last terminal
  observation. Never mark an unscanned root observed or rely on channel search
  to cover direct messages.
- Classify review requests, control-plane tasks, owned-change feedback, and CI
  transitions separately. Leave human review authority to the downstream
  review consumer; a bot, changed head, mention, announcement, or failed
  check is not itself a request.
- Hydrate every authorized direct-message and project-channel root and its
  nested replies, including a general review request without an individual
  native assignment. A different reviewer's reaction, a bot-delivered
  notification, or an unrelated channel must never hide the actual human
  request. Authenticate the exact head and check the principal's existing
  signed review before claiming or dispatching the event.
- Bind a provider review to its immutable review identifier and the commit
  actually reviewed; never substitute the pull request's observed head or
  multiply one review across later heads. An approval, dismissal, stamp, or
  self-authored comment is status, not actionable feedback, unless an
  authenticated unresolved human request independently establishes otherwise.
- Treat a genuine same-head re-request as a new cycle only when its immutable
  provider request follows the previous signed review. Preserve the resolved
  original cycle; a current-state result alone cannot reopen it.
- Match the assessed head and required markers against the complete immutable
  provider body before truncating text for display or bounded output.
- Independently reconcile outstanding individual reviews across all
  authenticated, authorized repositories, not just one organization.
- Fully page personal participating or subscribed upstream notifications
  within explicitly authorized repositories. Preserve third-party issue
  comments that directly mention the principal or follow their participation,
  and verify an original-owner response before considering one satisfied.
  Native review requests and owned pull requests are separate sources; do not
  substitute a global repository or issue-comment search.
  Fully page the assignment-parent set and each subject's timeline, author
  comments, inline replies, and principal review history; mark every scope
  complete only after its authenticated terminal cursor.
  When a filtered provider timeline omits an event, verify the authoritative
  per-subject event history. Retain the genuine event time even when it
  predates the incremental replay floor; a cursor is not proof that an older
  outstanding request was satisfied.
- Deduplicate equivalent events while retaining each real provider receipt.
- Identify mutable build and merge-status updates by their stable comment,
  assessed full head, actual run, and state. Authenticate the current head;
  a synthetic validation base need not equal the pull-request base.
- Classify provider job outcomes before diagnosing a failed build. Treat
  required `timed_out`, `failed`, `errored`, and `expired` jobs as independent
  hard failures; distinguish `timing_out`, soft or automatically retried jobs,
  and downstream `broken` or canceled dependents. An aggregate failure, a
  soft exit, or many blocked jobs cannot establish the underlying cause.
- Supersede a disproved claim with authenticated source, exact head, original
  claimant, and reason; never delete its receipt or invent a published review.
- Verify every configured source when computing health; bound only the number
  of examples shown to the user.
- Commit a real provider-observation heartbeat with each source receipt.
  Mark the watcher degraded once either a source or its durable heartbeat is
  over 120 seconds old. Restart the existing authenticated reader; never
  manufacture a heartbeat, advance an incomplete cursor, or create a second
  scanner after a transport stall.
- Run exactly one private `serve-receipts` writer. Existing authenticated
  provider readers deliver each complete observation with `submit-batch`;
  the writer atomically validates scopes, records events, advances the actual
  source checkpoint, and persists the provider heartbeat. Receipt ingestion
  must not wait for a model turn, user interaction, tests, or other source.
- An authenticated in-session connector is required for provider scans. A
  database read, cached receipt, background process, or quiet HTTP probe is not
  evidence that a provider was observed.

Run the watcher without installing dependencies or creating an environment:

```sh
PYTHONPATH="$HOME/.codex/skills/notification-watcher/scripts/src" \
  python3 -B -m codex_notification_watcher \
    --database /path/to/existing-notifications.sqlite3 health --limit 12
```

Resume each source from its actual verified high-water mark. Use an explicit
recovery cutoff only when the user authorizes an emergency cache rebuild.
Registration is not a provider scan; sources remain degraded until their
complete pages are actually observed.

## Validate every script change

Run the isolated behavior tests and strict basedpyright check:

```sh
PYTHONPATH="$HOME/.codex/skills/notification-watcher/scripts/src" \
  python3 -B -m unittest discover \
    -s "$HOME/.codex/skills/notification-watcher/scripts/tests" \
    -p 'test_*.py'
basedpyright --project \
  "$HOME/.codex/skills/notification-watcher/scripts/pyproject.toml"
```

Keep basedpyright declared and configured in `pyproject.toml`. Verify actual
provider coverage before reporting intake healthy.
