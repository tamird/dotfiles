---
name: coding-style
description: Design, implement, and review concise, correct, precisely typed changes grounded in real ownership, meaningful behavioral tests, incident evidence, bounded mitigations, canonical generation, and measured impact.
---

# Coding Style

Use `$efficient-repo-tools` when establishing repository evidence. Verify
task-specific restrictions directly; implementation guidance does not
authorize publication, review, or outreach.

## Establish the design

- Identify the actual problem, producer, consumer, ownership boundary,
  supported platforms, invariants, and failure behavior.
- Prefer the canonical source, an existing interface, deletion, or a narrower
  requirement over a duplicate mechanism, wrapper, fallback, or flag.
- Keep each commit independently reviewable; separate unrelated cleanup,
  movement, behavior changes, and corrections. Preserve useful history when
  moving code.
- Review the complete change, not merely the latest edit or requested patch.
  Do not allow incidental existing code to become a design requirement.
- Ground review findings in a concrete broken contract, affected consumer,
  or demonstrated cost; distinguish correctness from preference and never
  mistake change volume, approvals, or green CI for design evidence.
- Put substantive executable logic in an independently readable, typed,
  testable source. Keep cross-language and bootstrap glue minimal.

## Make the contract explicit

- Prefer closed types, exhaustive variants, and precise interfaces; avoid
  unnecessary casts, suppression, unchecked maps, and magic values.
- Keep required choices explicit, use lossless conversions, and test the
  exact error and unsupported failure rather than accepting any failure.
- Validate recoverable inputs and assert actual internal invariants.
- Define shared policy at its owner. Comment on non-obvious intent rather
  than restating the implementation; cite independently checkable distant
  facts and explain why genuinely deferred work could not be completed.
- For each test, identify a plausible broken implementation that makes it
  fail. Prefer a focused behavioral regression to mock plumbing, snapshots,
  import assertions, tautologies, negative-only assertions, or oversized
  fixtures. Remove duplicated or dead tests instead of multiplying them.

## Diagnose failures and bound mitigations

- Trace the original failure through its actual artifact, producer,
  consumer, worker, version, cache, and invariant. Distinguish introduction
  from exposure, source from symptom, and infrastructure or merge skew from
  a product regression.
- Preserve the failing evidence and establish a real reproduction before
  claiming causality. A successful retry, synthetic fixture, reconstructed
  artifact, or different worker does not prove the original cause.
- Correct the authoritative source when possible. If an immediate source
  fix is unavailable, make any mitigation narrow, fail-closed, observable,
  and bounded in cost; identify its owner, remaining uncertainty, and a
  concrete removal condition.
- Cover the observed failure and unsupported paths with a behavioral
  regression. Do not suppress diagnostics, broaden an exemption, or encode
  an unproven runtime invariant to make an incident disappear.

## Respect the real cost

- Change the authoritative input and run its canonical generator.
- Check sibling consumers and generated outputs; delete single-use wrappers,
  unnecessary indirection, and superseded machinery instead of preserving
  them as an accidental design requirement.
- Declare dependencies at their owning boundary; avoid copied upstream
  behavior, broad exemptions, and speculative compatibility.
- Choose one coherent migration when it is simpler than permanent dual paths.
- In a broad migration, start with independently safe, narrow corrections;
  defer high-fanout rewrites until they are genuinely needed.
- Explain why a platform distinction is necessary; use a common correction
  when it works on all supported platforms.
- Support performance claims with the actual workflow, baseline, cache
  conditions, and relevant memory or sharing costs.
