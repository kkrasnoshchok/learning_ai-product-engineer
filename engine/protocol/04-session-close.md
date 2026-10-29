# 4. Session close

Perform these steps in order, even for a short or abandoned lesson.

1. **Confirm assessments are logged** for everything scored this lesson.
2. **Write the lesson record** `programs/<id>/lessons/NNN-slug.md` (NNN = zero-padded lesson number, next in sequence)
   from `engine/templates/lesson-record.md`.
   - `outcome`: `completed`, `partial`, or `abandoned`.
   - `competencies_covered`: what was actually taught.
   - `next_focus`: ids the next lesson should start with (may be empty).
   - `## Summary`: what happened. `## Handoff`: what a stranger needs to continue (misconceptions, open questions,
     where to resume). Keep it short: the next lesson sees only this, nothing else from today.
3. **Close**: `python3 scripts/los.py close <program-id> --lesson <n>`. It rebuilds `state/` and validates.
4. If validation fails, fix the lesson record (never the derived state) and re-run.
5. Tell the learner what changed in plain language, and to **start the next lesson in a new conversation**.

Lesson records are immutable after closing, except to fix factual errors in a new commit.
