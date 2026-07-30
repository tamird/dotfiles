---
name: efficient-repo-tools
description: Search and inspect repositories using bounded, indexed Git operations, precise pathspecs, native batching, and minimal process, filesystem, and output cost.
---

# Efficient Repo Tools

Use indexed producers, narrow scopes, and batched operations. Never repeat
an expensive traversal merely because the first operation is slow.

## Search the existing index

- Prefer `git grep` to `rg` or recursive text scanning and `git ls-files` to
  `find`. Use the actual checkout, not another agent's worktree.
- Invoke Git through the existing `PATH`. Preserve the selected wrapper,
  `GIT_EXEC_PATH`, hooks, and inherited environment; prepend a required
  virtual environment instead of replacing the path or forcing other tools.
- Create or remove worktrees only through their documented owner and only
  when authorized. Do not interrupt an active filesystem monitor.
- Combine related predicates into one bounded traversal. Push known roots,
  paths, object identifiers, revisions, and selected fields into the producer.
- Keep a root and extension in one pathspec: positive pathspecs are a union,
  so `git grep -F name -- src ':*.py'` is not confined to `src`. Use
  `git grep -F name -- ':(glob)src/**/*.py'` when both are necessary.
- Use a literal directory instead of a recursive wildcard when the whole
  subtree is required. Verify that a piped consumer actually reads its input.
- Prefer fixed strings, native multi-pattern search, and set-oriented commands
  to regular expressions, shell loops, and one process per object. Batch
  object queries with `git cat-file --batch` or `--batch-check`.

## Avoid full worktree walks

- Never repeatedly time out and restart a cold `git status`: an interrupted
  index warmup repeats the same full scan. Let one operation complete or stop
  without starting another.
- Avoid `git status --untracked-files=all` unless every path is required.
  Prefer normal untracked-directory reporting or
  `git ls-files --others --exclude-standard --directory --no-empty-directory`.
- For tracked-change existence, use
  `git diff --no-ext-diff --quiet -- <known-paths>`; use `--cached` for the
  index. Do not invoke external diff drivers when only existence matters.
- Inspect an existing search, build, or generator before launching another.

## Bound history and output

- Put revisions, pickaxe flags, and limits before `--`; later arguments are
  pathspecs. Use `git log --max-count=5 -Ssymbol -- path`.
- Search relevant paths and revisions first. Use `--all`, `--follow`, or
  expensive history only when cross-branch or rename evidence is required.
- Combine output limits with a relevant revision or time range: a match-count
  limit alone cannot bound an unsuccessful history walk.
- Request only the required existence, count, field, path, or bounded record.
  Deduplicate overlapping search predicates before running the command.
