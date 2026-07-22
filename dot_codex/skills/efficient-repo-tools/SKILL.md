---
name: efficient-repo-tools
description: Use efficient, bounded Git and repository traversal. Apply when searching large repositories, inspecting content history or many Git objects, comparing broad diffs, or designing commands whose repeated scans could waste CPU, I/O, or context.
---

# Efficient Repo Tools

Use indexed producers, narrow traversal scopes, and batched operations. Avoid
repeatedly walking the same repository to answer related questions.

## Search once

- Prefer Git's index-aware commands when they answer the question: use
  `git grep` instead of `ripgrep`, and `git ls-files` instead of `find`.
- Invoke `git` through the user's `PATH` rather than hard-coding a platform
  binary. Git exports its selected helper directory to hooks and subprocesses,
  so explicitly invoking Xcode Git also makes pre-push checks use Xcode Git
  instead of the user's configured wrapper and optimized installation.
- Create linked worktrees through the owning tool's documented lifecycle and
  directory layout. Ad hoc worktrees can escape cleanup and leave their own
  filesystem-monitor daemons running indefinitely.
- Combine related predicates into one traversal. Do not launch concurrent or
  repeated whole-repository scans for related questions.
- Do not start a duplicate search, build, or generator because an existing
  command is slow. Let it finish or inspect that process before doing more work.
- Do not put a short timeout around a cold whole-worktree `git status` and
  immediately retry it. A killed status cannot persist its refreshed index, so
  the retry repeats the same full-tree walk. Let one warmup finish, or cancel
  once and avoid reissuing the scan.
- Avoid `git status --untracked-files=all` unless every individual untracked
  path is required. `normal` can report an untracked directory without
  recursively enumerating its contents and is much cheaper in large trees.
- Remove duplicate or subsumed predicates and scopes before traversal.
- Push known paths, revisions, fields, and record constraints into the producer
  instead of scanning broadly and filtering afterward.
- For a language-specific symbol, restrict both the file extension and any
  known root. Git combines positive pathspecs as a union, not an intersection:
  `git grep -F symbol -- src ':*.py'` still searches every Python file in the
  repository. Use one combined pathspec, such as
  `git grep -F symbol -- ':(glob)src/**/*.py'`, or use `src` alone when the
  extension restriction is unnecessary.
- Prefer a literal directory pathspec over `directory/**` when searching its
  whole subtree. The wildcard adds per-path matching and can prevent Git from
  pruning unrelated tree entries.
- Verify that a piped consumer actually reads standard input. Push the filter
  into the producer or use a stream matcher when it does not.

## Choose efficient operations

- Prefer set-oriented and batched commands over shell loops that start one
  process per input. Use native multi-pattern, all-match, batch-input, or
  file-list modes.
- Use the least expressive matcher that preserves the semantics. Prefer exact
  or fixed-string matching when a regular expression adds no value.
- Keep independent literal alternatives as separate fixed-string patterns when
  the tool can prefilter them. For commit subjects/messages, use repeated
  `git log --grep=<literal>` with `--fixed-strings`, not one ERE alternation.
- For large Git regex searches, prefer `git grep -P` over `git grep -E` when
  the PCRE and ERE expressions are equivalent.
- Feed multiple object IDs to one `git cat-file --batch-check` or
  `git cat-file --batch` process.

## Bound history and output

- Find likely current paths before using `git log -S` or `-G`, search relevant
  revisions first, and add `--all` only when cross-reference history matters.
- Pass limits such as `git log -n` to the producer, but remember that a
  match-count limit does not bound traversal when fewer matches exist. Add a
  relevant revision range or `--since` window. Use `--follow` only when rename
  or copy history is relevant.
- Request only what the next step needs. Prefer existence, count, name-only,
  selected-field, and bounded-output modes over full records.
