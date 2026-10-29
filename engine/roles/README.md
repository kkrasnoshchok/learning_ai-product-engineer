# Roles

| File | Role |
|---|---|
| [tutor.md](tutor.md) | Primary agent: the main conversation (no separate agent file) |
| [curriculum-designer.md](curriculum-designer.md) | Subagent |
| [researcher.md](researcher.md) | Subagent |
| [examiner.md](examiner.md) | Subagent |

Agent wrappers: `.claude/agents/*.md` (Claude, hyphenated names) and `.codex/agents/*.toml` (Codex, underscored names).
Wrappers only carry a description and a pointer to the role file, so behaviour is defined once.
