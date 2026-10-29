---
description: Pause the open lesson so a new session can resume it (usage: /pause-lesson <program-id> [where we stopped])
argument-hint: <program-id> [note]
---

Pause the lesson for `$ARGUMENTS` (first word = program id, the rest = a note).

First capture anything not yet saved with `python3 scripts/los.py lesson note <program-id> --file -`, then run
`python3 scripts/los.py lesson pause <program-id> --note "<note>"`. Tell the learner the lesson is paused, what the next
conversation will resume, and to start it with `/lesson <program-id>` in a **new session**.
