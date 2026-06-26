---
name: bpf-upstream-review
description: Prepare, review, reroll, and respond to Linux BPF subsystem patch series covering kernel BPF, libbpf, bpftool, BTF, generated skeletons, and BPF selftests. Use in Linux kernel trees when work targets bpf or bpf-next and needs BPF-specific lore archaeology, API and ABI review, evidence-backed maintainer review lenses, per-commit validation, or b4 mail preparation.
---

# BPF Upstream Review

Apply `$linux-upstream-review` first. It already applies the mailing-list and
maintainer-review bases. This skill adds only BPF-specific design, reviewer,
build, and submission constraints.

## Establish the boundary

1. Read `Documentation/bpf/bpf_devel_QA.rst`, the affected BPF docs, and
   the current `MAINTAINERS` entries.
2. Identify the integration tree and base. Use `bpf` for fixes and
   `bpf-next` for features, cleanups, and other improvements.
3. Trace the complete ownership boundary before designing the series:
   kernel ABI, libbpf parsing and runtime, bpftool, compiler output,
   generated artifacts, and consuming applications.
4. Separate host behavior from target behavior. For cross-build changes,
   state which programs run on the build host, which artifacts target
   Linux, and which kernel interfaces are genuinely required.
5. Find the closest existing mechanism before adding another concept.
   Account for public APIs, ELF and BTF conventions, generated formats,
   and light skeletons as compatibility commitments.

For BPF mail on this machine, run `mbsync -q bpf`, then index `~/Mail/bpf`
with `lei index -r`. The Gmail label and isync channel are both named `bpf`;
do not route them through `rfl-mail`.

## Select BPF review lenses

Read [reviewer-committee.md](references/reviewer-committee.md) when
selecting reviewers or performing maintainer-style review passes.

- Derive formal recipients from current `MAINTAINERS`,
  `scripts/get_maintainer.pl`, affected-path history, and prior thread
  participants.
- Keep the review-lens set distinct from the recipient list.
  A useful design lens does not automatically justify a Cc.
- Refresh representative lore threads for the affected subsystem. Use
  the reference as a seed, not as permanent evidence of current ownership
  or opinion.
- Base each review lens on concrete emails and accepted history. Do not
  invent personality traits or mechanically predict an individual's
  response.
- Include reviewers from the actual ownership paths and varied
  affiliations. Add adjacent-domain reviewers only when their expertise
  bears on the design.

## Add BPF review lenses

Review the whole series, including the cover letter and every commit, through
these BPF-specific lenses:

1. **Boundary and need**: Is the user-visible problem demonstrated? Does
   the change live in the correct layer? Is an existing mechanism being
   missed?
2. **Conceptual model**: Does the API name match its behavior? Can one
   mechanism replace wrappers, callbacks, compatibility branches, or
   duplicated state machines?
3. **libbpf API and ABI**: Check naming, ownership, lifecycle, error
   semantics, opts extensibility, reserved space, `libbpf.map`, static and
   shared linking, C and C++ consumers, and behavior of existing callers.
4. **bpftool and build system**: Check bootstrap versus target flags,
   feature detection, static builds, optional dependencies, install paths,
   command scope, and consistency with existing build variables.
5. **ELF, BTF, and generated artifacts**: Check endianness, alignment,
   malformed input, recursive state, section and symbol behavior, and
   byte-for-byte output stability where output is intended to be stable.
6. **Correctness and errors**: Review every partially initialized state,
   cleanup path, short I/O, integer boundary, failure latch, and behavior
   after an error.
7. **Tests and series shape**: Require meaningful regression and negative
   coverage, file-local test style, per-commit buildability, and clean
   separation of prerequisites, behavior, and policy.
8. **Permanent prose and mail**: Review commit messages as code. Keep
   revision history in the cover letter and verify trailers, recipients,
   threading, and the rendered mail.

For portability work, reject a design that exposes Linux runtime APIs as
Darwin stubs merely to make linkage succeed. First isolate and prove an
offline Linux host-tool boundary, then add platform support to that
boundary.

## Construct and reroll the series

- Make preparatory refactors behavior-neutral and independently useful.
- Put behavior and its coverage in the same patch unless the coverage is
  itself a reusable prerequisite.
- Avoid hiding broad cleanup in a feature patch.
- Preserve generated output unless a deliberate format change is part of
  the proposal.
- On every revision, resend the complete series. Explain only actual
  changes since the preceding posted version in the cover letter.
- Maintain a lore feedback ledger and review each disposition before
  changing the code.

## Validate

Use the checkout's canonical BPF workflow and any user-specified output
directory. In addition to the Linux skill's checks:

- Build every commit independently when public headers, libbpf internals,
  bpftool bootstrap code, or generated artifacts change.
- Build the affected libbpf static and shared forms and inspect exported
  symbols when ABI is touched.
- Build normal and bootstrap bpftool paths when host-tool logic changes.
- Compare generated BTF dumps, linked objects, skeletons, light skeletons,
  and subskeletons against the parent when output should be unchanged.
- For cross-build changes, exercise host and target compilers separately;
  do not let target flags leak into host tools.
- Run focused BPF selftests first, then broader BPF CI proportional to the
  risk.
- Run `git clang-format --diff <commit>^ <commit>` for every commit,
  `scripts/checkpatch.pl`, and `git diff --check`.
- Render the exact series with b4 and inspect the whole thread before
  sending.
