---
name: slack-reviewer-outreach
description: Identify the strongest practical reviewer for a pull request and contact them on Slack with a concise, evidence-backed rationale. Use when choosing reviewers, requesting owner approval, nudging a stalled review, or following up on a review blocker.
---

# Slack Reviewer Outreach

Apply `$audience-aware-writing` and `$slack`. Reuse the affected-path and
review-history evidence from `$maintainer-review` when it is already available.

## Choose the reviewer

1. Read the actual diff and identify the judgment needed: behavior, design,
   generated output, deployment ownership, or a required owner approval.
2. Build a practical candidate pool from eligible owners, recent authors of the
   exact behavior, and people who left substantive reviews on related changes.
   Automated assignments and nominal ownership are discovery inputs only.
3. Prefer, in order:
   - substantive review of the same behavior or interface;
   - recent authorship of the changed behavior;
   - repeated hands-on work in the owning subsystem;
   - prior approval of closely related changes.
4. Apply current availability only after establishing technical fit. Exclude
   people who declined, asked not to receive bot messages, are out of office, or
   cannot satisfy the required approval gate. Avoid repeatedly routing unrelated
   work to the same responsive person.
5. Inspect detailed status and DM history only for the shortlist. If no
   candidate is clearly qualified, show the user a short ranked list and the
   uncertainty instead of guessing.

Do not infer expertise or management load from title alone. Prefer direct
repository and review evidence.

## Contact them

Apply `$slack-outgoing-message` and honor the user's send-versus-draft intent.
Resolve the selected person's Slack identity before messaging. Use one short
paragraph:

- say what changed and what judgment is needed;
- connect the candidate's relevant experience to that judgment;
- include the pull request link;
- mention readiness only when it helps, such as relevant CI being green.

Do not cite automated assignment as the reason for outreach. Do not broadcast
review requests or connector-post agent-authored outreach to
`#codex-eng-chatter` or `#codex-pr-review`; return a manual-post draft if the
user wants to communicate there.

Before outreach about live breakage, search recent Slack and GitHub activity for
an active owner or fix. Report existing ownership instead of creating competing
work. After sending, monitor without repeated nudges and stop contacting anyone
who declines.
