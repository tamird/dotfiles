---
name: coding-style
description: Design, implement, and review coherent, correct, precisely typed changes grounded in real ownership, meaningful behavioral tests, incident evidence, bounded mitigations, canonical generation, and measured impact.
---

# Coding Style

Use `$efficient-repo-tools` when establishing repository evidence. Verify
task-specific restrictions directly; implementation guidance does not
authorize publication, review, or outreach.

## Establish the design

- Read all applicable checked-in implementation and testing instructions,
  including fixture, generator, and execution-environment sections. Mandatory
  requirements override historical exceptions and nearby shortcuts.
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

## Begin every code review with first principles

Apply this design pass automatically to every code, pull-request, or patch
review before listing tactical defects. A patch-only review is incomplete.

- Verify the actual failure, affected user, and desired behavior; do not
  accept the proposed diagnosis or intervention point without evidence.
- Trace the complete causal chain through the producer, consumer, resource
  owner, lifecycle, supported execution modes, and existing cleanup.
- Ask whether the change fixes the authoritative source or compensates for
  it in a shared wrapper, downstream consumer, fallback, or test harness.
- Compare the complete architecture with source-level correction, existing
  primitives, deletion, and alternatives with an appropriate blast radius.
- Account for every new test: require a distinct real failure, reject tests
  that only validate the workaround, and prefer existing owner-level coverage.
- Lead with an evidenced ownership or design flaw and the coherent alternative;
  do not present its tactical symptoms as though the architecture were sound.

## Choose the right design, not the smallest patch

- Optimize for a coherent design that solves the actual problem at the right
  ownership boundary. The smallest edit, shortest diff, and fewest lines are
  not the objective; a broader redesign is appropriate when the existing
  model, interface, or division of responsibility is wrong.
- Treat repeated tactical fixes, recurring review findings, multiplying
  special cases, and accumulating flags or fallbacks as evidence of a flawed
  design. Stop plugging holes, reconsider the end-to-end requirements and
  invariants, and replace the structure causing the family of failures.
- Define the actual user requirement before adding branches, interfaces,
  policy, metrics, compatibility paths, or speculative edge-case machinery.
  Remove superseded tactical scaffolding when the coherent design makes it
  unnecessary; do not preserve it as an accidental requirement.
- Inspect the cumulative merge-base diff after each substantive change. Count
  production and test lines separately and use growth, duplication, and churn
  as design diagnostics, not as a substitute for judging correctness or
  architectural coherence.
- Add only distinct, meaningful behavioral regressions. Reuse existing
  fixtures, collapse repetitive setup and overlapping scenarios, and reject
  mock-heavy or subprocess-heavy tests disproportionate to the behavior.
- Catch only the specific expected exception at the operation that produces
  it. Never swallow broad `Exception` or `OSError` merely for convenience;
  for an optional missing file, catch `FileNotFoundError` and let unexpected
  permission, filesystem, and other failures propagate.

## Enforce a strict behavioral-test budget

- Start from zero new tests. Before changing tests, identify the observed bug or
  supported contract, inspect existing owner-level coverage, and choose the
  smallest meaningful behavioral change.
- Add or retain a test only when it protects a distinct real failure or required
  contract, a plausible broken implementation would fail it, and existing
  coverage cannot already expose that failure. Explain this justification
  before writing the test. If any condition is missing, do not add it.
- Prefer extending one existing end-to-end or owner-level behavioral test over
  adding another test, fixture, helper, mock, snapshot, subprocess, or setup
  tree. Combine related failure variants in one concise table-driven test.
- Do not duplicate one invariant across unit and integration tests, transports,
  implementations, or fixtures unless their ownership or failure mechanisms
  genuinely differ. Remove tests invalidated or made redundant by a redesign.
- Never add tests for static definitions, removed behavior, speculative edge
  cases, tautologies, implementation details, negative-only trivia, or a test
  harness itself. Do not invent expensive fixtures merely to claim coverage.
- Audit cumulative merge-base production and test line counts before, during,
  and after implementation. If test setup dominates the change or scenarios
  overlap, stop, reassess, consolidate, and delete before adding anything.
- Before publication, account for every new or materially changed test: name
  its distinct demonstrated failure and why cheaper existing coverage cannot
  catch it. Delete any test that does not earn its maintenance cost.

## Make the contract explicit

- Make invalid states unrepresentable with closed enums, newtypes,
  exhaustive variants, and precise interfaces; avoid ambiguous flags,
  unnecessary casts, suppression, unchecked maps, and magic values.
- Match nested values one layer at a time: match the outer container first,
  then match its inner variants separately.
- Model each lifecycle phase independently. Include every input captured by
  in-flight work in its phase-specific identity, normalize effective defaults,
  and distinguish startup invariants from invariants after readiness.
- Trace atomic transitions across reads, awaits, and rechecks. A narrow race
  is still a correctness defect; classify states without dropping a valid
  transition and exercise controlled lifecycle boundaries deterministically.
- Prefer immutable bindings and expression-oriented data flow. Introduce
  mutation only when the algorithm, ownership, or measured performance
  requires it; localize and clearly bound that state.
- Keep required choices explicit, use lossless conversions, and test the
  exact error and unsupported failure rather than accepting any failure.
- Validate recoverable inputs and assert actual internal invariants.
- Define shared policy at its owner. While implementing, explain non-obvious
  intent, invariants, failure modes, ownership boundaries, patch selections,
  magic values, and pinned-input provenance. Cite independently checkable
  sources; do not restate the code or defer needed explanations to review.
  Explain why genuinely deferred work could not be completed.
- For each test, identify a plausible broken implementation that makes it
  fail. Prefer a focused behavioral regression to mock plumbing, snapshots,
  import assertions, tautologies, negative-only assertions, or oversized
  fixtures. Remove duplicated or dead tests instead of multiplying them.
- Use the repository's environment-aware fixture and runner constructors so
  new behavioral coverage actually executes across its supported foreign,
  sandboxed, and cross-platform test matrix.

## Keep clock domains separate

- Use a monotonic clock for elapsed time, deadlines, polling, retries,
  cancellation, and authentication or request budgets. Wall clocks can jump;
  never enforce a duration with calendar time.
- Use wall-clock time only for timestamps or external APIs that explicitly
  require Unix time. Convert externally supplied epoch deadlines to an
  absolute monotonic deadline once at the ownership boundary.
- Propagate that monotonic deadline unchanged across components. Preserve one
  immutable wall-to-monotonic anchor when refreshing or extending a deadline;
  do not re-anchor it after a wall-clock adjustment.
- Never compare or subtract values from different clock domains. Make the
  domain clear in names, contracts, and meaningful clock-jump regressions.

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
