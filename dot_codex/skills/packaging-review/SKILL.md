---
name: packaging-review
description: Review Python packaging, dependency resolution, interpreter and platform selection, lock generation, bootstrap, wheel safety, typing, and repository-wide cost. Use for evidence-backed package, installer, resolver, or dependency-universe review.
---

# Packaging Review

Apply `$maintainer-review` to the cumulative change and
`$efficient-repo-tools` to bounded source and consumer discovery. Review does
not authorize publishing, implementation, reviewer outreach, a delegated
identity, or private access. Consult
[references/review-lenses.md](references/review-lenses.md) when public
packaging history helps resolve the actual question. Only when explicitly
relevant and user-authorized, consult the optional owner-only
`~/Google Drive/My Drive/Codex/runtime/review-monitor/reviewer-profiles.md`; an absent
profile is not a defect.

## Establish the real package boundary

Identify the source that owns declared dependencies, interpreter and
platform selection, extras, constraints, indexes, build metadata, lock
generation, distribution artifacts, installation, and startup. Trace the
real resolver, installer, generated output, runtime consumer, fallback, and
failure path. Distinguish the checkout being analyzed from the source that
is actually running.

Change the authoritative declaration and use its canonical generator. Reject
parallel locks, copied constraints, metadata overrides that replace unrelated
upstream declarations, unowned local indexes, hand-maintained generated
artifacts, broad ignore rules, and additional bootstrap machinery when the
existing owner already expresses the requirement. Require a real supported
consumer for an extra, compatibility path, optional import, or exception.

Check dynamic dependencies, source distributions and wheels, supported
interpreter versions, platform markers, dependency groups, concurrent access,
cache identity, fail-closed error propagation, and repository-wide build and
action selection. Remove superseded machinery after migrating all actual
consumers. Keep public and private dependency sources at their explicitly
authorized boundary.

## Validate impact and failure evidence

Measure installation, resolution, network, import, filesystem, startup,
runfiles, or generated fanout on the actual affected workflow. Compare
controlled before-and-after results, supported platforms, and cold versus
warm cache behavior. A warm remote-cache hit is not evidence of an expensive
local rebuild; a wheel-only improvement is not evidence of end-to-end
application startup gains.

Do not infer production cache corruption from an artificial fixture, a retry
on another worker, or a later successful download. Establish the original
artifact, digest, authoritative producer, cache and worker identity,
concurrency, first failure, and incidence. A justified temporary mitigation
must retain that evidence, expose activation metrics, bound and fail-close
recovery, measure healthy-path cost, and name the source owner and removal
condition. Otherwise correct or expose the source; do not normalize a broad
installer retry or fallback.

For packaging tests, identify the real incorrect declaration, resolution,
installation, import, or generated output they would catch. Require precise
types and meaningful behavioral coverage; do not accept mocked resolver
plumbing or a green lock check as proof of a new architecture. Report only
falsifiable findings supported by the actual package, downstream consumer,
maintainer evidence, and current validation.
