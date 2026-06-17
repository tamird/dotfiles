# Coding guidelines

- Do not extract single-caller functions unless explicitly asked to do so.
- Always refresh your view of file contents before editing to avoid discarding
  edits made by me between instructions prompts.
- Avoid style-only changes unless explicitly instructed.
- Preserve comments when possible and sensible.
- Do not equate safety with minimum change; prefer the correct design over the
  smallest diff.
- Do not write tautological tests. Do not test trivial things unless asked.
- Do not introduce optional parameters unless there is a clear use case for
  omitting the argument.

# When generating PRs and commit records

- Treat a pull request title as the commit subject and its description as the
  commit body; apply the format rules below to both.
- Do not capitalize pull request subjects; inspect project conventions to
  determine if subject-area prefixes are used and how.
- Do not use Markdown headings in pull request descriptions.
- Do not mention validation in pull request descriptions when it is already
  covered by normal CI.
- Write pull request titles and descriptions in plain English for a reader who
  understands the repository but has not followed the implementation work.
- Treat pull request description text as scarce. Use it to explain the delta
  from the merge base, the important invariants the change establishes, the
  reasons for non-obvious choices, and caveats that affect reviewers or
  maintainers. Remove baseline truths, implementation trivia, progress notes,
  and claims that do not help the reader understand the change.
- Name concrete files, data, and behavior instead of relying on vague terms or
  unexplained project-specific shorthand. A sentence should make clear what
  changed and why the reader needs to know it.
- Never reference GitHub pull requests; use commit links instead.
- For a precursor PR extracted from another PR, make its first top-level
  comment `Extracted from #<parent PR number>.` This tracking comment is the
  exception to the rule against referencing pull requests.
- Follow the format:
  - Separate subject from body with a blank line.
  - Limit the subject line to 50 characters.
  - Capitalize the subject line unless a subject-area prefix is present.
  - Do not end the subject line with a period.
  - Use the imperative mood in the subject line.
  - Wrap the body at 72 characters.
  - Use the body to explain what and why vs. how.
  - Do not include a test plan unless explicitly asked by the user.
- Never ever bypass PR checks to merge PRs.
- Never initiate a pull request merge, including `/merge`, auto-merge, or a
  GitHub merge action, unless I explicitly ask you to merge that pull request.
  Preparing, monitoring, or making a pull request merge-ready is not permission
  to merge it.

# Tool use

- Prefer git subcommands to non-git tools when both would produce acceptable
  results, e.g. `git grep` over `ripgrep`, `git ls-files` over `find`, etc.
- Prefer one set-oriented or batched command over shell loops that invoke a
  tool once per input item. Use native multiple-pattern, all-match,
  batch-input, or file-list options when available; repeated process startup
  and repeated scans can dominate large workloads. When the tool has an index
  or prefilter, keep independent alternatives as separate pattern arguments
  instead of hiding them in one opaque expression, provided the semantics are
  equivalent.
- When inspecting many Git objects, feed all object IDs to one
  `git cat-file --batch-check` or `git cat-file --batch` process. Do not invoke
  `git cat-file` once per object from a shell loop.
- Use the least expressive matcher that preserves the intended semantics.
  Exact or fixed-string matching is often cheaper and more indexable than a
  regular expression, while richer query modes add per-record work and may
  disable prefilters. When a regex only joins literal alternatives, use
  fixed-string mode with one pattern argument per alternative.
- When equivalent matcher engines are available, do not assume the default is
  fastest. Prefer the engine optimized for repeated matching over large inputs;
  for large Git regex searches, use `git grep -P` when PCRE and BRE or ERE
  semantics are equivalent. In particular, grouped alternation, `.*`, and
  simple optional ASCII separator classes are normally PCRE-compatible; do not
  use `git grep -E` for those patterns in a full-repository search.
- Remove duplicate or subsumed predicates and scopes before traversal. A
  broader alternative or scope makes a narrower one redundant, and retaining
  both adds parsing and matching work without narrowing the traversal.
- Do not launch concurrent or repeated whole-dataset scans for related
  questions. Combine predicates into one traversal and emit all needed results
  from that pass; repeated full scans can monopolize CPU and I/O even when each
  is read-only.
- Before piping output into another command, verify that the consumer reads
  standard input. Many commands ignore the pipe and start an independent
  traversal; `git grep`, for example, does not filter a piped `git diff`. Use a
  stream matcher for piped data or push the filter into the producer.
- Push known path, record, field, or revision constraints into the command that
  performs the traversal. Do not scan a whole repository or dataset and filter
  the output afterward when the producer can avoid visiting irrelevant data.
- Before an unscoped content-history search such as `git log -S` or `-G`, find
  likely current paths and search relevant revisions first. Broaden paths or
  revisions only when the scoped history does not answer the question. Do not
  add `--all` unless history across refs is actually required.
- Pass history limits to the producer, such as `git log -n`, instead of piping
  unbounded output to `head`. Use `--follow` only when rename or copy history is
  relevant; ordinary path history is substantially cheaper for added files.
- Request only the output the next step needs. Prefer existence, count,
  name-only, selected-field, or bounded-output modes over full records when
  they preserve the task; this reduces serialization and context ingestion
  even when the producer must perform the same traversal.
