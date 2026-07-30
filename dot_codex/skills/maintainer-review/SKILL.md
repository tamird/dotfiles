---
name: maintainer-review
description: Review a complete change for its evidenced need, ownership, invariants, meaningful coverage, precise contracts, measured cost, change record, and authorized review verdict.
---

# Maintainer Review

Use `$efficient-repo-tools` for bounded evidence, `$coding-style` for design
and implementation criteria, `$change-record-writing` for the rendered record,
and `$audience-aware-writing` for findings. A review authorizes no source
edit, publication, outreach, identity change, new workstream, or merge.

## Establish why the complete change belongs

Verify the exact repository, author, full current head, target, merge base,
complete changed files, unresolved discussion, and actual validation. Page
provider results completely. Distinguish source from generated output, locks,
fixtures, vendoring, and mechanical change.

Trace the real producer, consumer, entrypoints, supported platforms, failure,
ownership, and invariant. Review the cumulative change, including a live or
merged parent or child when together they introduce or consume an interface.
Inspect pre-existing code only when the change depends on or exposes it.

Require an evidenced answer: what actually fails or is needed, whom it
affects, why the existing mechanism cannot handle it, why this owner is
correct, and how this change repairs the source. Approval, passing checks,
implementation detail, or assertive prose is not evidence of necessity.

Increase scrutiny for hidden executable logic, broad handwritten changes,
parallel policy or selectors, sensitive production behavior, unproven
recovery, and expanding legacy. Mechanical breadth and author identity are
not findings. Use private maintainer history only when the user authorizes
the actual profile, and substantiate every conclusion independently.

## Test the design, coverage, and cost

Apply `$coding-style` to canonical ownership, supported consumers, dependency
boundaries, meaningful regression tests, precise checked types, comments,
deferred cleanup, and shared-platform behavior. Report the actual violated
contract; do not reject legitimate dynamic or generated interfaces.

Challenge duplicate mechanisms; unsupported fallbacks, compatibility paths,
ignores, or dynamic imports; hidden source embedded in shell or configuration;
silent errors; lost evidence; obsolete parallel machinery; and unaccounted
shared startup, network, resolution, generation, or action cost. Accept
small, justified boundary glue.

For each test, identify a plausible broken implementation that would fail.
Reject tautologies, unverified mock or import assertions, incidental
snapshots, and oversized fixtures. Verify relevant existing contracts and
flag avoidable `Any`, unchecked casts, suppressions, broad exceptions,
ambiguous flags, magic literals, and non-exhaustive domain handling.

Require the actual explanation for a platform-specific correction, behavior
on other supported platforms, and evidence whether one common fix works.
Support measurable performance claims with the affected workflow, baseline,
before and after, cache conditions, and memory or sharing costs.

## Establish incidents and escaped failures

Trace an incident to its original artifact, producer, worker, cache identity,
timing, and first-party failure. A later successful retry, different worker,
synthetic corruption, or correlation is not a cause. Reject mitigation that
hides recurrence or weakens a healthy path; a necessary mitigation must
retain evidence, expose activation, fail closed, bound cost, and identify its
owner, justification, and removal condition.

For a default-branch regression, establish the introducing change, trigger,
actual failed job, selected tests, merge gate, environment, and why the
defect was allowed to land. Require regression coverage or a correction to
the real selection or required-check gap. If prevention is infeasible,
identify its primary evidence, owner, and blocker. Do not invent a wider
incident or initiative.

## Review the record and deliver the right verdict

Apply `$change-record-writing` to the actual title and rendered cumulative
description, including its pull-request title-length limit, causal reason,
primary citations, platform rationale, and the repository's real formatting.
Never invent an author's rationale or edit another person's record without
explicit authorization.

Before approving or disputing a citation, verify the provider's first-party
raw Markdown `body`, its actual link destination, and the concise supporting
evidence. Rendered or plain `bodyText` cannot establish a link's destination.

Rank substantiated findings by security, correctness, data, production cost,
and maintainability. Explain the concrete trigger, violated invariant,
affected consumer, impact, and smallest source-owned correction. Anchor each
independent source defect inline; use one concise overall comment for
cross-cutting design, prose, or unanchorable evidence. Batch repetition and
reply in the existing discussion.

Reserve a request-changes verdict for a genuinely severe, evidenced finding,
such as an exploitable security boundary, data loss, a production outage, or
a comparably serious correctness failure. A defect's label, author, volume,
or hypothetical severity is not enough. Leave ordinary correctness,
maintainability, testing, and documentation findings as neutral comments;
approve only when no relevant findings remain.

CI owns failed-check gating: do not request changes merely because a check is
red, pending, or unrelated. When sound code has only a deficient description,
leave a neutral finding; neither approve nor request changes. Verify the
repository's actual owner scope, draft policy, neutral-only requirements,
and explicitly authorized delegated attribution; do not claim an approval
satisfies another owner's gate. Publish only when authorized, reverify the
exact head and inline anchors, and verify the resulting provider receipt.
