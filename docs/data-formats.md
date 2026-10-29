# Data formats

| File | Format | Schema | Mutability |
|---|---|---|---|
| `learner/preferences.yaml` | YAML | `learner-preferences` | edited on learner request |
| `programs/<id>/program.yaml` | YAML | `program` | authored; stable once lessons exist |
| `programs/<id>/lessons/NNN-slug.md` | Markdown + YAML frontmatter | `lesson-record` | written once at lesson close |
| `programs/<id>/logs/assessments.jsonl` | JSONL | `assessment-event` | append-only |
| `programs/<id>/state/mastery.yaml` | YAML | `mastery` | derived |
| `programs/<id>/state/progress.yaml` | YAML | `progress` | derived |
| `programs/<id>/materials/*.md` | Markdown | none | authored |

Schemas are in `engine/schemas/*.schema.yaml` (JSON-Schema subset written in YAML). All carry `schema_version: 1`.

## Assessment event (one JSONL line)

```json
{"schema_version":1,"ts":"2026-01-05T10:20:00Z","program":"my-program","lesson":1,"competency":"some-competency","kind":"practice","score":0.8,"notes":"one hint"}
```

`kind`: diagnostic, practice, quiz, explain-back, project, review. `score`: 0.0-1.0. `ts`: UTC, non-decreasing within a log.

## Mastery derivation

Per competency, events in log order: `score = first event`, then `score = alpha*new + (1-alpha)*score`. Status:
`unseen` (no events) -> `learning` -> `proficient` (score >= proficient_threshold and events >= min_evidence) -> `mastered` (>= mastered_threshold, same evidence rule). Scores are rounded to 4 decimals.

## Supported YAML subset

Block maps/lists, scalars (null, bool, int, float, plain/quoted strings), flow lists of scalars, `{}`/`[]`, `|` and `|-` blocks, comments. No anchors, tags, merge keys, folded blocks, nested flow collections, or tabs. Dates are strings checked by `format: date`.

## Validation checks (`los.py validate`)

Schema conformity; id/directory match; unique competency ids; prerequisites exist and are acyclic; threshold ordering; log lines parse, reference known competencies and existing lessons, timestamps non-decreasing; lesson files named `NNN-slug.md`, numbered 1..N, with Summary and Handoff sections; derived state equals fresh derivation. Warnings: missing preferences, `TODO` placeholders (errors under `--strict`).
