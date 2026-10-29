@AGENTS.md

## Claude-specific notes

- Slash commands live in `.claude/commands/`: `/lesson <id>`, `/close-lesson <id> <n>`, `/new-program <id> <title>`.
- Open a **new session** for every lesson (Claude Desktop, Code tab: new session on this folder).
  Do not resume or fork an earlier lesson session.
- Use the task list sparingly during lessons; the learner cares about the lesson, not tooling.
- Subagents live in `.claude/agents/` (`curriculum-designer`, `researcher`, `examiner`). They have no write tools;
  you, the Tutor, record everything. Delegate only when it helps the lesson.
