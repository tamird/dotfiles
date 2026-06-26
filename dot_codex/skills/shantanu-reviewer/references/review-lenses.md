# Review lenses from source comments

Use these as evidence of recurring standards, not as a fixed checklist. Refresh
GitHub history for the subsystem under review.

## Problem and scope

- Ask what exact problem the change solves and why existing oaipkg mechanisms
  are insufficient: [#850479](https://github.com/openai/openai/pull/850479),
  [#938666](https://github.com/openai/openai/pull/938666).
- Challenge whether the benefit justifies the workflow for affected users:
  [#920213](https://github.com/openai/openai/pull/920213).
- Remove unrelated churn because it conceals behavior and can introduce harmful
  changes: [#874720](https://github.com/openai/openai/pull/874720).

## Complexity and semantics

- Remove fallback paths without a concrete user; otherwise explain the precise
  failure and solve that problem directly:
  [#939405](https://github.com/openai/openai/pull/939405).
- Avoid adding bootstrap complexity without a strong reason and preserve simple
  controlled-input logic:
  [#1031639](https://github.com/openai/openai/pull/1031639),
  [#1037419](https://github.com/openai/openai/pull/1037419).
- Verify semantic equivalence, especially fail versus skip and dynamic
  dependency behavior:
  [#998769](https://github.com/openai/openai/pull/998769),
  [#1004450](https://github.com/openai/openai/pull/1004450).
- Treat global constraints, legacy support, and centralized exceptions as
  repository-wide policy costs:
  [#802086](https://github.com/openai/openai/pull/802086),
  [#1018587](https://github.com/openai/openai/pull/1018587).

## Performance and evidence

- Measure happy-path overhead before adding checks to installation or bootstrap
  paths: [#1001735](https://github.com/openai/openai/pull/1001735),
  [#985508](https://github.com/openai/openai/pull/985508).
- Rebase and rerun benchmarks when the baseline changed; distinguish code
  effects from filesystem-cache effects:
  [#924240](https://github.com/openai/openai/pull/924240).
- Inspect concurrency and parsing mechanics rather than accepting aggregate
  timing claims:
  [#918538](https://github.com/openai/openai/pull/918538),
  [#921496](https://github.com/openai/openai/pull/921496).
- Do not pay a hot-path cost for guarantees the underlying packaging model
  cannot provide:
  [#860579](https://github.com/openai/openai/pull/860579).

## Tests and rationale

- Tests must catch the real breakage; replacing simple behavior with weaker
  tests is itself a regression:
  [#1037419](https://github.com/openai/openai/pull/1037419).
- Ask for the real-life reproduction when the motivating failure is unclear:
  [#940812](https://github.com/openai/openai/pull/940812).
- Preserve comments that explain user workflows and document non-obvious
  limitations where the relevant behavior is assembled:
  [#1037419](https://github.com/openai/openai/pull/1037419),
  [#1004450](https://github.com/openai/openai/pull/1004450).
