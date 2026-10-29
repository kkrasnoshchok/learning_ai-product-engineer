# Using Learning OS with Claude Desktop (Code tab)

Auth: your Claude subscription sign-in in the desktop app. Nothing in this repo needs an API key.

## Setup (once)
1. Open Claude Desktop, go to the **Code** tab, and choose this folder (`learning-os/`) as the project.
2. Claude Code reads `CLAUDE.md`, which imports `AGENTS.md` (the shared contract). Slash commands in `.claude/commands/` appear automatically.
3. Edit `learner/preferences.yaml` to your taste.

## Create a program
New session, then `/new-program my-program My Program Title` (or ask in plain words). Claude scaffolds, interviews you, authors `program.yaml`, and runs `validate --strict`. No lesson is taught in that session.

## Every lesson
1. Open a **new session** on this folder (do not continue the previous lesson's session).
2. `/lesson my-program` (or "start a lesson on my-program"). Claude runs `los.py context` and proposes a focus.
3. Learn; Claude logs scored items with `los.py log`.
4. `/close-lesson my-program 3` (or "close the lesson"). Claude writes `lessons/003-*.md`, runs `los.py close`, and reports validation.
5. End the session.

## Tips
- Approve the `python3 scripts/los.py ...` commands (and writes under `programs/`) when prompted; you can allow-list `python3 scripts/los.py` in your permission settings.
- If a session accidentally covers two programs, close it and start fresh. The protocol forbids reading across programs.
- Run `make test` after changing anything in `engine/` or `scripts/`.
