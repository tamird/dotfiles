# Observed Git Maintainer Feedback

Use this catalogue to recognize recurring review failures. It summarizes the
June 2026 discussions for four submitted series; follow the links when the
exact context matters.

## Contents

- Narrative and AI-generated prose
- Explain the mechanism and the policy
- Prefer the simpler existing path
- Split independent changes
- Tests and perf tests
- Performance counterexamples
- Historical citations and trailers
- Revision threading and cadence
- Source thread roots

## Narrative and AI-generated prose

- A commit message is not a lab notebook. Preserve the causal story and the
  minimum useful performance evidence; omit incidental flags, hardware, RAM,
  and setup details unless they affect interpretation. Jeff King called out
  verbose, semi-relevant detail and supplied a much shorter workload/result
  narrative. Patrick Steinhardt emphasized that incoherent story structure is
  worse than length alone. Junio Hamano agreed that contributors must adapt
  generated prose to project style.
  - https://lore.kernel.org/r/20260609110957.GB1509396@coredump.intra.peff.net
  - https://lore.kernel.org/r/aika_Q0rWhcI6eXR@pks.im
  - https://lore.kernel.org/r/xmqqpl1zsv8s.fsf@gitster.g
- Raw hyperfine output is acceptable when its distribution or CPU split is
  relevant. The governing rule is to remove data that does not help the reader
  assess the claim.
  - https://lore.kernel.org/r/20260611063711.GA2191159@coredump.intra.peff.net
  - https://lore.kernel.org/r/20260611064117.GB2191159@coredump.intra.peff.net
- Git's AI policy rejects bloated or superficial submissions the contributor
  cannot explain. Project-defined trailers matter; `Assisted-by` is not a
  documented Git trailer, and naming an LLM does not provide useful provenance.
  - https://lore.kernel.org/r/8f3bab63-3b37-4492-a39e-95e610a15a07@app.fastmail.com
  - https://lore.kernel.org/r/e42fac49-5037-4eac-b4c8-58bc62857ee2@app.fastmail.com

## Explain the mechanism and the policy

- Name the actual expensive event and when it happens. For the prefix-scoped
  iterator regression, the important fact was that cache priming occurs during
  iterator construction, before a later seek can narrow the loose-ref scan.
  - https://lore.kernel.org/r/CAOLa=ZRHKNNymXGk31YgECjUmF9nZ8GsPUdQb7aKBH5DKMz7=w@mail.gmail.com
- Do not merely document a heuristic cutoff. Explain the policy behind it and
  benchmark a plausible counterexample. Reviewers challenged a one-pathspec
  threshold as arbitrary and also considered unconditional prefiltering because
  the demonstrated regression was synthetic.
  - https://lore.kernel.org/r/20260609104119.GA1509396@coredump.intra.peff.net
  - https://lore.kernel.org/r/20260611084132.GK2191159@coredump.intra.peff.net
  - https://lore.kernel.org/r/xmqqfr2tnfk0.fsf@gitster.g
- Algorithm choices require their limiting conditions. Memoized depth-first
  contains walks can regress branch queries without generation numbers, while
  generation numbers permit early cutoff. Preserve the existing tag behavior
  without generations and explain why.
  - https://lore.kernel.org/r/20260608223430.GA340696@coredump.intra.peff.net
  - https://lore.kernel.org/r/CAOLa=ZSezQOj56-TezVaAcisUyczxhJmu4VghyFBHcBB_mKJ2A@mail.gmail.com

## Prefer the simpler existing path

- Preserve the existing iterator flow when changing its construction prefix is
  enough. Introducing another public helper path made the regression fix harder
  to understand without adding capability.
  - https://lore.kernel.org/r/CAOLa=ZRHKNNymXGk31YgECjUmF9nZ8GsPUdQb7aKBH5DKMz7=w@mail.gmail.com
- Avoid overengineering malformed-state handling. A replacement-ref cycle
  violates the commit-graph invariant; a fatal error consistent with existing
  replacement and parse behavior may be clearer than clearing caches and
  falling back to a second traversal.
  - https://lore.kernel.org/r/CAL71e4PRqN9iPCzvgwC1Vtj-kzn4Udv+v1LTFSUXtGnC5KGrpA@mail.gmail.com
- Use local variables when they remove repeated long expressions and awkward
  wrapping. This is readability, not abstraction.
  - https://lore.kernel.org/r/xmqqpl20vhni.fsf@gitster.g

## Split independent changes

- Cycle correctness and selecting a faster traversal are separate changes.
  Make the existing user of an algorithm safe before expanding its use.
  - https://lore.kernel.org/r/CAOLa=ZS_U+u43SV9ELSEU6AT7rzEQ44BuHPAi1BAHEGQAnPoPw@mail.gmail.com
  - https://lore.kernel.org/r/20260608223430.GA340696@coredump.intra.peff.net
- Error handling for a non-memoized traversal is an independent bug fix. Do not
  hide it in a performance patch, and use the project's error convention.
  - https://lore.kernel.org/r/20260611072942.GG2191159@coredump.intra.peff.net
  - https://lore.kernel.org/r/20260611082244.GH2191159@coredump.intra.peff.net
