---
name: audience-aware-writing
description: Draft or revise prose around the reader's actual context, knowledge, and next decision. Use for explanations, email, Slack, review replies, documentation, proposals, status updates, and handoffs where missing context, tone, attribution, or an unclear ask could cause misunderstanding. Specialized writing workflows use this as their base.
---

# Audience-Aware Writing

Write from the reader's context, not the author's accumulated context.

## Establish shared context

- Identify the reader, what they have actually seen, what domain knowledge is
  reasonable to assume, and what judgment or action the text should produce.
- Treat domain expertise and task context separately. A maintainer may know the
  subsystem while knowing nothing about an unposted branch or private decision.
- Name the concrete artifact, behavior, or problem at first mention. Give
  pronouns and labels such as `this`, `earlier`, and `the new API` explicit
  antecedents when ambiguity is possible.
- Introduce future, adjacent, or private work before relying on it. Explain only
  the part that affects the reader's decision.
- Use links as evidence or navigation, not as a substitute for explanation.

## Answer the reader's need

- State what changed, why it matters, and the judgment or action needed.
- Treat quoted context as part of the reply. Do not restate it merely to prove
  understanding. A quoted request can often be answered with `Done.`,
  `Will do.`, or a direct explanation of why not.
- Match the reader's demonstrated understanding. Add the new conclusion,
  decision, or scope boundary instead of explaining known facts back to them.
- When adopting only part of feedback, separate the accepted concern from the
  mechanism declined. Make causal relationships explicit.
- Preserve uncertainty when evidence is incomplete. Do not imply shared
  agreement or knowledge that has not been established.

## Write plainly

- Prefer concrete nouns and plain verbs. Preserve agency when the actor matters.
- Keep the rationale specific to the artifact and reader. Avoid canned praise,
  generic approval requests, abstract process language, and internal agent
  narration.
- Preserve authorship when writing in another person's voice. Do not turn the
  assistant's research or implementation into the author's first-person claim.
- Be concise after the context and requested judgment are clear. Remove
  chronology, implementation trivia, repetition, and consequences that are
  already obvious.

## Review the draft

Check that:

1. Every artifact, person, API, and prior event is identifiable.
2. Unseen or future context is introduced before it becomes a premise.
3. The requested judgment or action is explicit.
4. Links resolve and support rather than replace the explanation.
5. First-person claims belong to the stated author.
6. The text does not repeat what the reader already understands.
7. Uncertainty, disagreement, and partial feedback are represented accurately.
