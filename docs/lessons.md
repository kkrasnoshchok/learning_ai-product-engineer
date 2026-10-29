# Lesson lifecycle (Phase 5)

How a learner runs interactive lessons in fresh Claude Desktop (Code tab) or Codex Desktop conversations while progress
stays durable. This is a **custom** pedagogical workflow written as repository protocol; it is not an integration with
ChatGPT's native Study Mode or any product feature. No API keys, backend, or custom GUI are involved.

## The learner's experience (baseline: works with a manual "New chat")

1. Open the Learning OS folder in the desktop app and start a **new conversation** yourself.
2. Claude: `/lesson` or `/lesson my-program`. Codex: "Start a lesson on my-program" (or the `lesson` prompt file).
3. The tutor checks state. It either resumes your open lesson, or tells you the recommended next objective and why, and you
   agree, choose another, or ask what is blocked. You never type ids or CLI commands.
4. You learn through short dialogue: recall, diagnostic, explanation, guided practice, independent challenge, reflection.
5. Say you are done: `/pause-lesson` (continue later) or `/close-lesson` (finish). The tutor saves a handoff.
6. Start the next lesson in another **new** conversation. Nothing is copied between conversations; the files carry it.

The CLI does not create or switch desktop conversations. Neither Claude Desktop nor Codex Desktop exposes a supported way
for these scripts to open a thread, so none is attempted (see Limitations).

## Lifecycle

States: `planned`, `active`, `paused`, `awaiting_assessment`, `completed`, `abandoned` (protocol 08 has the diagram).
`completed` = instruction finished; the closure records `outcome` (`completed`/`partial`) and `assessment`
(`logged` with line refs into `logs/assessments.jsonl`, or `not_assessed`). Mastery is derived only from the log, so a
completed lesson with `not_assessed` leaves every competency exactly as it was.

| Command (`python3 scripts/los.py lesson ...`) | Purpose |
|---|---|
| `next <id>` | recommend; prints reason, alternatives, blockers; writes nothing (exit 1 if nothing is eligible) |
| `start <id> [--objective REF] [--override-rationale T --statement T --confirm]` | plan if nothing is open, then activate; idempotent |
| `status <id>` | open lesson and recent closed lessons |
| `brief <id>` | resume brief = `context <id>` for the open lesson |
| `note <id> --file -` | save concepts, attempts (with assistance level), misconceptions, open questions |
| `pause`, `resume [--takeover]`, `await-assessment` | transitions; repeating them is a no-op |
| `complete <id> --file - [--outcome partial]` | write the lesson record, rebuild state, validate |
| `abandon <id> --reason T --confirm` | explicit-confirmation abandon; writes an `abandoned` record |
| `los.py programs` | choose a program; shows open lessons |

### Planning rules (deterministic)
- Objectives come in curriculum order (module order, then objective order) from the **activated, approved** curriculum snapshot.
  A program whose curriculum is a draft, in review, or a onboarding placeholder is refused. Programs with no curriculum
  pipeline at all use competency-level objectives `<competency>:overall` ("legacy" mode).
- Eligible = all prerequisite competencies are `proficient`/`mastered` **by logged assessment**. Self-reported experience, curriculum
  rationale, and having been taught never count. Ineligible objectives are reported as blockers, never skipped.
- `new`: objective not yet covered by a completed lesson (and its competency not already demonstrated). `consolidate`: all objectives of
  a competency were taught but the competency is not demonstrated, so the next lesson should assess it independently.
- Ties: competencies named in the previous lesson's `next_focus` first, then curriculum order.
- Manual choice: `--objective`. Unmet prerequisites need a recorded, learner-approved override (rationale + the learner's words + `--confirm`).
- The session pins the curriculum revision and its sha256; `validate` fails if the snapshot later changes.

### Persistence and recovery
- `sessions/NNN.yaml` is written atomically; planning creates it exclusively (never overwrites).
- `complete` order: save closure in the session, create `lessons/NNN-slug.md` exclusively, rebuild derived state, mark the session terminal.
  If interrupted, `validate` reports "interrupted close", other transitions refuse, and re-running `lesson complete` finishes
  without changing the record. A lesson record that belongs to a different session is never overwritten.
- Two live conversations: if both supply different `--thread` refs the second is refused; without refs the tool cannot tell and the
  tutor asks (protocol 08). `resume --takeover` is for a lesson left `active` by a conversation that is gone.

## Context

`context <id>` (extended; `lesson brief` calls it) assembles only this program's files: preferences, program identity and
pinned curriculum, the current objective with success criteria and exercises, the focus competency and its prerequisites
(others are counted, not listed), observed evidence with log line refs (authoritative), a separate section for self-report and
interpretation, at most 3 open misconceptions, resources with inspection status (uninspected ones are flagged), progress notes,
and the previous handoff. Stable refs: `program:`, `curriculum:<id>@rN#sha`, `objective:`, `competency:`, `registry:`, `lesson:`,
`log:logs/assessments.jsonl:LINE`.
Size: `--max-chars N`, else `lesson_policy.context_max_chars`, else 16000. Optional blocks shrink in a fixed order (suggested focus,
older events, handoff detail, misconceptions, resources, snapshot) and the pack says what shrank. Required blocks are never cut: if they
exceed the limit, the pack is emitted whole with a WARNING.

## Agent responsibilities
Tutor owns the conversation and all writes. Curriculum Designer advises on objectives/prerequisites when a blocker looks structural.
Researcher verifies resources only when the learner asks. Examiner writes and scores independent items and never logs or changes lesson
state. Ordinary explanations do not spawn subagents.

## Compatibility notes
- Claude Desktop (Code tab): slash commands `.claude/commands/{lesson,pause-lesson,close-lesson}.md`.
- Codex Desktop: plain-language phrases work from `AGENTS.md`; optional prompt files in `adapters/codex/prompts/`.
- Both: identical CLI, protocol and files. `--provider`/`--thread` are optional metadata the tutor fills when it knows them.

## Verification status and limitations
- **Verified (CLI level, automated):** planning, gating, pinning, all transitions and invalid transitions, idempotency, conflicts, recovery,
  context isolation and limits, evidence preservation, fresh-conversation resumption from copied files, an end-to-end multi-lesson flow
  (`tests/test_lifecycle.py`, synthetic abstract fixtures only).
- **NOT verified:** anything inside Claude Desktop or Codex Desktop. That slash commands/prompts load, that an agent follows protocol 08
  faithfully, that thread references are available, how permission prompts behave, and the teaching quality of live dialogue were not
  exercised. A manual GUI check is still owed.
- No supported thread-creation API is used; "fresh conversation" is the learner's action. Conflict detection is best-effort without thread refs.
- Misconception and attempt notes are tutor interpretation, stored in `sessions/`; they are not evidence.
- Assessment events carry no assistance field (unchanged); assistance is recorded in lesson notes and in event `--notes`.
- Checkpoints and capstones in a curriculum are not scheduled automatically. Spaced repetition beyond the existing `review_after_days` is Phase 6.
- Lesson numbers are consumed by abandoned lessons; abandoning a never-started plan also writes an `abandoned` record.
