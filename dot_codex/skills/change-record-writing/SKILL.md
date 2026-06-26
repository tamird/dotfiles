---
name: change-record-writing
description: Write or revise commit messages, pull request titles and descriptions, and precursor tracking comments as durable change records. Use when preparing a commit or pull request, rewriting a PR body that will become a squash-commit message, or explaining an extracted precursor.
---

# Change Record Writing

Apply `$audience-aware-writing`. Assume repository fluency, but not private
implementation history, future branches, or unstated rationale.

Before drafting, inspect recent relevant history for the affected paths. Follow
the repository's subject prefixes, capitalization, terminology, and body style.
Use the defaults below only where local history does not establish a convention.

## Describe the change

- Treat a pull request title as the eventual commit subject and its description
  as the commit body.
- Explain the delta from the merge base, why it is needed, the important
  invariant it establishes, and non-obvious caveats.
- Name concrete files, data, and behavior. Remove baseline truths, progress
  notes, implementation trivia, and private or future context that does not help
  a reviewer understand the change.
- Do not add a test plan unless explicitly requested. Do not narrate validation
  already covered by normal CI.

## Format the record

- Separate subject from body with a blank line.
- Limit the subject to 50 characters.
- Use imperative mood and no terminal period.
- Capitalize the subject unless the repository uses a subject-area prefix or
  another local convention.
- Wrap body text at 72 characters.
- Use the body for what and why, not a step-by-step account of how.
- Do not use Markdown headings in pull request descriptions.

## Handle references and precursors

- Prefer durable commit links over pull request references in permanent prose.
- For a precursor extracted from another pull request, make the first top-level
  tracking comment begin `Extracted from #<parent PR number>.` Then state the
  concrete problem in the parent that required the extraction.
- Explain the same causal relationship in the precursor description so the
  change remains justified after the tracking context is gone. The tracking
  comment is the exception to avoiding pull request references.
