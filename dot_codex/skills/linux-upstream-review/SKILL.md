---
name: linux-upstream-review
description: Prepare, review, reroll, and reply to Linux kernel mailing-list patch series. Use in Linux kernel trees for subsystem history and lore archaeology, b4-managed series, MAINTAINERS-based recipients, kernel commit-message and DCO review, checkpatch, selftests/KUnit/build validation, and maintainer-persona review. Load mailing-list-review first for the shared lore and series workflow.
---

# Linux Upstream Review

Read `../mailing-list-review/SKILL.md` completely and apply it as the base
workflow. This skill contains only Linux-kernel additions. Also follow the
checkout's `AGENTS.md` and subsystem documentation.

## Establish kernel context

Before editing:

- identify the target subsystem tree and integration branch;
- inspect `MAINTAINERS`, relevant `Documentation/process/` guidance, local
  history, and prior lore discussions;
- find comparable accepted patches and reviews from the affected maintainers;
- check for overlapping work in the target tree.

Use the base skill's lore fetcher with the narrowest relevant archive. Do not
substitute GitHub PR metadata for kernel history or lore.

For Rust-for-Linux work on this machine, use the local delivery path instead
of asking the user for identifiers:

- Run `rfl-mail inbox` to synchronize the Gmail label, index it with lei, and
  emit directly addressed, unanswered messages as JSONL.
- Run `rfl-mail series` to derive the most recently sent cover Message-ID from
  the current b4 branch and emit that thread as JSONL.
- Run `lei lcat --no-remote --no-external -f reply id:<msgid>` to produce the
  reply-all template and quoted context for a selected message.

Treat the template as a draft. Inspect recipients and threading headers,
render the exact outgoing message, and obtain explicit confirmation before
sending it through msmtp.

## Construct kernel commits

- Follow subsystem subject prefixes and local capitalization seen in accepted
  history.
- Use accurate `Fixes:`, `Reported-by:`, `Suggested-by:`, `Reviewed-by:`, and
  `Tested-by:` trailers only when warranted.
- Place any requested, project-accepted AI assistance trailer before the
  `Signed-off-by:` DCO trailer.
- Preserve the author's DCO chain and never invent maintainer trailers.
- Keep revision history and prior-version links in the cover letter.

Do not force all revisions into one email thread. Follow the subsystem's and
`b4`'s established revision practice; verify whatever threading metadata is
actually intended.

## Validate the series

- Use the repository's canonical build and selftest/KUnit workflow. Do not
  introduce containers or shadow build trees unless explicitly requested.
- Run `git clang-format --diff <commit>^ <commit>` for every patch. Apply any
  required formatting within that patch and rerun it until the diff is empty.
- Run `scripts/checkpatch.pl` and `git diff --check`, treating checkpatch as a
  review aid rather than an authority.
- Inspect ABI/API exports, symbol-version maps, generated skeletons, and
  documentation when affected.
- Verify error paths, feature-disabled builds, supported architectures, and
  concurrency or memory-ordering invariants relevant to the change.

When old compilers or architectures matter, reproduce with the canonical
toolchain path and record the exact evidence. Do not replace requested native
builds with unrelated Docker experiments.

## Review like the subsystem

Use `MAINTAINERS`, accepted commits, and lore to seed independent reviewer
passes with the actual subsystem's concerns. Include maintainers and reviewers
from varied affiliations; do not exclude or privilege one employer except when
the task supplies a reason.

Add concurrency, memory ordering, API/ABI, architecture, and toolchain personas
when the patch touches those areas.

## Prepare with b4

Use the checkout's existing b4-managed branch. Update the cover letter through
the b4 workflow, preserve tracking metadata, and keep the revision changelog
limited to changes actually made since the preceding posted version.

Before sending, run the b4 dry run and inspect the exact cover, patches,
and revision metadata using the base workflow. Use `scripts/get_maintainer.pl`
plus prior participants and subsystem history to review recipients; do not
accept its output uncritically.
