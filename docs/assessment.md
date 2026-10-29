# Assessment, mastery and review (Phase 6)

Protocol: `engine/protocol/09-assessment-and-review.md`. This page is the reference for data, rules, migration and limits.

## What the learner says, and what happens

| Learner says | Tutor runs (learner never sees ids) |
|---|---|
| "Test my understanding of this topic." / "Start an independent assessment." | `/assess`: Examiner drafts task + rubric -> `assess create` -> `assess show` -> `submit` -> `brief` -> `grade` -> `commit` |
| "What should I review today?" | `review due <id>` |
| "Start my review session." / "Review what I'm about to forget." | new conversation: `review start` -> `review brief` -> per item the assessment workflow -> `review complete` |
| "Show my learning progress." | `progress <id>` |

## Files (per program)

| Path | Role | Mutability |
|---|---|---|
| `logs/assessments.jsonl` | **source of truth**; Phase 6 added optional fields | append-only |
| `assessments/asm-NNN/task.yaml` | learner-facing task + lifecycle (`assessment` schema) | mutable until committed/void |
| `assessments/asm-NNN/private.yaml` | rubric + answer key (`assessment-key`); sha256 recorded in task.yaml | never shown before submission |
| `reviews/NNN.yaml` | one review session (`review-session`); separate from `sessions/` (lessons) | mutable until completed/abandoned |
| `state/mastery.yaml` | derived; same shape as before | derived |
| `state/evidence.yaml` | derived: evidence levels, review schedule, misconceptions (`evidence-state`) | derived |
| `.los.lock` | advisory per-program write lock (git-ignored) | n/a |

New optional event fields: `assessment_id`, `task_id`, `type` (recall/application/transfer/delayed_review), `objective`, `curriculum_revision`, `difficulty`,
`independence`, `assistance`, `hints`, `confidence`, `grading_method`, `rubric_sha256`, `evidence`, `review_session`, `misconceptions`, `resolves`.
`lesson` is now optional: exactly one of `lesson` / `review_session` must be present. Assessment lifecycle:
`issued -> submitted -> graded | needs_review -> committed | void`. `kind` is derived from `type` (recall=quiz, application=practice, transfer=project, delayed_review=review).

## Mastery rules

Score is still the EWMA over counted events with the program's thresholds. Assisted events are excluded from score, evidence count and status.
In `strict` mode `mastered` additionally needs (see `mastered_blockers` in `state/evidence.yaml`): `min_evidence` valid assessments, `min_task_types` distinct types among valid passes,
a medium/hard pass, a passing `delayed_review` at least `min_retention_days` after the first valid pass, and (optionally) a transfer pass. If the score reaches the mastered
threshold but these are missing, the status is `proficient`. Passing means `score >= proficient_threshold`. Assistance caps the graded score: hint-1 0.8, hint-2 0.7, hint-3 0.6, hint-4 0.5, worked-example/explained 0.3.

Evidence levels: unseen, exposure (taught or tried without a pass), assisted (only assisted passes), independent, retained.

### Migration

- Existing programs have no `evidence_policy` => **legacy** mode: statuses are computed exactly as before, except that explicitly **assisted** events (new) never count.
  Their old log lines are "unverified". Existing derived files stay valid; `state/evidence.yaml` is created by `rebuild` (a missing one is only a warning).
- To opt in, add `evidence_policy: {mode: strict}` (and optionally `review_policy`) to `program.yaml`, then `rebuild`. `progress` reports how much evidence is unverified.
  Statuses may drop from `mastered` to `proficient` until valid evidence exists; that is intended. No log line is rewritten.
- New programs (template and onboarding) are **strict** by default. Delete the block to get the legacy rule.
- `lesson` became optional in `assessment-event` (still required unless `review_session` is present); all old lines remain valid.

## Scheduler

Intervals `review_policy.intervals` (default 1, 3, 7, 14, 30 days), per competency (an objective is picked per review: the least recently evidenced). Rules and priorities are in protocol 09.
The schedule in `state/evidence.yaml` depends only on the log (no wall clock), so a rebuild is deterministic; "due", "overdue" and "missed" (a full interval overdue) are computed for the
date you ask about. Each entry stores the `reason` it is scheduled. A competency in an open review session is never assigned twice; a task id can only be created once.

## Reliability

All multi-file writes take an advisory per-program lock (`fcntl.flock`, POSIX) and use temp-file + rename. Commit order: append event (idempotent on `assessment_id`) -> refresh derived
state -> mark the task committed; a crash between steps is reported by `validate` as a warning and repaired by re-running `assess commit` or `rebuild`.

## Limitations (read these)

- **Privacy of the key is procedural.** The Tutor persists the Examiner's draft and any agent with file access can read `private.yaml`. The engine keeps it out of every context pack, command output
  before submission, and detects edits, but it cannot stop a determined or careless agent. Use objective checks and human review for high-stakes claims.
- **Tutor-supplied grading is model judgement.** Judged criteria depend on an Examiner subagent (or the Tutor playing that role, which is not independent). Confidence and uncertainty are recorded, not verified.
- **"Human review" is whoever confirms.** The engine cannot tell the learner from a third-party reviewer; it records the statement.
- Delayed-review timing uses UTC dates of log timestamps. Time zones, vacations and clock changes are not modelled; missed reviews do not decay the schedule beyond being overdue.
- The scheduler is a simple interval ladder, not a validated memory model. Per-objective scheduling is not implemented (competency level only).
- The advisory lock does not protect network file systems or non-POSIX platforms; separate conversations should not write the same program concurrently.
- Tests run the CLI and library on synthetic data. **No test drives the Claude or Codex desktop apps**; the slash commands, prompt files and subagent hand-offs are unverified in the GUIs.
