Run an independent assessment for program $1 (and topic $2 if given) (first word = program id; the rest = topic or competency, in the learner's words).

1. Read `AGENTS.md` and `engine/protocol/09-assessment-and-review.md`. If no lesson is open and no review is open, start `lesson start` for the
   topic's objective (or `review start` if the learner wants retrieval of older material); never assess without one of them.
2. Map the topic to a competency/objective from `python3 scripts/los.py lesson brief <program-id>` (do not ask the learner for ids).
3. Delegate task + private rubric to the examiner subagent (spawn it explicitly, or apply engine/roles/examiner.md yourself and say the task was not independent), `assess create`, show ONLY `assess show`, no hints (record any with `assess hint`).
4. `assess submit`, `assess brief` -> examiner, `assess grade`, human review if flagged, `assess commit`. Report the score honestly,
   whether it counted as independent evidence, and what is still missing for mastery.