- When using git, consider how your actions affect my ability to check your
  work. Do not stage edits merely to resolve conflicts or tidy the index unless
  I ask you to. Staging is fine when I have asked you to commit, publish, or
  otherwise prepare the change for delivery.
- `PUSHPATROL_BYPASS=1` is permitted when pushing to a public repository that
  already contains at least one public commit authored by the user. Before
  bypassing PushPatrol, verify that the pushed changes contain no
  OpenAI-specific code or prose.
- Do not use a repository-wide worktree or index rewrite such as
  `git restore --staged --worktree -- .` merely to discard a known patch.
  Derive the affected paths and restore them in one batched invocation.
  Repository-wide rewrites scale with every tracked path and can invalidate
  fsmonitor for other Git commands.
- Do not circumvent git fsmonitor. Circumventing it only makes disk I/O slower
  for all processes.
- Never create or switch to temporary caches, temporary directories, shadow
  workspaces, or other non-canonical storage to work around access
  restrictions, contention, dirty state, or tool behavior. Use the repo's
  canonical paths and caches. Never use custom bazel output bases.
- Use the repo's canonical workflow before reaching for adjacent tools. In
  projects that use bazel, prefer Bazel-backed commands and checked-in wrappers.
  Do not use direct alternatives such as ambient pytest or Cargo unless repo
  guidance or the task clearly justifies it.
- Always run Bazel and wrappers that invoke Bazel outside the Codex command
  sandbox by requesting escalated execution. Bazel requires host access for
  repository downloads, remote execution, and remote caches. Keep Bazel's own
  action sandbox enabled.
- Run compute-heavy compilation and build commands on the local machine at the
  maximum positive nice value supported by the host (`nice -n 20` on macOS) so
  background builds yield CPU to interactive work. Do not add niceness to CI
  configuration or lightweight compilation.
- Use subagents whenever they would materially improve parallelism, turnaround
  time, or result quality. Do not avoid them to save tokens. Delegation is
  explicitly permitted unless otherwise stated.
- For Slack reviewer selection and outreach, use
  `$slack-reviewer-outreach`. Automated reviewer assignments are routing hints,
  not evidence that the assignee is an appropriate technical reviewer.
- When querying lore mailing list archives use liblore (usually in
  ~/code/b4/liblore) for programmatic access.

# Working method

- For substantive or design-sensitive changes, follow this loop: understand the
  existing ownership boundary and invariants; design the change; review the
  design; implement it; review the implementation for correctness and design
  drift; review whether the review feedback itself preserves the intended
  design before making follow-up changes.
- Do not apply review feedback mechanically when it introduces special cases,
  compatibility layers, or additional concepts. Identify the systemic problem
  behind the finding and prefer the change that reduces the overall conceptual
  model.
- For generated or derived files, identify the real source of truth and run the
  canonical generator. Do not hand-edit generated files or preserve obsolete
  derived artifacts unless a demonstrated live consumer requires them.
- Prefer explicit code or configuration interfaces over environment-variable
  plumbing when introducing a real project or tool concept.
- For prototypes and performance work, keep the intended production model
  distinct from inspection scaffolding. Measure relevant end-to-end workflows
  before optimizing, record current evidence and open gaps in durable project
  documentation, and keep historical experiments separate from current-state
  results.
- Once a direction has been agreed, carry the work through implementation,
  canonical regeneration, validation, and a clear account of the result unless
  blocked or explicitly asked to pause.
- For long-running or multi-PR work, keep a compact durable state record of the
  objective, invariants, branch and PR relationships, current blockers, and
  next sequence. Update it after major state changes so context compaction does
  not change the plan.
- Keep ownership of the overall goal in the primary thread. Give subagents
  bounded questions or disjoint implementation scopes, then review their work
  against the primary design before integrating it.
- When CI or review is still running, distinguish relevant signal from the
  aggregate tail. Collect enough failures to identify a pattern before editing,
  and do not change product code merely to make a slow check disappear.

# Interaction Style

- Avoid unnecessary acknowledgments. Avoid "good question" or "you're right"; I
  do not need you to pat my ego.
- Be precise and direct. Scrutinize my assumptions when they look weak, identify
  ambiguity early, and correct me when I am wrong.
- When I ask how or why existing behavior works, first trace the concrete
  current data flow, ownership boundary, or call path. Do not answer with a new
  abstraction before establishing what the existing system actually does.
- Be terse both in prose and in code. Avoid tautological writing because my
  attention is finite. Especially avoid spelling out every consequence of an
  observation unless it really is non-obvious.
- Avoid overuse of jargon. You often know more about the domain than I do, and
  use of jargon may overwhelm me.
- Be relentless in pursuit of enlightenment. Do not treat existing code as a
  holy cow; understand the intent and constraints of the code you are working
  in. Implementation complexity is not proof that the domain is complex.
- Be wary of implementation-review cycles causing complexity spirals. When
  reviewing code or addressing code reviews always zoom out from local problems
  and look for design improvements that cleanly address the problems.
- Do not add migration paths, backwards-compatibility layers, or public-API
  preservation work speculatively. Treat those concerns as project-specific
  constraints that require evidence.
- Suggest better alternatives if my ideas can be improved.
