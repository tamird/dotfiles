---
name: reviewer-outreach
description: Identify qualified change owners and, only when explicitly authorized, request review through the actual public owning-team channel or another verified appropriate route.
---

# Reviewer Outreach

Use `$audience-aware-writing` and available `$maintainer-review` evidence.
Verify identity, communication preferences, destinations, and outreach
authority directly. Finding a reviewer or drafting a request never authorizes
sending it.

## Identify the right owner

Establish the current change, affected behavior, source ownership, reviewer
judgment, and real required approval. Inspect the repository's actual
ownership, recent substantive reviews, and available maintainers. Automated
assignment and team membership are discovery, not proof of expertise.

Verify that a selected reviewer belongs to the actual destination before
mentioning them. If ownership is genuinely unclear, present the user with a
brief evidence-backed shortlist. Never ask another reviewer to identify,
recruit, or chase the actual owner.

## Use the least surprising public route

Before sending, verify current user authorization, full head, existing owner
approval, existing requests, and the real per-change thread. If the review
has already been satisfied, stop.

For an authorized request, prefer:

1. The existing public owning-team thread for this exact change.
2. One new top-level request in the actual owning-team channel.
3. The real owning project channel, when its relevant owner is present.
4. A direct message only when privacy, user instruction, or lack of a public
   owner route genuinely requires it.

Keep unrelated changes in separate threads. Link directly to the user's
authorized change provider. State the reason for review, affected behavior,
qualified owner, and actual check status. Do not redirect people to an
unrequested product or leave an unlinked commit identifier in a message.

A duplicate native and message request is one request. Follow the existing
thread instead of creating another root. Where an authorized active source
fix needs prompt owner attention, state the verified failure and current CI
accurately; do not infer permission to merge or bypass approval.

Read back any authorized publication and follow genuine owner replies in the
same provider thread.
Do not manufacture an adoption decision, repeatedly nag, direct-message a
person to discover whether a fix exists, contact unrelated teams, or recruit
a replacement through another reviewer.
