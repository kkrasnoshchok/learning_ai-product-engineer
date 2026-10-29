---
description: Complete the open lesson (usage: /close-lesson <program-id>)
argument-hint: <program-id>
---

Close the lesson for `$ARGUMENTS`.

Follow `engine/protocol/08-lesson-lifecycle.md` (Pause, finish, abandon). Make sure every independently scored item is logged with
`los.py log`, then run `python3 scripts/los.py lesson complete <program-id> --file -` with `summary`, `handoff`, `next_action`
(and `next_focus` / `outcome: partial` if apt). Report the result in plain language, including whether the lesson was independently
assessed: completing a lesson is not mastery. Then tell the learner to start the next lesson in a new session.

Abandoning instead requires the learner's explicit yes: `lesson abandon <program-id> --reason "<their words>" --confirm`.
Programs without lifecycle sessions can use the manual path in `engine/protocol/04-session-close.md`.
