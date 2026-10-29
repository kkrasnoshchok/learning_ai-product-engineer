# Data formats

| File | Format | Schema | Mutability |
|---|---|---|---|
| `learner/preferences.yaml` | YAML | `learner-preferences` | edited on learner request |
| `programs/<id>/program.yaml` | YAML | `program` | authored; stable once lessons exist |
| `programs/<id>/lessons/NNN-slug.md` | Markdown + YAML frontmatter | `lesson-record` | written once at lesson close |
| `programs/<id>/logs/assessments.jsonl` | JSONL | `assessment-event` | append-only |
| `programs/<id>/state/mastery.yaml` | YAML | `mastery` | derived |
| `programs/<id>/state/progress.yaml` | YAML | `progress` | derived |
| `programs/<id>/sessions/NNN.yaml` | YAML | `lesson-session` | mutable lifecycle record via `los.py lesson`; never evidence |
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

## Research and curriculum (`programs/<id>/design/`)
Schemas: `research-plan`, `research-registry`, `competency-map`, `curriculum` (+ optional `curriculum` pointer in `program.yaml`).
- `research/plan.yaml`: outcomes (seeded from the spec), questions, source categories, quality criteria, gaps, tasks; `status`, `revision`, `approval` (with `content_sha256`).
- `research/registry.yaml`: `browsing` (available|unavailable|unknown), `sources` (status discovered|inspected|verified|unavailable; url or citation; accessed; inspection; relevance; quality; limitations), `findings` (claim|hypothesis|recommendation; only claims with an inspected source may be verified), `tasks` (pending|done|blocked), `limitations`. No quote field.
- `competencies.yaml`: domain-wide, learner-free; objectives, prerequisites, priority, level, sources, assessment criteria, applications.
- `curriculum/draft.yaml`: `basis` revisions, `personalization` (decisions with evidence kinds, sequence), `modules`, `checkpoints`, optional `capstone`.
- `*/versions/`: approved plan/curriculum snapshots, replaced competency maps, `program-before-rNNN.yaml`.
`validate` additionally checks schema, ids, references, approval hashes, snapshot presence and that active `competencies` equal the activated revision.

## Onboarding state
`onboarding/<id>/state.yaml` (schema `engine/schemas/onboarding.schema.yaml`): status `draft | in_review | approved`, a `revision` counter, and the sections `goal`, `profile`, `constraints`, `assumptions`, `open_questions` (+ `approval` once approved). `goals.md` and `program.draft.yaml` beside it are derived previews. On approval the sections are frozen into `programs/<id>/program.yaml` under the optional `spec` key, with a placeholder curriculum.

## Assessment, evidence and review (Phase 6)
`assessment-event` gained optional fields (independence, type, assessment_id, rubric_sha256, misconceptions, ...) and `review_session` as an alternative to `lesson`.
New: `assessments/asm-NNN/task.yaml` (`assessment`), `private.yaml` (`assessment-key`), `reviews/NNN.yaml` (`review-session`), derived `state/evidence.yaml` (`evidence-state`);
`program.yaml` optional `evidence_policy` and `review_policy`. Full reference, migration and limitations: `docs/assessment.md`.

## Lesson sessions (`programs/<id>/sessions/NNN.yaml`, Phase 5)
Schema `lesson-session`: `id` (`lesson-NNN`), `status` (planned | active | paused | awaiting_assessment | completed | abandoned), `curriculum`
(`pinned` with revision + sha256, or `legacy`), `selection` (auto | manual | override, reason, optional learner-approved override), `objectives`
(one `<competency>:<objective>` ref), `outcomes`, `materials` (source + status at plan time), optional `provider`, `notes` (concepts, attempts with
assistance level, misconceptions, open questions), `closure` (outcome, summary, handoff, next_action, assessment `{status, refs}`), `history`.
The lesson record frontmatter gained optional `session`, `curriculum_revision`, `objectives`, `assessment_status`; `program.yaml` `lesson_policy`
gained optional `context_max_chars`. Older files remain valid unchanged. See `docs/lessons.md`.
