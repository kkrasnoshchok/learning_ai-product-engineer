# Onboarding

One subdirectory per in-progress (or finished) program onboarding: `onboarding/<id>/state.yaml` is the durable
working state, so any new conversation can resume with `python3 scripts/los.py onboarding status <id>`.
`goals.md` and `program.draft.yaml` beside it are derived previews. After approval the program lives in
`programs/<id>/` and `state.yaml` stays as the frozen approval record. This repository ships none.
