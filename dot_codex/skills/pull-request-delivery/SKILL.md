---
name: pull-request-delivery
description: Prepare and advance an explicitly authorized pull request while checking ownership, contribution rules, exact-head validation, normal hooks, and review and merge boundaries.
---

# Pull Request Delivery

Use `$change-record-writing` for the change record and `$maintainer-review`
for the complete design. Verify repository-specific publication, attribution,
review, and draft policy directly. Missing authority is a blocker.

## Establish the actual authority

Verify the exact repository, checkout, branch, integration base, full remote
head, original implementing owner, current pull-request state, and user-
authorized action. Account access does not make another agent's change ours.
Do not modify someone else's branch, description, threads, or reviewers.

Use the unchanged normal Git identity, signing, hooks, and configuration.
Do not change Git or HTTP settings, bypass hooks, or impersonate a review
signature. Run environment-sensitive Git commands through normal project
activation, such as `mise x --`; diagnose missing activation before changing
`SSH_AUTH_SOCK`, signing identity, credentials, or hook settings. Use
exact-head `--force-with-lease` only when the user has authorized the intended
branch. Stop and report a genuine authorization,
credential, ownership, or hook blocker.

When the user explicitly authorizes Git-publication fallbacks, try normal
signing and SSH first. If signing actually fails and repository policy permits
an unsigned commit, retry only that intended commit with
`git -c commit.gpgsign=false commit ...`. If an SSH push actually fails because
SSH authentication or transport is unavailable, retry only that push against
the already verified HTTPS destination. Preserve the user's Git identity,
normal hooks, configured remotes, and branch protections. Never persistently
change Git or signing configuration, credentials, hooks, or remote URLs;
never use these fallbacks to bypass repository policy.

Within an already authorized internal-repository publication workstream,
a normal hook-preserving push of the verified user-owned intended branch is
standing-authorized; do not repeatedly request permission for that push.
Verify branch ownership, destination, and remote head first. This does not
authorize a public push, force-push, another owner branch, merge, policy
bypass, or any operation blocked by the actual platform.

Before pushing a branch rebased on a shared default branch, verify that the
intended authenticated remote's remote-tracking default branch matches the
actual remote head. Coordinate shared worktrees before safely fast-forwarding
that ref: fetching an object or using `--no-write-fetch-head` alone need not
update `origin/<default>`. Hooks comparing `<remote>/<default>..HEAD` must
see the real integration base. Fix a stale ref; never bypass a multi-author
hook, skip verification, or change Git configuration to hide the problem.

Respect the current repository instructions. Choose ready or draft status from
the actual authorized workflow; do not infer a draft default. Use an
independent base unless stacking is semantically necessary and authorized.

## Validate the complete change

Rebase only for a verified conflict, a necessary merged prerequisite, an
actual integration-branch failure, or a user request. Verify conflicts from
the provider's native current-head result, not a normalized Boolean or a
review-blocked state. Do not invalidate good CI through speculative rebases.

Change the authoritative source, use its canonical generator, and run the
smallest meaningful validation. For each exact head, distinguish verified
causal failure, integration-branch breakage, infrastructure incident,
quarantine, cancellation, pending work, and absent evidence. Never call an
unverified or unsuccessful check green.

Map required checked-in test policy and projected, generated, or
platform-specific CI paths to the exact change before publication. Run the
required user-visible integration path when local infrastructure permits; if a
pre-existing bootstrap failure prevents it, report that precise limitation and
verify the new head's corresponding CI result instead of claiming local parity.

For a genuinely shared required-check failure, verify and link the actual
source, failure, owner, and existing correction on each affected change.
Route implementation to the original owner. Refresh an existing evidence-
backed analysis when its head or material failure changes; do not turn
aggregate incident status into a substitute for the individual diagnosis.

Label a partial CI assessment preliminary. Identify its exact head, each
still-running material job, and the evidence for whether further failures
could change the diagnosis. Finalize only after the material checks settle or
verified evidence makes further failures reasonably unlikely. If a later
failure disproves the assessment, edit the original comment: retain the
original prediction, strike through obsolete claims, and append the updated
analysis and primary evidence. Use Markdown-linked citations in a GitHub
comment; plain-prose change-record restrictions do not apply. Verify the
rendered correction.

## Keep reviews and ownership current

Apply repository-specific automated review or fallback rules only when the
user authorizes them. Verify the provider's current availability, actual bot
identity, draft and frozen state, full head, prior review, and existing
requests. Never request a review for a draft or frozen change or treat an
automated finding as a human request.

When the user authorizes human solicitation, use `$reviewer-outreach`.
Re-request a human review only after that review's substantive findings have
actually been addressed. Follow genuine replies directly in their existing
provider threads without creating new work.

After addressing an actionable review thread, verify the fix on the published
exact head and reply in that same thread with the concrete change and relevant
validation. Stage replies to multiple threads and submit them together using
GitHub's review feature; do not post a separate review for each response.
After the review is published, resolve each fully addressed thread when the
user has authorized resolution. Verify that every reply and resolved state
persisted. Never silently resolve feedback, resolve a concern before it is
fixed, or close a partially addressed thread.

Explicitly acknowledge every substantive top-level human request after
verifying its disposition against the current head. When the provider cannot
thread a reply to the original comment or review, quote each reviewer and
the relevant request in one concise top-level reply; explain what changed,
cite the verified evidence, and identify which requests remain unresolved.
Do not duplicate an existing acknowledgment, misrepresent an older review
as current, self-resolve a human concern, or substitute a status update for
a substantive answer.

Monitor exact-head mergeability, required checks, owner review, comments,
and in-place merge-validation results within the existing workstream. Wake
the original implementation owner when a real action is required.

Preparing, validating, publishing, or obtaining approval never authorizes a
merge, auto-merge, merge command, review bypass, or check bypass. Each needs
explicit user authorization for the specific pull request and action.
