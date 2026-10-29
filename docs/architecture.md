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

## Multi-agent layer (Phase 2)

One primary agent (Tutor) plus three optional, read-only subagents (Curriculum Designer, Researcher, Examiner).

- **Behaviour is defined once** in `engine/roles/` and `engine/policies/`. The agent files in `.claude/agents/*.md`
  and `.codex/agents/*.toml` are thin wrappers (name, description, tool limits, pointer to the role file).
- **Single writer.** Only the Tutor runs `los.py log/close` or edits program files, so parallel subagents cannot corrupt
  authoritative state. Claude enforces this with a `tools` allowlist (no Write/Edit/Bash). Codex custom agents cannot
  override `sandbox_mode` per agent, so there it is enforced by instruction and guarded by tests, not by the sandbox.
- **Independence.** The Examiner never sees the tutoring dialogue and cannot log; assisted work caps below 0.9.
- **Mastery logic unchanged.** Scoring bands, EWMA mastery and thresholds are untouched; policies only constrain how
  events are produced. Misconceptions travel in event `--notes` and the lesson `Handoff` (no schema change).
- **Network.** Only the Researcher has web tools (Claude `WebSearch`/`WebFetch`); the repo's code stays offline.
- **Not in Phase 2:** program onboarding, curriculum research workflow, lesson lifecycle changes.

## Research and curriculum engine (Phase 4)

`scripts/learning_os/design.py` plus schemas `research-plan`, `research-registry`, `competency-map`, `curriculum`. State is
files under `programs/<id>/design/` (plan, registry, domain competency map, curriculum draft, frozen `versions/`); briefs and
learner views are computed on demand, so nothing derived is stored. The plan and curriculum reuse the onboarding pattern
(draft -> in_review -> approved, revision counter, explicit confirmed approval of the reviewed revision) and add a content
hash so edits after approval are detected. Checks are deterministic (graph integrity, references, evidence status,
personalization rules, coverage, ordering, effort vs. deadline); the LLM only proposes content. Activation rewrites only
`program.yaml` `competencies` + a `curriculum` pointer, keeps a backup of the previous file, and refuses to orphan logs or lessons.
The engine makes no network calls: web research is done by the Researcher subagent with the host's own tools, and the
engine only records and validates what is reported.
- **Not in Phase 4:** lessons that consume modules, any real curriculum, a UI.

### Phase 4 limitations and unverified behavior
- No real web research was run; all tests use synthetic fixtures. The registry records what the Researcher reports and cannot check that a URL exists or that a source says what is claimed (the Tutor and learner must spot-check load-bearing sources).
- Subagent and GUI behavior (Claude Desktop Code tab, Codex Desktop) was not exercised; only the CLI and file contracts are tested. Codex cannot enforce read-only subagents by sandbox, only by instruction.
- Effort realism is a total-hours vs. deadline check; it does not model calendar gaps or review time beyond what the draft lists.
- Lessons do not yet consume modules or objectives; the lesson lifecycle is unchanged.

## Lesson lifecycle (Phase 5)

`scripts/learning_os/lifecycle.py`, schema `lesson-session`, protocol `08-lesson-lifecycle.md`. Source-of-truth rules are unchanged:
`logs/assessments.jsonl` stays the only evidence and `state/*.yaml` stays derived. `sessions/NNN.yaml` is a new *mutable workflow* file
(plan, status, tutor notes, closure) and is never an input to mastery. At close it produces the existing immutable `lessons/NNN-slug.md`
(additive optional frontmatter), so `progress.yaml` derivation is untouched. Planning reads only the activated approved curriculum snapshot,
the mastery state and lesson records. `context` was extended in place (same entry point, new blocks and a size budget). Migration: none
needed; programs without `sessions/` behave as before, and programs without a curriculum pipeline plan at competency level.
