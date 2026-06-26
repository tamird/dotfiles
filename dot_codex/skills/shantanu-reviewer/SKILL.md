---
name: shantanu-reviewer
description: Adversarially review oaipkg, Python packaging, dependency-resolution, bootstrap, and related monorepo changes using standards derived from Shantanu Jain's actual review history. Use before requesting Shantanu's review, when assessing whether an oaipkg change adds repository-wide cost or complexity, or when the user asks for a Shantanu-style review.
---

# Shantanu Reviewer

Apply `$maintainer-review` as the base workflow. Review the change through
standards supported by Shantanu's real comments. Do not imitate his tone or
invent objections.

## Add Shantanu-specific evidence

1. Read [references/review-lenses.md](references/review-lenses.md).
2. Refresh recent relevant review history when the change is newer than the
   reference or materially different from its examples:

   ```bash
   gh search prs oaipkg \
     --repo openai/openai \
     --reviewed-by hauntsaninja \
     --limit 50 \
     --json number,title,url,updatedAt,state
   ```

   Read the actual review and inline comments on the most relevant results.
   Prefer reviews of the same subsystem and behavior over merely recent ones.

Add these domain-specific risks to the base review:

1. **Repository-wide tax**: mandatory CI, startup, import, project discovery,
   network, resolver, metadata parsing, filesystem, and generated-file costs.
2. **Semantic drift**: fail versus skip, dynamic dependencies, lock and
   constraint authority, fallback behavior, and unsupported cases presented as
   preserved behavior.
3. **Complexity**: speculative fallbacks, compatibility paths without proven
   users, special cases, duplicated policy, and unrelated churn.
4. **Performance evidence**: relevant end-to-end journeys, controlled before
   and after measurements, warm and cold distinctions, and cost decomposition.
5. **Tests**: whether failures identify the violated behavior, whether tests
   exercise the real contract, and whether a real-life reproduction is missing.
6. **Documentation**: lost rationale, vague claims, branch-internal history,
   and limitations documented away from the code that owns them.

Do not assume a large implementation reflects an inherently complex domain.
Zoom out when local fixes multiply concepts.
