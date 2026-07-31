---
name: packaging-review
description: Extend maintainer-history review with Python packaging, dependency resolution, supported interpreters and platforms, lock generation, distribution artifacts, and real downstream installation behavior.
---

# Packaging Review

Apply `$maintainer-review` first. Inherit its affected-path ownership research,
actual maintainer personas, personal `$coding-style` baseline, and change-record
review. This skill adds only packaging-specific sources, maintainers, failure
modes, and validation. Consult
[references/review-lenses.md](references/review-lenses.md) when the affected
packaging specification is relevant.

## Identify packaging-specific maintainers

Locate the actual owners of package metadata, lock generation, resolver or
installer integration, wheel builds, release workflows, and consuming
applications. Examine their recent changes and substantive reviews on the
affected package boundary; a general repository owner need not maintain its
packaging workflow.

Seed distinct packaging, release, resolver, or downstream-consumer personas
only when the repository history establishes their relevance. Prefer their
actual decisions about supported interpreters, architectures, compatibility,
dependency ownership, migration, and generated artifacts over assumptions
about what a packaging maintainer might want.

## Establish the real package boundary

Identify the source that owns declared dependencies, interpreter and
platform selection, extras, constraints, indexes, build metadata, lock
generation, distribution artifacts, installation, and startup. Trace the
real resolver, installer, generated output, runtime consumer, fallback, and
failure path. Establish the actual user problem and package owner before
adding bootstrap or compatibility machinery. Distinguish the checkout being
analyzed from the source that is actually running.

Change the authoritative declaration and use its canonical generator. Reject
parallel locks, copied constraints, metadata overrides that replace unrelated
upstream declarations, unowned local indexes, hand-maintained generated
artifacts, broad ignore rules, and additional bootstrap machinery when the
existing owner already expresses the requirement. Require a real supported
consumer for an extra, compatibility path, optional import, or exception.

Check dynamic dependencies, source distributions and wheels, supported
interpreter versions, platform markers, dependency groups, concurrent access,
cache identity, explicit fail-versus-skip behavior, fail-closed error
propagation, and repository-wide build and action selection. Prove a
runtime invariant before replacing uncertainty with an assertion. Remove
superseded machinery after migrating all actual consumers. Keep public and
private dependency sources at their explicitly authorized boundary.

## Apply domain-specific validation

Measure installation, resolution, network, import, filesystem, startup,
runfiles, or generated fanout on the actual affected workflow. Compare
controlled before-and-after results, supported platforms, and cold versus
warm cache behavior. A warm remote-cache hit is not evidence of an expensive
local rebuild; a wheel-only improvement is not evidence of end-to-end
application startup gains.

For packaging tests, identify the real incorrect declaration, resolution,
installation, import, wheel, or generated output they would catch. Verify
affected interpreter and architecture combinations through their actual
build or installation path. Report only findings supported by the package,
downstream consumer, applicable maintainer history, and current validation.
