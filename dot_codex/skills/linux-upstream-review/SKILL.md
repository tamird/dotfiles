---
name: linux-upstream-review
description: Prepare, review, reroll, and reply to Linux kernel mailing-list patch series. Use in Linux kernel trees for subsystem history and lore archaeology, b4-managed series, MAINTAINERS-based recipients, kernel commit-message and DCO review, checkpatch, selftests/KUnit/build validation, and evidence-backed maintainer review.
---

# Linux Upstream Review

Apply `$mailing-list-review` as the base workflow. This skill contains only
Linux-kernel additions. Also follow the checkout's `AGENTS.md` and subsystem
documentation.

## Establish kernel context

Before editing:

- identify the target subsystem tree and integration branch;
- inspect `MAINTAINERS`, relevant `Documentation/process/` guidance, local
  history, and prior lore discussions;
- find comparable accepted patches and reviews from the affected maintainers;
- check for overlapping work in the target tree.

Use the base skill's lore fetcher with the narrowest relevant archive. Do not
substitute GitHub PR metadata for kernel history or lore.

When the user explicitly authorizes Rust-for-Linux mailbox access, use
`rfl-mail inbox` for the configured inbox and `rfl-mail series` for the current
patch-series thread. Prepare an authorized reply with
`lei lcat --no-remote --no-external -f reply id:<msgid>`; obtain explicit user
confirmation before sending through `msmtp`.

Treat a generated reply as a draft. Verify its original Message-ID,
recipients, quoted context, threading headers, and rendered content; obtain
explicit confirmation before using the user's configured delivery path.

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

## Add kernel review lenses

Use `MAINTAINERS`, accepted commits, and lore to extend `$maintainer-review`
with the actual subsystem's concerns. Include evidence from maintainers and
reviewers across relevant ownership paths and affiliations; do not exclude or
privilege one employer without a task-specific reason.

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
