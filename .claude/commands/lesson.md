---
description: Start or resume a lesson (usage: /lesson [program-id])
argument-hint: [program-id]
---

Run a lesson for program `$ARGUMENTS` (if empty, run `python3 scripts/los.py programs` and ask the learner which one).

This must be a **fresh session**. If this conversation already holds a different lesson, tell the learner to open a new session.

1. Read `AGENTS.md`, `engine/protocol/08-lesson-lifecycle.md` (Entry) and `engine/protocol/02-lesson-flow.md`.
2. Run `python3 scripts/los.py lesson status <program-id>`. Resume, take over, or plan exactly as protocol 08 says.
   The learner never types commands or ids; you run them. Pass `--provider claude`.
3. `python3 scripts/los.py lesson brief <program-id>` is your only briefing. If any command fails validation, stop and show the errors.
4. Teach with the Study-Mode-style flow. Capture notes with `lesson note`; log independent items with `los.py log`.
5. End with `lesson pause`, `lesson await-assessment` or `lesson complete`, then tell the learner to start the next lesson in a new session.
