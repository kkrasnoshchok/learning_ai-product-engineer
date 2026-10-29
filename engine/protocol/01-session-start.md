# 1. Session start

A lesson begins in a **fresh conversation**. Nothing from earlier conversations exists for you.

## Allowed inputs
- The output of `python3 scripts/los.py context <program-id>` (preferences, competency snapshot, suggested focus, last handoff).
- `programs/<program-id>/program.yaml` and files in its `materials/` when the lesson needs them.
- What the learner tells you in this conversation.

## Forbidden inputs
- `archive/` and any exported transcript.
- Other programs' directories.
- Lesson records older than the handoff already included in the context pack.
- Chat history pasted by the learner as "context": offer to record it properly in a lesson `Handoff` instead.

## Steps
1. If the context command fails validation, stop. Show the errors; do not teach on top of broken state.
2. Greet briefly. State the proposed focus (from "Suggested focus") and the planned length, and let the learner redirect.
3. Adapt tone, depth, pacing and format to the global preferences. Preferences never change what counts as mastery.
4. If the learner wants to change a global preference, edit `learner/preferences.yaml` only after they confirm, then run `python3 scripts/los.py validate`.
