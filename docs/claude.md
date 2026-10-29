# Using Learning OS with Claude Desktop (Code tab)

Auth: your Claude subscription sign-in in the desktop app. Nothing in this repo needs an API key.

## Setup (once)
1. Open Claude Desktop, go to the **Code** tab, and choose this folder (`learning-os/`) as the project.
2. Claude Code reads `CLAUDE.md`, which imports `AGENTS.md` (the shared contract). Slash commands in `.claude/commands/` appear automatically.
3. Edit `learner/preferences.yaml` to your taste.

## Create a program
1. **Onboarding** (new session): `/onboard my-program My Program Title`. Claude interviews you (goal, background, constraints), saves progress to `onboarding/my-program/state.yaml`, and creates the program only after you explicitly approve a summary. Interrupted? Open a new session and run `/onboard my-program` again; it resumes from the saved state.
2. **Curriculum** (another new session): `/new-program my-program` follows the authoring protocol and starts from `onboarding brief`, which refuses until you have approved.
No lesson is taught in either session.

## Every lesson
1. Open a **new session** on this folder (do not continue the previous lesson's session).
2. `/lesson my-program` (or "start a lesson on my-program"). Claude runs `los.py context` and proposes a focus.
3. Learn; Claude logs scored items with `los.py log`.
4. `/close-lesson my-program 3` (or "close the lesson"). Claude writes `lessons/003-*.md`, runs `los.py close`, and reports validation.
5. End the session.

## Lesson lifecycle (Phase 5)
`/lesson [program-id]` resumes or plans a lesson (the tutor runs the commands; you never type ids), `/pause-lesson <id> [note]` pauses it, `/close-lesson <id>` completes it. Always start each in a **new session**. Details and limits: `docs/lessons.md`. The slash commands and live behavior were not exercised in Claude Desktop in this authoring session.

## Assessment, mastery and review (Phase 6)
- "Test my understanding of X" -> `/assess <id> X`; "What should I review today?" / "Start my review session" -> `/review <id>` (always a **new session**; it is not a lesson); "Show my learning progress" -> `/progress <id>`.
- Claude uses the `examiner` subagent for tasks and grading and persists everything with `los.py assess ...` / `review ...`. Details and limits: `docs/assessment.md`.
- Not exercised in Claude Desktop here: the commands and subagent hand-offs were only verified through the CLI and library tests.

## Tips
- Approve the `python3 scripts/los.py ...` commands (and writes under `programs/`) when prompted; you can allow-list `python3 scripts/los.py` in your permission settings.
- If a session accidentally covers two programs, close it and start fresh. The protocol forbids reading across programs.
- Run `make test` after changing anything in `engine/` or `scripts/`.

## Subagents
`.claude/agents/` defines `curriculum-designer`, `researcher`, `examiner` (YAML frontmatter: `name`, `description`, `tools`).
Claude delegates automatically from the descriptions, or ask: "have the examiner write a rubric-based item for <competency>".
Subagents are read-only; Claude (the Tutor) logs and writes. Check them with `/agents`. Verified: file syntax and tests;
live delegation in the desktop GUI was not exercised here.

## Research and curriculum (Phase 4)
After onboarding, use a **new conversation per stage** (protocol 07): research planning and review, source research, competency discovery, curriculum drafting and review, approval and activation. Begin each with `python3 scripts/los.py curriculum status <id>`. Web research only works if this app session actually has web tools; otherwise the Tutor records the limitation and tasks stay pending.
