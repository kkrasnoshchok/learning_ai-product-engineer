---
description: Start a fresh lesson for a program (usage: /lesson <program-id>)
argument-hint: <program-id>
---

Start a lesson for program `$ARGUMENTS`.

1. Read `AGENTS.md` and `engine/protocol/01-session-start.md`.
2. Run `python3 scripts/los.py context $ARGUMENTS` and treat its output as your only briefing.
   If it fails validation, stop and tell the learner what to fix.
3. Follow `engine/protocol/02-lesson-flow.md` and `03-assessment.md`.
4. When the learner is done, follow `04-session-close.md`.

If this conversation already contains a different lesson, tell the learner to open a new session instead.
