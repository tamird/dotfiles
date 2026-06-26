# Evidence-backed BPF review lenses

Use these threads as starting points. Re-read the complete threads with
`~/code/b4/liblore`, inspect newer accepted work on the affected paths, and
refresh `MAINTAINERS` before applying a lens. A review lens is not a claim
that a maintainer will object, and it is not automatically a recipient.

## Alexei Starovoitov: subsystem boundary and existing mechanisms

- In the raw-ELF-in-kernel RFC, Alexei rejects moving libbpf's ELF protocol
  into the kernel because doing so would turn a userspace format into a
  permanent kernel contract. He redirects the use case to light skeletons:
  <https://lore.kernel.org/bpf/CAADnVQLxgD_7GYWZZ49aY2LqVYOy4uGvK2ikm7MJ1Cj60VPNaw@mail.gmail.com/>.
- In the follow-up, he asks for the specific unsupported relocation rather
  than accepting a broad claim and explains that light skeletons preserve
  CO-RE and carry BTF:
  <https://lore.kernel.org/bpf/CAADnVQLYeV8-nJ-=_4p8U=xax99-i5QavJrQ=hnKS0EK1ZjecA@mail.gmail.com/>.

Review for the correct kernel/userspace boundary, accidental permanent
contracts, concrete gaps in existing mechanisms, and unnecessary new
concepts.

## Andrii Nakryiko: libbpf contracts and bisectable series

- The open-coded iterator implementation spells out constructor, sticky
  exhaustion, destructor, state-size, nesting, and composition contracts:
  <https://lore.kernel.org/bpf/20230308184121.1165081-4-andrii@kernel.org/>.
- Discussion of `btf_dump__new()` shows attention to extensible opts,
  symbol compatibility, callback consistency, and C++ consumers:
  <https://lore.kernel.org/bpf/CAEf4BzZGwUkE0aYLdVk6QaXfuv=BHFwOiJdqM=_RVm3BzNYKfw@mail.gmail.com/>.
- Review of the libbpf error-reporting series catches a split that breaks
  intermediate commits:
  <https://lore.kernel.org/bpf/CAEf4BzYQc+ijF78vX14CXi9My7hJ_+XNpnh1ZcMjpcdT1czHmA@mail.gmail.com/>.

Review public naming and ownership, opts and reserved-space evolution,
static and shared ABI, generated API consumers, and every intermediate
commit.

## Tejun Heo: semantic fit, state footprint, and useful composition

- Tejun questions a cgroup "iterator" that does not iterate and asks
  whether an existing execution mechanism fits better:
  <https://lore.kernel.org/bpf/YodGI73xq8aIBrNM@slm.duckdns.org/>.
- DSQ iterator review examines caller-owned state size, removes unused
  fields before considering allocation, and asks which assignments are
  actually required:
  <https://lore.kernel.org/bpf/Zn81srqbHfKBC7zZ@slm.duckdns.org/>.
- The v4 follow-up discusses whole-series rerolls, unlocked versus locked
  checks, patch splitting, and whether the example demonstrates a useful
  operation:
  <https://lore.kernel.org/bpf/Zox4_MHR9HiwmtHt@slm.duckdns.org/>.

Review whether the abstraction describes the operation, whether state and
lifecycle are justified, whether composition is real, and whether the
example demonstrates more than API syntax.

## Quentin Monnet: bpftool scope, dependencies, and build behavior

- Review of an LLVM disassembler plug-in covers why a dependency should be
  separated, static-build behavior, install paths, fallbacks, build wording,
  and commit-message structure:
  <https://lore.kernel.org/bpf/f2b8227f-528e-4fbd-aa2a-d86986565f87@kernel.org/>.
- Bootstrap libbpf review distinguishes host and target flags and asks that
  filtering and comments be no broader than necessary:
  <https://lore.kernel.org/bpf/2b72da46-bf83-406f-bf5b-022f8e0ac04f@kernel.org/>.
- Review of explicit dependency skips confirms consistent internal naming
  and clear unsupported-command behavior:
  <https://lore.kernel.org/bpf/ad8a783b-7b8c-46f2-9a3c-953315aafe38@kernel.org/>.

Review command boundaries, normal and bootstrap builds, optional features,
static builds, install behavior, and whether a dependency is truly needed by
the selected command set.

## Daniel Borkmann: reuse build concepts and cover alternate link modes

- Dynamic-libbpf review asks to reuse existing build concepts rather than
  add a confusing parallel variable, explains the internal/public API
  boundary, and retains static linking as the default:
  <https://lore.kernel.org/bpf/f6e8f6d2-6155-3b20-9975-81e29e460915@iogearbox.net/>.
- The follow-up asks for Makefile documentation and a build test covering
  the new dynamic-link mode:
  <https://lore.kernel.org/bpf/9853054b-dc1f-35ba-ba3c-4d0ab01c8f14@iogearbox.net/>.
- A small bpftool portability patch was accepted with a conventional local
  layout fix during application:
  <https://lore.kernel.org/bpf/c23c7c37-8d4e-e9ad-3fa0-a41da3b7aefa@iogearbox.net/>.

Review build-interface coherence, public versus internal dependencies,
alternate link modes, documentation, and coverage of the new build path.

## Eduard Zingerman: complete state propagation and recursive cases

- Review of `bpf_program__clone()` checks whether every paired option and
  inherited property is propagated, and withdraws a concern after comparing
  the existing path:
  <https://lore.kernel.org/bpf/83cf0430bf164c46abe56d2ec6565ca57ead1663.camel@gmail.com/>.
- BTF dump review identifies state leaking through a recursive type and
  suggests passing the state directly instead of mutating shared state:
  <https://lore.kernel.org/bpf/d5a578c01f8a2d4d95ca16e0a9ee5b9bfce1c30e.camel@gmail.com/>.

Review paired fields, inherited defaults, comparison with the existing
path, recursion, and shared mutable traversal state.

## Cover libbpf and bpftool host-tool concerns

At minimum, cover these independent lenses:

- subsystem and compatibility boundary: BPF core maintainers;
- libbpf API, object model, ABI, and generated loader: current libbpf
  maintainers;
- bpftool command and build behavior: current bpftool maintainer;
- BTF parsing and dumping: current BTF owner when those paths change;
- selftests and generated artifacts: current BPF selftest owners;
- host-tool and cross-build history: recent authors and reviewers of the
  affected Makefiles.

Use Tejun's lens for iterator, lifecycle, ownership, or abstraction-design
questions, but add him as a recipient only when touched paths, prior
participation, or the proposal's domain warrants it.
