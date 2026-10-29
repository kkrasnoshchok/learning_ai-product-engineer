---
description: Close the current lesson (usage: /close-lesson <program-id> <lesson-number>)
argument-hint: <program-id> <lesson-number>
---

Close the lesson: `$ARGUMENTS`.

Follow `engine/protocol/04-session-close.md` exactly: write the lesson record from
`engine/templates/lesson-record.md`, make sure every assessed competency has been logged,
run `python3 scripts/los.py close <program-id> --lesson <n>`, and report the validation result.
Then tell the learner to start the next lesson in a new session.
