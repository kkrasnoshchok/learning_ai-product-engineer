# Architecture

## Boundaries

| Zone | Path | Written by | Notes |
|---|---|---|---|
| Engine | `engine/`, `scripts/`, `tests/`, `docs/` | maintainers | Subject-agnostic. Read-only for tutors during lessons. |
| Global learner data | `learner/` | learner (via agent on request) | Preferences only: tone, pacing, formats. No subject matter, no mastery. |
| Program | `programs/<id>/` | tutor during that program's lessons | Isolated: a lesson for program A never reads or writes program B. |
| Archive | `archive/` (gitignored) | learner | Raw transcripts. Never loaded. |

Why this split: preferences follow the learner across subjects, while mastery is only meaningful relative to one competency graph. Keeping them in separate files makes it impossible for one program's evidence to leak into another, and lets you delete or archive a program without touching the rest.

## Source of truth vs derived state

```
logs/assessments.jsonl  ──►  state/mastery.yaml     (derived: EWMA of scores, thresholds from program.yaml)
lessons/NNN-slug.md     ──►  state/progress.yaml    (derived: counts, last lesson, next focus)
```

`los.py rebuild` regenerates derived files; `los.py validate` fails when they differ from a fresh derivation. Hand-edits are therefore detected rather than trusted. The log's append-only property is enforced by tooling (`log` only appends; validation rejects out-of-order timestamps) and by git history.

## Fresh conversation per lesson

A new lesson's only briefing is `los.py context <id>`, which assembles: preferences, program goal, a competency table, suggested focus (planned by last lesson, in-progress, review due, newly unlocked), and the Summary and Handoff of the last N lessons (N = `lesson_policy.history_lessons_in_context`, 0-3). Old conversations are excluded structurally (not stored in the repo, `archive/` is gitignored and forbidden by `AGENTS.md`) and procedurally (`engine/protocol/01-session-start.md`). Continuity is carried by an explicit, small, reviewable `Handoff` section.

## Domain-agnostic engine

No code or schema names a subject. Schemas constrain shape (ids, ranges, enums of *assessment kinds*, not topics). Competencies, prerequisites, thresholds, and lesson length are program data. The scaffold contains one `TODO` stub that `validate --strict` rejects, so an unfinished program cannot pass as a real one.

## Why no PyYAML / jsonschema

The environment needs zero installs and works offline, matching the subscription-only constraint. The cost is a deliberately small YAML subset (`scripts/learning_os/miniyaml.py`) and schema subset (`schema.py`) that reject anything unsupported loudly instead of guessing. Both are unit-tested.

## Extension points

- New assessment kinds: add to `assessment-event.schema.yaml`, `learner-preferences.schema.yaml`, and `03-assessment.md`.
- Different mastery model: change `derive_mastery` in `model.py`; programs' `mastery_policy` and the drift check follow.
- Schema changes: bump `schema_version` and add a migration note here.
