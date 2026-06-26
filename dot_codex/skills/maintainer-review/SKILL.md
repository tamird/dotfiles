---
name: maintainer-review
description: Review a cumulative repository change through evidence-backed expectations of relevant maintainers and affected paths. Use before declaring substantive implementation complete, before requesting maintainer review, or when local review history should shape a design or patch.
---

# Maintainer Review

Apply `$audience-aware-writing` to the findings and related prose. Apply
`$efficient-repo-tools` when gathering broad path or review history.

Review the complete merge-base delta, not only the latest commit or working
tree. Derive maintainer expectations from evidence; do not imitate tone or
invent preferences. Review only: do not edit files or post comments unless the
user asks.

## Establish the review lens

1. Identify the repository, merge base, complete changed-file set, and the
   behavior and ownership boundaries affected.
2. Identify relevant maintainers through path ownership, accepted commits, and
   substantive review history. Treat ownership and automated assignments as
   routing hints rather than proof of expertise.
3. Inspect nearby code, accepted changes, and reviews of the same paths or
   behavior. Prefer directly relevant evidence over merely recent evidence.
4. Record the local design, coding, testing, comment, documentation, and review
   expectations supported by that history.

Use the same evidence that informed implementation. Refresh it when the scope
or design changes materially.

## Review the cumulative change

Start with behavior and design:

- What concrete problem changes?
- What owned the behavior before, and what owns it afterward?
- Which semantics, supported cases, failure modes, and costs change?
- Does the implementation follow the affected project's conventions?
- Could an existing mechanism solve the problem with fewer concepts?

Then inspect correctness, repository-wide cost, performance evidence, tests,
generated artifacts, comments, documentation, and review prose. Look for
special cases or compatibility layers that indicate a design problem.

Do not apply a historical preference mechanically. Reconcile each finding with
the intended invariants and current constraints, then prefer the correction
that simplifies the overall model.

## Close the workstream

Lead with actionable findings ordered by severity and grounded in concrete
files and lines. Separate confirmed defects from questions that need evidence.
When implementation is in scope, send valid corrections back to the existing
implementers when practical, then review the cumulative result again. If the
change is clean, say so and name any residual risks.

When asked to post GitHub feedback, batch non-overlapping findings in one
review. Reply in the existing thread when responding to an inline comment.
