---
description: Create a learning program (usage: /new-program <program-id> <title>)
argument-hint: <program-id> <title>
---

Create a new learning program from: `$ARGUMENTS`.

Follow `engine/protocol/05-program-authoring.md`. For a program that has an onboarding, begin with
`python3 scripts/los.py onboarding brief $1` (it refuses until the learner approved; then run `/onboard` instead). Scaffold with `python3 scripts/los.py new-program`,
then interview the learner to author `program.yaml`. Finish with `python3 scripts/los.py validate --strict`.
Do not teach a lesson in this session.
