---
name: distill-session-guidance
description: Review a completed work session and promote reusable lessons into durable Codex guidance without accumulating one-off policy. Use when the user explicitly asks to distill, capture, or incorporate session learnings into AGENTS.md, existing skills, a new skill, or project-local guidance, especially at the end of a session.
---

# Distill Session Guidance

Turn demonstrated lessons from the current session into concise guidance for
future work. Invocation authorizes direct edits to live guidance unless the
user asks for a proposal or review only.

## Gather evidence

1. Re-read the session, emphasizing explicit user corrections, repeated failure
   modes, successful working patterns, and decisions intended to outlive the
   current task.
2. Read `~/.codex/AGENTS.md`, the affected skills, and any more-specific
   repository guidance before proposing another rule.
3. Treat explicit corrections as stronger evidence than inferred preferences.
   Treat emotional emphasis as evidence of importance, not prose to preserve.
4. Consult current official or company guidance only when a candidate depends
   on platform behavior, policy, or a disputed best practice. Do not make broad
   research a ritual part of every run.

## Decide what is durable

Promote a lesson only when it is likely to recur, changes future behavior, and
can be stated more generally than the incident that exposed it. Strong
candidates include explicit general corrections, repeated problems across
tasks, and workflow improvements supported by concrete evidence.

Do not promote:

- branch names, current blockers, one-off commands, or incident chronology;
- facts likely to drift or technical details owned by project documentation;
- rules already implied clearly by existing guidance;
- temporary workarounds or speculative compatibility requirements;
- a preference inferred from one ambiguous interaction.

If the session contains no durable lesson, make no edits and say so.

## Choose the owner

- Put cross-domain, always-on behavior in `~/.codex/AGENTS.md`.
- Put a focused, reusable workflow in the existing skill that owns its trigger.
- Create a skill only for a distinct recurring job with a clear trigger and
  procedure. Apply `$skill-creator` before creating or substantially revising
  one.
- Put repository or subpath conventions in the corresponding local guidance.
- Put technical architecture, contracts, and current-state facts in project
  documentation close to the implementation.
- Update memory only when the user separately and explicitly requests it.

Prefer deleting, merging, or clarifying existing guidance before adding
another rule. Keep one source of truth and make specialized skills layer on
general ones without copying them.

## Make the update

1. Form a compact working ledger of each candidate lesson, its evidence,
   intended owner, and `promote`, `merge`, `reject`, or `defer` disposition.
   Do not create a durable ledger artifact unless it has an independent use.
2. Refresh every target file immediately before editing. Preserve user-owned
   policy unless the session supplied clear evidence that it should change.
3. Make the smallest coherent guidance change, not necessarily the fewest
   changed lines. Remove contradictions and stale duplication in the affected
   area.
4. Keep `AGENTS.md` concise. Move procedural detail into a skill, and keep
   detailed reference material out of `SKILL.md` unless it is required for the
   workflow.
5. Do not modify chezmoi or another synchronization source unless the user
   explicitly requests it. Do not recursively revise this skill unless the
   session exposed a problem in this workflow itself.

## Validate and report

- Re-read the cumulative guidance as a system, not just the edited lines.
- Check for contradictory defaults, duplicate ownership, bad cross-references,
  stale trigger descriptions, and inappropriate scope.
- Run the skill validator for every changed skill and verify its
  `agents/openai.yaml`, local resources, and skill references.
- Report the files changed, the durable lessons promoted, meaningful candidates
  rejected or routed elsewhere, and validation performed.
