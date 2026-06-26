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
- Combine related predicates into one traversal. Do not launch concurrent or
  repeated whole-repository scans for related questions.
- Do not start a duplicate search, build, or generator because an existing
  command is slow. Let it finish or inspect that process before doing more work.
- Remove duplicate or subsumed predicates and scopes before traversal.
- Push known paths, revisions, fields, and record constraints into the producer
  instead of scanning broadly and filtering afterward.
- Verify that a piped consumer actually reads standard input. Push the filter
  into the producer or use a stream matcher when it does not.

## Choose efficient operations

- Prefer set-oriented and batched commands over shell loops that start one
  process per input. Use native multi-pattern, all-match, batch-input, or
  file-list modes.
- Use the least expressive matcher that preserves the semantics. Prefer exact
  or fixed-string matching when a regular expression adds no value.
- Keep independent literal alternatives as separate fixed-string patterns when
  the tool can prefilter them.
- For large Git regex searches, prefer `git grep -P` over `git grep -E` when
  the PCRE and ERE expressions are equivalent.
- Feed multiple object IDs to one `git cat-file --batch-check` or
  `git cat-file --batch` process.

## Bound history and output

- Find likely current paths before using `git log -S` or `-G`, search relevant
  revisions first, and add `--all` only when cross-reference history matters.
- Pass limits such as `git log -n` to the producer. Use `--follow` only when
  rename or copy history is relevant.
- Request only what the next step needs. Prefer existence, count, name-only,
  selected-field, and bounded-output modes over full records.
