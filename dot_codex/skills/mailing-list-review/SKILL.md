---
name: mailing-list-review
description: Extend maintainer-history review for email-based patch series by discovering maintainer expectations in mailing-list archives, reconstructing revision threads, accounting for feedback, and preparing project-correct rerolls.
---

# Mailing List Review

Apply `$maintainer-review` first. Its maintainer-persona discovery, personal
`$coding-style` baseline, and change-record review remain authoritative. This
skill adds mailing-list history, maintainer feedback, revision threads, and
mail delivery conventions. Preparing or reviewing a series does not authorize
sending mail, publishing a branch, contacting maintainers, or claiming review
credit.

Own the complete series rather than polishing the latest diff in isolation.
Reconstruct the discussion, understand the invariant, and make the permanent
history stand alone.

## Gather the record

Collect:

- the exact base, complete series, diff, and cover letter;
- every submitted revision and all replies, including nested replies;
- the target branch and overlapping topics;
- comparable accepted commits and current submission guidance;
- substantive comments from the maintainers who own the affected paths.

Use `scripts/fetch_lore_threads.py` through the local liblore environment:

```sh
skill=${CODEX_HOME:-$HOME/.codex}/skills/mailing-list-review
uv run --project ~/code/b4/liblore \
  python "$skill/scripts/fetch_lore_threads.py" \
  --node https://lore.kernel.org/all \
  <root-msgid> [<root-msgid> ...]
```

Select the narrowest public-inbox endpoint that contains the thread. Do not
substitute a web UI, remembered discussion, or a revision changelog for the
complete record.

## Derive maintainer personas from mailing-list history

Identify actual subsystem maintainers from checked-in ownership, accepted
patches, affected-path history, and prior substantive thread replies. Inspect
what each relevant maintainer previously accepted, rejected, or required for
the same interface or design tradeoff. Seed those evidence-backed review
lenses before rerolling; a participant, Cc, employer, or previous approval
alone does not establish a maintainer's technical expectations.

## Track feedback

Record each substantive comment as:

```text
message-id | issue | disposition | evidence
```

Use one disposition:

- `address`: change code, tests, prose, or mail metadata;
- `reject`: explain why the suggestion is incorrect or worse;
- `defer`: show that it is independent and this series does not depend on it;
- `question`: investigate or answer before deciding.

Never silently omit feedback. Review each disposition against the intended
design rather than applying the comment mechanically.

## Build the series

- Trace the concrete behavior and ownership boundary before editing.
- Prefer one coherent mechanism over wrappers, special cases, or compatibility
  layers.
- Split independent correctness fixes, prerequisites, and policy changes when
  each is independently useful and reviewable.
- Make every commit build and test independently.
- Put behavioral coverage with the behavior it protects. Keep correctness tests
  separate from performance measurements.
- Test the regression and meaningful negative paths; avoid tautological tests.
- Run narrow validation first, then broaden it according to risk.
- Run project format and patch checks against every commit, not only the final
  tree.
- Compare parent and patched trees with identical setup for performance work.

Write commit messages as short causal narratives: old behavior, mechanism, new
behavior, and preserved invariant. Keep revision history in the cover letter.
Use only project-recognized trailers and never claim review or testing credit
that was not offered.

## Prepare mail

- Follow the target project's revision-threading convention.
- Determine recipients from project tools, ownership, affected-path history,
  prior participants, and substantive reviewers.
- Compare revisions with a range-diff and account for every change.
- Render and inspect the exact outgoing mail: subjects, recipients, threading,
  MIME, cover letter, commit bodies, diffstat, and base.
- Route mail through an SMTP account for the sender's domain. Keep the envelope
  sender and DKIM identity aligned with the visible `From` address.
- Unless `From` is an `@gmail.com` address, reflect an envelope-only copy to
  the parsed `From` address so the sender's mailbox retains the message. Do
  not add a visible `Bcc` header.
- Build replies by trimming the original message in place. Keep each response
  directly below the quote it addresses and retain enough surrounding context
  for other readers.
- Mark omitted spans between nonadjacent excerpts using the project's
  convention. Use `[...]` for Linux-style mail.

## Final review

Apply the evidence-backed maintainer lens to the complete series, cover letter,
commit messages, tests, and rendered mail. Add project-specific correctness,
API, compatibility, performance, and metadata passes as needed. After fixes,
repeat only affected passes and report any unresolved disposition or validation.
