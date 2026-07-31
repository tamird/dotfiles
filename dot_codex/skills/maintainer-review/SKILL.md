---
name: maintainer-review
description: Derive affected maintainers' technical review personas from ownership, commit history, prior reviews, and accepted changes, then apply those evidence-backed perspectives to a complete change before publication.
---

# Maintainer Review

Apply `$coding-style` and `$change-record-writing` as the user's own baseline;
they are not evidence of another maintainer's preferences. Use
`$efficient-repo-tools` for bounded repository discovery and
`$audience-aware-writing` for any authorized findings.

## Identify the actual review boundary

Establish the repository, exact head, integration base, complete change,
affected paths, interfaces, consumers, and unresolved discussion. Distinguish
handwritten source from generated output and incidental movement. Include
related changes only when together they introduce or consume the same
contract.

Identify the people who actually maintain those boundaries using checked-in
ownership, affected-path history, recent accepted changes, substantive review
comments, and the repository's contribution process. Commit authorship,
organizational affiliation, assignment, or an approval alone does not prove
maintainership.

Start with bounded path-specific history:

```sh
git log --follow -n 30 -- path/to/affected/file
git blame -L start,end -- path/to/affected/file
```

Inspect the corresponding reviews, discussions, and accepted alternatives
through the repository's actual first-party provider. Prefer recent comments
on the same subsystem, interface, failure mode, or design tradeoff. Never
invent private access or replace another maintainer's evidence with the user's
historical preferences.

## Construct evidence-backed maintainer personas

For each relevant maintainer or ownership boundary, derive:

- The subsystem and decisions that person actually owns.
- Recurring technical concerns demonstrated by their real comments or commits.
- Previously rejected approaches and the concrete reason they were rejected.
- Compatibility, testing, migration, performance, and submission standards
  that apply to this change.
- Whether the historical evidence is current, directly applicable, and
  consistent with the current source.

Ground each lens in independently attributable evidence. Distinguish a
repository requirement from an individual preference, a stale objection, a
resolved issue, or an unsupported inference. Do not invent personality traits,
imitate maintainers, or infer a technical standard from identity alone.

## Review through those personas

Inspect the complete change through each applicable maintainer lens before a
real reviewer has to raise the same issue. Trace the actual invariant,
producer, consumer, failure path, ownership, and validation relevant to that
lens. Check whether the change repeats a previously rejected design, violates
an established interface, omits an expected case, or leaves a foreseeable
maintainer question unanswered.

Apply the user's `$coding-style` and `$change-record-writing` separately; never
misattribute those preferences to repository maintainers. Where evidenced
maintainer expectations conflict, explain the concrete tradeoff instead of
inventing consensus.

Report only independently verified findings. Explain the affected code,
actual impact, supporting maintainer evidence, and smallest appropriate
correction; separate a blocking requirement from a question or stylistic
preference. Reviewing does not authorize editing code, publishing comments,
contacting maintainers, or merging.
