---
description: Review what you are about to forget (usage: /review [program-id])
argument-hint: [program-id]
---

Run a spaced-repetition review session for program `$ARGUMENTS` (if empty, run `python3 scripts/los.py programs` and ask which one).

This must be a **fresh session** and is NOT a lesson: do not start or plan one.

1. Read `AGENTS.md` and `engine/protocol/09-assessment-and-review.md`.
2. `python3 scripts/los.py review due <program-id>`. If nothing is due, say so and offer `/progress` or `/lesson`; stop.
3. `python3 scripts/los.py review start <program-id> --provider claude`, then `review brief <program-id>` is your only briefing.
4. For each item: ask the `examiner` subagent for ONE task with a private rubric, `assess create`, show only `assess show`, let the learner answer
   without help, then `assess submit`, `assess brief` (give it to the examiner), `assess grade`, `assess commit`. Ambiguous grading needs human review.
5. `review complete <program-id>`; give the learner the concise summary and end the session. The learner never types ids.
