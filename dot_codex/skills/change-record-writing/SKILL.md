---
name: change-record-writing
description: Write or revise commit messages, pull request titles and descriptions, and precursor records as concise, evidence-backed accounts of the cumulative change, its cause, and its observable effect.
---

# Change Record Writing

Apply `$audience-aware-writing`. Follow the actual repository contribution
rules and the user's applicable writing policy; do not turn either into a
universal convention.

## Establish the change

Inspect the complete merge-base change, authoritative producer, actual
consumer, affected owner, original invariant, and observable behavior. Lead
with what fails or needs to change, who or what it affects, and why the final
correction is necessary. Explain how the producer causes the consumer-visible
effect and how the change corrects it. Independently reviewable prerequisites
must explain their own problem and relationship to the eventual change.

Distinguish a source fix from a mitigation. If the cause is unknown, say so;
explain why a bounded mitigation is warranted, how original evidence and
observability remain available, and what ends the mitigation. Do not imply
that a retry, reconstruction, synthetic reproduction, or correlation proves
an unverified cause. For a surviving fallback or deferred cleanup, identify
the actual owner, necessary prerequisite, and concrete removal condition.

For a regression, establish and cite the original invariant, introducing
change, distinct exposure or rollout, trigger, concrete failure, test or CI
gap, and final correction and regression coverage. Distinguish introduction
from exposure, cause from symptom, and proof from inference. Explain why a
platform-specific change applies on that platform, what occurs elsewhere,
and whether the simpler shared alternative actually works. State measurable
performance claims only with relevant measurements.

If a material causal fact cannot be verified, investigate before describing
the change. Do not invent intent, users, effects, guarantees, measurements,
historical failures, or a rationale inferred from unrelated conversation.

## Write the durable record

Write a concise, discriminatory account of the final cumulative behavior,
not a chronology or inventory. Explain non-obvious decisions and only the
context needed to evaluate them. Cite primary evidence directly: source,
introducing commit, failing job, authoritative design, or behavioral test.
A conversation may establish coordination but cannot replace technical
evidence or make the reader discover the incident analysis elsewhere.

Follow current repository contribution rules and representative accepted
changes in the affected component for subject capitalization, wrapping,
required test plans, citation conventions, and area prefixes. Do not import
a prefix from another checkout, a generic example, or a single outlier; omit
it when local history is mixed and no rule or user instruction requires it.
Keep both commit subjects and pull-request titles at or below 50 characters,
including any prefix.

Prefer short paragraphs and real newlines. Write commit messages as plain
text and hard-wrap their body prose at 72 columns. Do not hard-wrap
pull-request descriptions; keep their raw text immediately readable without
a Markdown renderer. Cite same-repository commits with
unfenced SHAs of at least nine characters, extending them when uniqueness or
linkification requires it. Link directly to authoritative external artifacts
with numbered references in the prose and a compact list of URL definitions
after the final paragraph, such as `[1]` and `[1]: https://example.com`. Do
not use inline Markdown links, HTML, images, badges, collapsible sections,
decorative emphasis, or other renderer-dependent markup. Simple bullet
lists, aligned plaintext-readable tables that also happen to be Markdown,
and fenced fragments containing actual code or similarly structured material
are acceptable only when they materially clarify the change.

Avoid section headings, literal `\n`, filler about unchanged behavior, and
unsupported claims. Long lists suggest an inventory rather than a coherent
change; explain the unifying behavior and retain only necessary distinctions.
Never include a validation inventory, passing-check summary, test count,
execution command, or testing diary in a commit message or pull-request
description; CI owns validation results. Describe testing strategy only when
it clarifies a regression, meaningful behavioral coverage, or remaining risk.

Exclude task priority, work queues, agents, checkouts, monitoring, personal
coordination, who noticed the issue, local commands, and testing diaries
unless an explicitly required detail explains observable behavior. Explain
extracted precursors independently; add tracking comments only when requested
or required by the actual repository.

## Respect the authorization boundary

Writing does not authorize editing product code, another author's record,
publishing, soliciting or submitting review, changing pull-request state, or
merging. Do not change Git identity, attribution, signing, hooks, HTTP
configuration, or credentials. Keep any authorized delegated identity in
its intended review or comment, never in a commit identity.

When a record mutation is separately authorized, use the normal typed API or
CLI and verify the resulting title, exact body, actual newlines, and rendered
paragraphs. Otherwise return the requested text without publishing it.
