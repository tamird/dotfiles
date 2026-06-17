---
name: slack-reviewer-outreach
description: Identify an appropriate pull request reviewer and contact them on Slack with a concise, personalized rationale. Use when Codex needs to choose reviewers, request an owner approval, nudge a stalled review, or follow up on a review blocker through Slack.
---

# Slack Reviewer Outreach

Find the strongest available reviewer rather than the first plausible one, then
make the outreach feel like a message from a colleague rather than an
approval-routing bot.

## Build The Candidate Pool

1. Read the actual diff and identify the judgment needed: behavior, design,
   generated output, deployment ownership, or a specific owner approval.
2. Build the practical candidate pool before choosing anyone. Include:
   - members of every owner set that can satisfy the affected gate;
   - recent authors of the exact files and the owning subsystem;
   - authors or reviewers of related interfaces and changes;
   - explicitly suggested or assigned reviewers.
3. Treat automated assignments, requested-reviewer lists, and nominal team
   membership as discovery inputs only. Never stop at the first plausible name.
4. For related pull requests, inspect review history as well as commit authors.
   Record whether each reviewer left substantive comments or only approved.
5. Use bounded, set-oriented history queries. Prefer exact changed-file history,
   then broaden once to the smallest relevant subsystem when exact history is
   sparse.

## Rank The Candidates

Compare the practical candidates. When the pool permits, examine at least the
top three before selecting one.

When an owner approval is required, first discard candidates who cannot satisfy
that gate. Gate eligibility is a requirement, not evidence of expertise.

Positive signals, strongest first:

- left substantive review comments on the same behavior, interface, or nearby
  change;
- recently authored the changed behavior or exact file directly;
- reviewed or approved the same area without leaving comments;
- repeatedly contributes to the owning subsystem;
- designed the affected interface or owns its behavior.

Use those signals to form a qualified shortlist. Availability and timezone are
then selection constraints within that shortlist, not low-value expertise
signals. Prefer a pretty-good qualified reviewer who is available in a
compatible timezone over the strongest theoretical expert who cannot respond.
Availability must not rescue a candidate with weak technical evidence.

Apply anti-signals explicitly:

- exclude anyone who asked not to receive bot messages, declined this request,
  or had a clearly negative prior Slack interaction about outreach;
- exclude the author when the ownership rule disallows author approval;
- exclude OOO or leave from current outreach, and deprioritize sustained away
  status or a prior unanswered request;
- when org data exposes it, deprioritize managers with a large reporting span or
  broad executives when a hands-on contributor can provide the same approval;
- deprioritize nominal owners with no relevant recent work, one-off old authors,
  and people whose nearby commits were mechanical or unrelated;
- avoid repeatedly routing unrelated reviews to the same responsive person.

Do not infer management load or expertise from a title alone. Use available org
and repository evidence, and state uncertainty when evidence is incomplete.

Check detailed Slack status and existing DM history only for the shortlist. This
both limits unnecessary personal-data inspection and catches previous declines
or negative interactions before sending.

Select the strongest currently reachable candidate who clears the technical
qualification threshold, not merely the person with the largest number of weak
signals. If no candidate clearly dominates, show the user a short ranked list
with the evidence and anti-signals before contacting anyone.

## Write The Message

Start with `Hey <name>,` or another natural greeting. In one short paragraph:

- explain why this person was chosen, using the concrete evidence above;
- state what changed and what judgment is needed;
- include the pull request link;
- mention readiness only when useful, such as relevant CI already being green.

Do not send generic approval requests, repeat an automated assignment as the
rationale, or imply that ownership alone makes someone the right technical
reviewer. Avoid templated blasts and broad mentions.

Example:

> Hey Alex, you recently changed the service's dependency-build path and are in
> its owner group. Could you review the small adaptation of that path in [PR
> link]? It switches the caller to the new lock API; the relevant CI is green.

## Send And Follow Up

Use the Slack outgoing-message workflow and return the message link. Do not send
unless the user has authorized reviewer outreach; when they asked to review the
draft first, create a draft instead.

After sending:

- monitor the pull request and the DM without repeated nudges;
- stop contacting anyone who declines or asks not to receive bot messages;
- do not reply to such a request through the bot unless the user explicitly asks;
- use a recommended replacement reviewer only after validating them through the
  same selection process.