- Do not introduce a dormant empty-input behavior change without a trigger and
  rationale. If it matters, give it its own patch.
  - https://lore.kernel.org/r/20260611082244.GH2191159@coredump.intra.peff.net

## Tests and perf tests

- Keep setup, correctness, and timing distinct. Assertions buried in a perf
  script are hard to understand and rarely run; normal tests should establish
  correctness, while `test_perf` measures.
  - https://lore.kernel.org/r/CAOLa=ZS_U+u43SV9ELSEU6AT7rzEQ44BuHPAi1BAHEGQAnPoPw@mail.gmail.com
  - https://lore.kernel.org/r/20260611082244.GH2191159@coredump.intra.peff.net
- Perf coverage should exercise all affected frontends, not only the command
  that first exposed the issue. Prefer real input repositories when useful,
  while retaining focused synthetic cases that demonstrate shared-history or
  scaling behavior.
  - https://lore.kernel.org/r/20260611082244.GH2191159@coredump.intra.peff.net
- A prerequisite must reflect a real semantic requirement. Generic ref
  iteration improvements should run for both files and reftable backends even
  if loose files made the original symptom dramatic.
  - https://lore.kernel.org/r/aiZoYE8koq1UKlWq@pks.im
  - https://lore.kernel.org/r/xmqqecihyzse.fsf@gitster.g
  - https://lore.kernel.org/r/aivx-7VOKE_TC50R@pks.im
- Synthetic data should resemble real repositories. Many refs are commonly
  packed; use `pack-refs` when that better represents the claim. Use modern
  helpers such as `test_seq -f` and batched `update-ref --stdin`.
  - https://lore.kernel.org/r/20260609110957.GB1509396@coredump.intra.peff.net
- Cleanup commands inside `test_when_finished` should be `&&`-chained so
  failures are visible.
  - https://lore.kernel.org/r/20260611072942.GG2191159@coredump.intra.peff.net
- Object hashes from another generated repository prove nothing to reviewers.
  Verify semantic output or counts derived from the local fixture.
  - https://lore.kernel.org/r/20260611082244.GH2191159@coredump.intra.peff.net

## Performance counterexamples

- An early pathspec match can avoid expensive `lstat()` calls, but an
  all-matching pathspec duplicates matching work and a large pathspec list can
  turn the prefilter into the dominant cost. Measure both before choosing the
  policy.
  - https://lore.kernel.org/r/xmqqa4t5yyee.fsf@gitster.g
  - https://lore.kernel.org/r/20260608230315.GC340696@coredump.intra.peff.net
  - https://lore.kernel.org/r/20260608232516.GA357822@coredump.intra.peff.net
- Check behavior beyond performance. An early pathspec filter may change
  recursive-submodule traversal, so trace command semantics before assuming
  that skipped work is invisible.
  - https://lore.kernel.org/r/xmqqa4t5yyee.fsf@gitster.g
- A depth-first contains walk needs generation numbers to avoid walking to the
  root for nearby negative cases. Benchmark the likely regression shape, not
  only the shared-history win.
  - https://lore.kernel.org/r/20260608223430.GA340696@coredump.intra.peff.net

## Historical citations and trailers

- Permanent history must explain relevant prior discussion rather than depend
  on it. Unexplained `Link:` trailers to review messages look random. Introduce
  the discussion in prose and use a numbered reference when it materially
  supports the decision.
  - https://lore.kernel.org/r/aivx-7VOKE_TC50R@pks.im
- Use `Reported-by`, `Suggested-by`, `Helped-by`, and other trailers according
  to what the person actually contributed. Do not use a trailer as a substitute
  for explaining why their discussion matters.

## Revision threading and cadence

- Send each revision as a reply to the preceding revision. A changelog link is
  not a substitute because maintainers and tools recover and range-diff series
  through thread ancestry.
  - https://lore.kernel.org/r/xmqqv7bstmw8.fsf@gitster.g
  - https://lore.kernel.org/r/xmqqecigtm5z.fsf@gitster.g
- Aim for no more than one revision per day. Batch minor feedback, wait longer
  for large series, and reroll sooner when substantial rework would otherwise
  waste reviewers' time.
  - https://lore.kernel.org/r/aietF4BX1Ewt3cpG@pks.im

## Source thread roots

Fetch these roots to reconstruct the complete discussions. v3 messages that
were sent as replies to v2 appear under the v2 roots.

- Prefix-scoped ref iteration:
  - `20260605-fix-git-branch-regression-v1-1-02f40ad40929@gmail.com`
  - `20260608-fix-git-branch-regression-v2-1-fd82075a8520@gmail.com`
- `ls-files` pathspec prefilter:
  - `20260607-ls-files-pathspec-lstat-v1-1-8cf40b730146@gmail.com`
  - `20260608-ls-files-pathspec-lstat-v2-1-fb734b28422e@gmail.com`
- Memoized contains traversal:
  - `20260607-ref-filter-memoized-contains-v1-1-a1972dde9c76@gmail.com`
  - `20260608-ref-filter-memoized-contains-v2-0-e72720344a7c@gmail.com`
- `describe` tag ref scope:
  - `20260607-describe-tag-ref-scope-v1-1-653d232b86b5@gmail.com`
  - `20260608-describe-tag-ref-scope-v2-1-256fd36dca32@gmail.com`
