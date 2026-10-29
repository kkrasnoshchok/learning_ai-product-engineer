Complete the open lesson for program $1 per engine/protocol/08-lesson-lifecycle.md. Log independently scored items with
`python3 scripts/los.py log`, then run `python3 scripts/los.py lesson complete $1 --file -` with summary, handoff, next_action
(and next_focus / outcome: partial if apt). Report whether the lesson was independently assessed; completion is not mastery.
Abandoning needs the learner's explicit yes: `lesson abandon $1 --reason "<their words>" --confirm`.
Then tell the learner to start the next lesson in a new thread.
