---
name: mailing-list-review
description: Prepare, review, reroll, and respond to email-based patch series using public-inbox archives such as lore. Use for projects that develop through mailing lists when Codex must reconstruct prior revisions and replies, review code and commit messages, maintain a feedback ledger, prepare a new revision, or inspect rendered mail. Apply a project-specific skill in addition when one exists.
---

# Mailing List Review

Own the change rather than polishing the latest diff in isolation. Reconstruct
the discussion, understand the invariant, and make the permanent history stand
alone.

## Gather the record

Before editing, collect:

- the exact base, current commits, diff, and cover letter;
- every submitted revision and all replies, including replies to replies;
- the target branch and overlapping topics;
- comparable commits and current project submission guidance.

Use `scripts/fetch_lore_threads.py` through the local liblore environment:

```sh
skill=${CODEX_HOME:-$HOME/.codex}/skills/mailing-list-review
uv run --project ~/code/b4/liblore \
  python "$skill/scripts/fetch_lore_threads.py" \
  --node https://lore.kernel.org/all \
  <root-msgid> [<root-msgid> ...]
```

Select the narrowest public-inbox endpoint that contains the thread. Do not
rely on a web UI, remembered discussion, or a revision changelog.

## Keep a review ledger

Record each substantive comment as:

```text
message-id | issue | disposition | evidence
```

Use one disposition:

- `address`: change code, tests, prose, or mail metadata;
- `reject`: explain why the suggestion is incorrect or worse;
- `defer`: establish that it is independent and that this series does not
  depend on it;
- `question`: answer or investigate before deciding.

Never silently omit feedback. Review whether the proposed disposition itself
preserves the intended design.

## Build project reviewer personas

Before delegating review, reconstruct how the project actually reviews
patches. Search accepted and rejected mailing-list threads, prioritizing the
same files, subsystem, protocol, and patch shape. Identify two to four active
maintainers or reviewers and record the messages or accepted commits that
support each persona's review tendencies.

Seed reviewer agents with those evidence-backed project personas, not generic
maintainer stereotypes. Give each agent the whole series, including the cover
letter and commit messages, and a distinct review axis reflected in that
person's actual feedback. Require concrete findings with file or mail evidence
and an explicit statement of full-series coverage. If no project-specific
skill exists, this archaeology is still required; use the narrowest relevant
public-inbox archive and local history.

## Understand and design

Trace the concrete ownership boundary and call path first:

1. State the old behavior and user-visible failure.
2. Identify the exact mechanism causing it.
3. Recover intent from history and discussion.
4. List public, dormant, error, and alternate-backend paths.
5. State the invariant the new code must preserve.

Prefer one coherent mechanism over wrappers, special cases, or compatibility
layers. Split independent correctness fixes, prerequisites, and policy changes
when each is independently reviewable. Do not apply feedback mechanically when
it increases the conceptual count.

## Build the series

- Make every commit build and test independently.
- Put behavioral coverage with the behavior it protects.
- Keep correctness tests separate from performance measurements.
- Test the regression and meaningful negative or error paths; avoid
  tautological tests.
- Run narrow validation first, then broaden it according to the change's risk.
- Run the project's formatter and patch checks against every commit, not only
  the final tree.
- Compare parent and patched trees with identical setup for performance work.
- Account for likely counterexamples, not only the motivating case.

Write commit messages as short causal narratives: old behavior, mechanism,
new behavior, and the preserved invariant. Keep revision language in the cover
letter, not permanent history. Use only project-recognized trailers and never
claim review or testing credit that was not offered.

## Prepare mail

- Follow the target project's revision-threading convention; do not assume all
  projects want every revision in one thread.
- Determine recipients from project tools, ownership files, relevant history,
  and prior reviewers.
- Compare revisions with a range-diff and account for every change.
- Render the exact outgoing mail and inspect subjects, recipients, threading,
  MIME, cover letter, commit bodies, diffstat, and base.
- Reply inline with enough quoted context to identify the issue.

## Final review

Perform independent passes for correctness, design simplicity, tests and
performance, public API or compatibility concerns, permanent prose, and mail
metadata. Use the evidence-backed project personas built above. After fixes,
repeat the affected passes. Report any validation or review disposition that
remains unresolved.
