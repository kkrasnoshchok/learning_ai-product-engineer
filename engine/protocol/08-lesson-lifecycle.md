# 8. Lesson lifecycle

Planning, state and closure of one lesson. The learner never types commands or ids: you run them. All commands are
`python3 scripts/los.py lesson <cmd> <program-id>`; they are offline and idempotent. You are the only writer.

## States

```
planned -> active <-> paused
              |  \-> awaiting_assessment -> active | completed
              \-> completed | abandoned          (paused and planned may also be abandoned)
```

- `completed` means **instruction finished** (outcome `completed` or `partial`). It is never mastery. Only logged
  assessment events (`los.py log`) change mastery; `lesson complete` records whether any exist for this lesson
  (`assessment: logged` with line refs, or `not_assessed`) and never creates one.
- `awaiting_assessment`: teaching is done and an independent assessment is still owed.
- One open lesson per program. Planning while one is open returns it. Lesson numbers equal the next lesson-record number;
  an abandoned lesson keeps its number (its record has outcome `abandoned`).

Files: `programs/<id>/sessions/NNN.yaml` (mutable lifecycle record, schema `lesson-session`) and, at close,
`lessons/NNN-slug.md` (immutable record). Never edit either by hand.

## Entry (every lesson, fresh conversation)

1. `lesson status <id>`. If it fails validation, stop and show the errors.
2. **Open lesson exists**
   - `paused` or `awaiting_assessment`: tell the learner what it is (objective, where it stopped) and `lesson resume <id>`.
   - `active`: it is probably the last conversation, which may still be open. Ask the learner; if that conversation is gone,
     `lesson resume <id> --takeover`. Never run two live conversations on one lesson.
   - `mid-close` (status says so, or `validate` reports an interrupted close): re-run `lesson complete <id>`.
3. **No open lesson**: `lesson next <id>`. Present the recommended objective and *why* in plain words, plus alternatives and any
   blockers. The learner may accept, pick another (`--objective <ref>`), or ask what is blocked. Then `lesson start <id>`.
   - Prerequisites without demonstrated mastery are never skipped silently. If the learner insists, explain the risk, ask for
     their reason in their words, and only then `lesson start <id> --objective <ref> --override-rationale "..." --statement "<their words>" --confirm`.
   - No suitable objective: report the blockers verbatim and agree a next step (assessment, curriculum change via protocol 07).
   - Self-reported experience is a hypothesis. Verify it with a diagnostic; do not skip an objective because the learner says they know it.
4. Pass `--provider claude|codex` and `--thread "<title>"` only if you know them. The baseline works without.
5. `lesson brief <id>` (same as `context <id>`) is your whole briefing. Follow `02-lesson-flow.md`.

## During the lesson

- Capture as you go, in small batches, so a crash or pause loses nothing: `lesson note <id> --file -` with a YAML mapping of
  `concepts_explained`, `attempts` (objective, task, assistance, result), `misconceptions` (text, competency, status),
  `unresolved_questions`. Assistance is `none | hint-1..hint-4 | worked-example | explained`, the same ladder as `policies/assessment.md`.
  A misconception may be marked `resolved` only after a recorded independent (`none`) correct attempt on that competency.
- Score independent work with `los.py log` per `03-assessment.md`. Notes are your interpretation; log events are evidence.
- Teaching never changes mastery. Do not tell the learner they have mastered anything.

## Pause, finish, abandon

- **Pause** (learner stops, or time is up): `lesson pause <id> --note "where we stopped"`. Say the next conversation resumes it.
- **Instruction done, assessment owed**: `lesson await-assessment <id>`.
- **Complete**: `lesson complete <id> --file -` with `summary`, `handoff` (what a stranger needs), `next_action`, optional
  `competencies_covered`, `next_focus`, and `outcome` (`completed` | `partial`; or `--outcome partial`). Unknown fields are
  rejected, so mastery cannot be asserted here. This writes the lesson record, rebuilds derived state and validates.
  Tell the learner what changed, whether the lesson was independently assessed, and to start the next one in a **new conversation**.
- **Abandon**: only on the learner's explicit yes. `lesson abandon <id> --reason "<their words>" --confirm`.
- A failed or repeated command is safe to re-run. Do not hand-edit around errors; report them.

## Subagents

Ordinary explanations and quick questions stay with you. Delegate (policies/delegation.md) only when it adds independence:
the Examiner for an independent assessment item or scoring, the Curriculum Designer when prerequisites look wrong or `lesson next`
reports a structural blocker, the Researcher when the learner asks for or approves resource verification. They return text;
you persist. The Examiner never logs and never touches lesson state.

## Without the lifecycle

Programs and lessons predating this protocol, or a learner who declines it, can still use `04-session-close.md` manually.
Do not mix both for the same lesson: validation flags a lesson record that its session does not own.
