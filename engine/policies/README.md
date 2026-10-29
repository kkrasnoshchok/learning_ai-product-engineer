# Policies

Shared, subject-agnostic educational policies. Every role reads the ones it needs; none names a topic.
Where a policy and `engine/protocol/` disagree, the protocol wins (it owns scoring and logging).

| Policy | Governs |
|---|---|
| [teaching.md](teaching.md) | Adaptive teaching, Socratic questioning, active recall, deliberate practice, progressive hints |
| [assessment.md](assessment.md) | Independent assessment, evidence-based mastery, misconception tracking, spaced repetition |
| [delegation.md](delegation.md) | Roles, minimal-context handoffs, single-writer rule, session context isolation |

Roles are specified in `engine/roles/`; the Codex and Claude agent files are thin wrappers around them.
