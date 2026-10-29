# Programs

Each subdirectory is one independent learning program (`programs/<id>/`). Programs share nothing
except the engine and `learner/preferences.yaml`. This repository ships none: create one with

```bash
python3 scripts/los.py new-program <id> --title "<Title>"
```

Layout of a program:

```
program.yaml            definition: goal, competency graph, policies   (human/agent authored)
materials/              educational Markdown documents                  (authored)
lessons/NNN-slug.md     one record per lesson: Summary + Handoff        (authored, immutable once closed)
logs/assessments.jsonl  append-only assessment events                   (append via `los.py log`)
state/mastery.yaml      DERIVED from the log                            (never edit)
state/progress.yaml     DERIVED from lesson records                     (never edit)
```
