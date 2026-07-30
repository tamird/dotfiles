---
name: review-intake
description: Classify, claim, perform, and publish explicitly requested human pull-request reviews, including personal assignments, author re-review requests, and direct user requests to post a review.
---

# Review Intake

Consume authenticated `review_request` events from `$notification-watcher`.
This skill owns human-request validation, exact-head review claims, review
decisions, publication, and verified receipts. It does not own notification
polling, provider cursors, Slack control tasks, implementation, reviewer
recruitment, or merging.

Read the private operator profile and source checklist only when identity,
repository-specific verdicts, source ownership, attribution, or publication
authority matters. Do not assume a user, account, channel, signature, bot, or
owner. If verification is unavailable, remain read-only.

## Verify an actual review request

Establish the first-party human actor, exact requested individual, repository,
full current head, immutable event, and actual event time. Accept only:

- A verified personal assignment or native individual review request.
- An author's explicit review or re-review request, including an actual
  statement that prior findings were addressed.
- An explicit human author request in a user-authorized review conversation
  or watched thread.
- A review the user explicitly asks to perform, publish, post, or submit.

Do not treat a team assignment, bot-originated request, announcement,
ordinary mention, pull-request link, reviewer-routing question, changed
head, failing check, self-request, or unrelated discussion as a review
request. First verify that an existing current-head review has not already
satisfied the actual request. Review a draft only when its author or the
user explicitly requests it.

An automated carrier can deliver an authentic human request. Verify the
original human actor, intended individual, event, and head instead of either
accepting the carrier's authority or discarding the human's message.

Independently reconcile open, personally requested changes across every
authorized repository against their authoritative per-change event history.
An organization filter, filtered timeline, incremental watermark, bot
assignment, earlier review, or changed head cannot establish whether a
genuine human request remains outstanding.

## Claim and review once

Use the canonical watcher's transactional claim for the actual repository,
complete head, logical request, and authenticated source. Deduplicate the
same request received through several providers without discarding genuine
receipts. A new human request starts a new cycle even on an unchanged head.

When a message duplicates an already received native request, keep one cycle.
If a reply is authorized and useful, acknowledge once in the original thread
that the native request was sufficient. Do not invent a trigger, request
another notification, redirect the requester, or send a standalone nudge.

If authenticated source evidence disproves a claim, have the sole source
owner supersede it with the exact head and reason; never fabricate a review.

Return the review to the verified original reviewer or appropriate domain
owner. Wake that same agent with `followup_task` and verify its response;
never mistake a queued message for completed work or invent an implementation
assignment. A review agent must not delegate a broader audit, modify a skill,
or treat inherited conversation history as a new task.

Apply `$maintainer-review` to the complete merge-base change, title, rendered
description, existing discussion, affected source, invariants, and current
validation. Apply `$packaging-review` only when the actual packaging domain
warrants it.

## Publish an authorized, verifiable verdict

Use `$maintainer-review` for findings, inline placement, change records,
CI, and the appropriate substantive verdict.

Request changes only when that review establishes a genuinely severe
blocking finding. Publish lesser findings as neutral comments instead.

Apply repository-specific verdict, signature, reviewer-gate, mirrored-change,
and reaction policy from the private operator profile. Do not imply that an
approval satisfies an outstanding owner gate. An explicit request to publish
a review authorizes that review, not unrelated code or provider mutations.

If evidenced objections remain, the operational tradeoff belongs to the
actual owner, and further discussion is visibly unproductive, the user may
explicitly direct an escape: dismiss only our own change-request review,
publish one concise, accurately signed neutral withdrawal retaining the
substantive rationale, and disengage. Do not approve, dismiss anyone else's
review, or conceal the findings. Resume only upon a later explicit individual
re-review request from the author or user.

Immediately before publication, reverify the actual head, request, ownership,
and existing terminal review. Publish any required replies before submitting
the final verdict: some providers implicitly create a neutral review when a
thread reply is posted, replacing the principal's latest approval. Submit one
final verdict for that exact cycle, verify the first-party latest review state
as well as the review and inline receipts, and resolve the watcher claim only
after the terminal publication receipt exists.
