Start or resume a lesson for program $1 (if $1 is empty, run `python3 scripts/los.py programs` and ask which one).
This must be a fresh thread. Read AGENTS.md, engine/protocol/08-lesson-lifecycle.md (Entry) and 02-lesson-flow.md.
Run `python3 scripts/los.py lesson status $1`, then resume or plan exactly as protocol 08 says (you run the commands; the learner
never types ids; pass `--provider codex`). `python3 scripts/los.py lesson brief $1` is your only briefing.
Teach with the Study-Mode-style flow, capture notes with `lesson note`, log independent items with `los.py log`,
and end with `lesson pause`, `lesson await-assessment` or `lesson complete`. Tell the learner to start the next lesson in a new thread.
