---
name: git-upstream-review
description: Prepare, reroll, review, and reply to patches for the Git project mailing list. Use for git.git changes, Git commit-message review, t/ and t/perf validation, performance-patch evidence, maintainer-feedback disposition, and Git-specific revision threading.
---

# Git Upstream Review

Apply `$mailing-list-review` as the base workflow. This skill contains only
Git-project additions.

## Required context

Read the relevant parts of:

- `Documentation/SubmittingPatches`;
- `t/README` and `t/perf/README`;
- prior revisions and replies from `https://lore.kernel.org/git`;
- comparable commits, especially commits by current reviewers;
- overlapping topics in `next` and `seen`.

Read `references/maintainer-feedback.md` when reviewing messages, tests,
performance evidence, or revision mail.

## Git-specific design and tests

- Preserve dormant public state and alternate ref backends deliberately.
- Follow local fatal-error conventions instead of elaborate malformed-state
  recovery.
- Exercise every affected command and ref backend when logic is shared.
- Gate tests only on capabilities they require.
- Keep setup variables inside their `test_expect_success` block. Export only
  values needed by later `test_perf` subshells with `test_export`.
- Chain `test_when_finished` cleanup with `&&`.
- Prefer `test_seq -f` and batched `git update-ref --stdin` for large fixtures.
- Verify semantic output rather than object IDs created in another repository.
- Use `t/perf` for durable measurements and `hyperfine` for exemplar commands.
- Run `git clang-format --diff <commit>^ <commit>` for every patch. Apply any
  required formatting within that patch and rerun it until the diff is empty.
- For ref and commit-graph work, test realistic packed-ref, backend, generation
  number, and negative-query cases when relevant.

## Git commit messages

Use the local `area: subject` convention. Keep the complete subject at or
below 50 characters and hard-wrap commit-message body prose at 72 columns.
Explain the mechanism and policy, not merely a heuristic or internal helper.
Remove lab-notebook detail that does not help reviewers evaluate the claim.

Use only recognized trailers. Do not invent AI attribution trailers. When a
historical discussion materially supports a decision, summarize it and cite it
in prose rather than appending an unexplained `Link:` trailer.

## Git revision mail

Git expects successive versions in one thread. Send each revision as a reply
to the preceding revision and verify the full `References` ancestry. A
changelog link is not a threading substitute.

Determine recipients with relevant history, prior reviewers, and:

```sh
perl contrib/contacts/git-contacts <revision-or-patch>
```

Render with `b4 send --dry-run --no-sign` and apply the base skill's outgoing
mail review. Normally send at most one revision per day; batch minor feedback
unless a prompt reroll avoids wasting reviewer time.
