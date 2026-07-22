# Tamird review lenses and historical evidence

These examples establish recurring review standards. They are evidence, not
rules to apply mechanically. Prefer newer, path-relevant history when a
change differs materially from these examples.

The initial history pass covered public activity from 2011 through 2026:
approximately 6,967 commented-on PRs and 1,150 formally reviewed PRs across
Rails/Arel/mysql2, CockroachDB, gRPC/gVisor, Go/Rust/Aya/BPF, BuildKit, and
other projects. GitHub's formal-review API does not cover the oldest years, so
early evidence comes from substantive inline/issue comments. Date-partitioned
search avoids the API's 1,000-result cap.

## Test falsification, not test volume

In [aya-rs/bpf-linker#151](https://github.com/aya-rs/bpf-linker/pull/151), a
negative `CHECK-NOT` assertion could pass even if no BTF were emitted at all;
the requested correction was to add another enum that proves output exists.
The useful question is: what plausible broken implementation makes this test
fail? Apply that question to affected pre-existing tests too. A mock assertion,
loading assertion, or large fixture does not establish behavior by itself.

That standard is stable across the history: a
[2013 Rails review](https://github.com/rails/rails/pull/11694#discussion_r18134110)
explicitly notes an assertion did not fail even before the change and asks what
is actually under test; a
[lib/pq review](https://github.com/lib/pq/pull/661#discussion_r143672834)
asks for the specific error rather than any non-nil error; and a
[gVisor review](https://github.com/google/gvisor/pull/1995#discussion_r391310144)
asks whether the defensive-check failure case is covered. Test the real
contract and remove duplicated/dead suites instead of multiplying them, as in
[aya-rs/aya#1318](https://github.com/aya-rs/aya/pull/1318).

## Precise contracts instead of facts at a distance

Public Rust reviews repeatedly prefer a closed enum/config
so invalid state is unrepresentable, use precision-safe conversion instead of
`as`, align widths, and avoid lossy path conversions in
[aya-rs/aya#1365](https://github.com/aya-rs/aya/pull/1365) and
[aya-rs/aya#1038](https://github.com/aya-rs/aya/pull/1038). Earlier examples
ask [why a closed domain is not an enum](https://github.com/BurntSushi/ripgrep/pull/751#discussion_r162147489)
and reject a compatibility/default that hides a required choice in
[BrightSpots/rcv#608](https://github.com/BrightSpots/rcv/pull/608). Keep
known invariants in types and local control flow instead of `Any`, casts,
loose maps, boolean modes, checker suppression, or downstream validation.

## Explicit failure, decisions, and verifiable rationale

The [gVisor defensive-check review](https://github.com/google/gvisor/pull/1995#discussion_r391310144)
asks for the real failure path rather than silently accepting an unsupported
case. Keep failure contracts explicit and remove dead test code instead of
adding special cases.

A [protobuf review](https://github.com/gogo/protobuf/pull/341#discussion_r143318348)
rejects a comment that merely restates code and asks that it explain why. A
[configuration review](https://github.com/BrightSpots/rcv/pull/605#discussion_r939713641)
requests a citation and reproducible update command for a non-obvious input.
Policy belongs near its owner with a verifiable source; vague comments,
unsupported facts from elsewhere, and unexplained decisions become
uncheckable folklore.

The same standard applies to deferred work: a TODO must explain not only what
remains, but why it could not be completed here and what concrete condition
would make it actionable. Delete stale comments, and require an inline reason
for a platform constraint or other non-obvious exception; Tamir made both
requests in
[a dependency review](https://github.com/openai/openai/pull/1163240#discussion_r3624669587)
and
[the accompanying platform-constraint discussion](https://github.com/openai/openai/pull/1163240#discussion_r3624674799).
When a local path requires many citations to distant owners, implementations,
or policies merely to be understood, treat that citation density as evidence
that the ownership boundary or design should be simplified.

## Reuse upstream behavior and reject compatibility-shaped complexity

In [lima-vm/lima#2985](https://github.com/lima-vm/lima/pull/2985), the review
challenges a copied OSS implementation, fake/no-op `net.Conn` methods, an
empty type, and impossible paths that returned nonsense. The standard is to
verify the upstream bug/limitation, prefer fixing or reusing the real
abstraction, and make impossible states fail clearly. Apply the same scrutiny
to local reimplementations, fallbacks, and speculative migration layers.

Reduction also means tracing the actual callers: inline a
[single-caller function](https://github.com/grpc/grpc/pull/28667#discussion_r791176504),
remove a
[needless function-returning-function](https://github.com/moby/buildkit/pull/6015#discussion_r2212401033),
and check for the
[same bug in sibling cases](https://github.com/cockroachdb/cockroach/pull/17453#discussion_r131625140).
Unexpected wrappers, conversions, builders, or duplicate branches are design
feedback, not structure to preserve automatically.

## Repository-wide cost and live consumers

A [protobuf change](https://github.com/protocolbuffers/protobuf/pull/8854)
needed its stale Makefile consumer caught, while a
[CockroachDB review](https://github.com/cockroachdb/cockroach/pull/17453#discussion_r131625140)
explicitly asks for the same bug to be checked in sibling cases. Trace all
consumers and quantify repository/startup/runfile/action tax; apparently local
automation can impose a global cost.

## Performance claims need numbers and platform reality

Require the relevant before/after journey, cold/warm distinction, platform,
compiler/runtime context, and cost decomposition. The recurring standard is
explicit: ["Let's talk numbers"](https://github.com/brianmario/mysql2/pull/463#issuecomment-30886752),
challenge an
[implausible benchmark ordering](https://github.com/grpc/grpc-go/pull/1597#discussion_r146326372),
and enumerate the cost before dropping platform coverage or optimizing a path
that may not matter. Validate real downstream consumers and distinguish merge
skew or infrastructure failure from a branch regression.

## Large cumulative changes require design-level review

[aya-rs/aya#1063](https://github.com/aya-rs/aya/pull/1063) spans a large
feature-probe change and review across revisions: exhaustive variants,
comments/citations, duplicate helpers, unrelated semantic changes, and
commented-out assertions all required attention. Separate generated churn from
handwritten design, trace each integration/failure path, and ask what the new
foundation makes obsolete. Code volume and green CI are not proof that the
design is necessary.

Movement-heavy changes need even stricter treatment. The
[aya-rs/bpf-linker#295 review](https://github.com/aya-rs/bpf-linker/pull/295#discussion_r2399944023)
calls out that extensive movement makes review difficult and destroys useful
history; separate movement from behavior, preserve history where practical,
and re-review every affected path. Mixed changes belong in coherent commits,
not one opaque migration.

## Refreshing relevant history

Refresh the historical corpus only from public, non-OpenAI repositories.
Reviews on `openai/openai` may have been authored by Codex while acting for
Tamir and must not be used as evidence of Tamir's personal review style.
Sample substantive reviewed PRs with bounded GitHub queries, then read the
actual reviews and inline comments on the most relevant results. For example:

```bash
gh search prs '<subsystem-or-path-keyword>' \
  --repo aya-rs/aya \
  --reviewed-by tamird \
  --limit 50 \
  --json number,title,url,updatedAt,state
```

Use exact repository/PR/path history and `$efficient-repo-tools`; do not run
unbounded repository traversals. Review history is evidence of expectations,
not a reason to preserve stale conventions.
