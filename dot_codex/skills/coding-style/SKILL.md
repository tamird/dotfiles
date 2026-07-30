---
name: coding-style
description: Design and implement concise, correct, precisely typed changes grounded in real ownership, meaningful behavioral tests, canonical generation, and measured impact.
---

# Coding Style

Use `$efficient-repo-tools` when establishing repository evidence. Read the
private operator profile only when a user-specific restriction applies.
Implementation guidance does not authorize publication, review, or outreach.

## Establish the design

- Identify the actual problem, producer, consumer, ownership boundary,
  supported platforms, invariants, and failure behavior.
- Prefer the canonical source, an existing interface, deletion, or a narrower
  requirement over a duplicate mechanism, wrapper, fallback, or flag.
- Keep each commit independently reviewable; separate unrelated cleanup,
  behavior changes, and corrections.
- Review the complete change, not merely the latest edit or requested patch.
  Do not allow incidental existing code to become a design requirement.
- Put substantive executable logic in an independently readable, typed,
  testable source. Keep cross-language and bootstrap glue minimal.

## Make the contract explicit

- Prefer closed types, exhaustive variants, and precise interfaces; avoid
  unnecessary casts, suppression, unchecked maps, and magic values.
- Validate recoverable inputs and assert actual internal invariants.
- Define shared policy at its owner. Comment on non-obvious intent rather
  than restating the implementation; cite independently checkable distant
  facts and explain why genuinely deferred work could not be completed.
- For each test, identify a plausible broken implementation that makes it
  fail. Prefer a focused behavioral regression to mock plumbing, snapshots,
  import assertions, tautologies, or oversized fixtures.

## Respect the real cost

- Change the authoritative input and run its canonical generator.
- Declare dependencies at their owning boundary; avoid copied upstream
  behavior, broad exemptions, and speculative compatibility.
- Choose one coherent migration when it is simpler than permanent dual paths.
- In a broad migration, start with independently safe, narrow corrections;
  defer high-fanout rewrites until they are genuinely needed.
- Explain why a platform distinction is necessary; use a common correction
  when it works on all supported platforms.
- Support performance claims with the actual workflow, baseline, cache
  conditions, and relevant memory or sharing costs.
