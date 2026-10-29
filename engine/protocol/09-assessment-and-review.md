# 9. Assessment, mastery and review

Binding. Extends 03 (scoring bands, `log`) without replacing it. The assessment log stays the only source of truth;
everything below is either a way to append to it or a function of it.

## Evidence classes (what the engine believes)

| Class | How it arises | Counts toward score/proficient | Can earn strict `mastered` |
|---|---|---|---|
| assisted | any hint / worked example / explanation before answering | no | no |
| valid | independent attempt committed through `assess commit` (rubric hash, confidence not low) | yes | yes |
| unverified | legacy `log` lines, or `log --independence independent` without a rubric | yes | no |

Levels per competency (`state/evidence.yaml`): `unseen` < `exposure` (taught, no evidence) < `assisted` < `independent` < `retained`
(a passing delayed review at least `min_retention_days` after the first valid pass). `mastered` in a **strict** program also needs enough
valid assessments, several task types, one medium/hard pass and retention (`evidence_policy` in `program.yaml`). Status text always
shows what is missing (`mastered_blockers`). Absent `evidence_policy` = **legacy** mode: the pre-Phase-6 rule, except assisted events never count.

## Roles

- **Examiner** (subagent, no write tools): Mode A writes ONE task + private rubric; Mode B returns grading YAML from `assess brief`. It has not seen the tutoring.
- **Tutor** (you): persists everything, shows the learner only `assess show`, never the rubric or key before submission, and never edits state files.
- The private rubric (`assessments/asm-NNN/private.yaml`) is a **procedural** boundary, not a security one: you can read it. Do not copy it into the conversation.
  Prefer objective `check`s (graded by the engine) over judged criteria. The rubric hash makes later edits detectable.

## Workflow (learner never types ids)

1. Context: an active lesson (`lesson start`) **or** an open review session (`review start`).
2. Ask the Examiner for a task: type `recall` | `application` | `transfer` | `delayed_review`, difficulty, `task_id` (new kebab-case id),
   `competency`, `objective`, prompt, optional `items`, and `rubric` (criteria with weights; objective = `check` + `item`, judged = `full`/`zero`).
   Do not reuse a scored item. Save it as YAML, then `assess create <id> --file draft.yaml` (idempotent on `task_id`).
3. Show `assess show <id> <asm>`. The learner answers independently. If they ask for help, **first** `assess hint ... --level hint-N`: the attempt becomes assisted and capped.
4. `assess submit` (the answer is final), `assess brief` (Examiner input), `assess grade --file` (engine auto-grades objective checks; the Examiner cannot override them).
5. Low confidence or ambiguity => `needs_review`: ask a human (the learner or an external reviewer), then `assess review --confirm --statement "..."` (optionally `--credit criterion=0.5` on judged criteria).
6. `assess commit` appends ONE event (idempotent) and refreshes derived state. Mistaken tasks: `assess void` before commit; after commit correct with a later explained event.
7. A lesson cannot `complete` while one of its assessments is submitted but uncommitted. `lesson await-assessment` is the moment to run this workflow.

## Misconceptions

Examiner output `misconceptions: [{text, status}]`, `status` = `suspected` | `demonstrated` (text is a short falsifiable claim). Assisted attempts can only suspect.
Resolve with `resolves: [text]` on a **valid, passing, non-easy, independent** assessment; anything else is refused at commit. Re-demonstration after resolution counts as a recurrence.
Recurring ones are listed first in lesson contexts.

## Spaced repetition (`review ...`)

Intervals default to 1, 3, 7, 14, 30 days (`review_policy`). A competency enters the schedule at its first independent pass. A strong pass (>= mastered threshold)
at or after the due date advances one stage; a borderline pass repeats the interval once, then advances; a failure drops two stages and is prioritized; early successes do not
lengthen the interval; assisted attempts never advance or reset. Priority: failed > prerequisite-critical > overdue > due, then days overdue. The daily limit is
`min(max_per_day, target_minutes / minutes_per_item)`; items assigned today count even if skipped. This is a simple explainable heuristic, **not** an optimal algorithm.

Review session (fresh conversation, "review what I'm about to forget"): `review due` -> `review start --provider ...` -> `review brief` (your whole briefing) ->
per item steps 2-6 above (`assess create --review review-NNN` is automatic when the review is open and no lesson is) -> `review complete` and give the learner its summary.
A review never needs or creates a lesson and never consumes a lesson number. Skipping needs the learner's reason (`review skip`); `review abandon` needs `--confirm`.

## Progress

`progress <id>` prints measured facts first and a clearly labelled rule-based suggestion after. Report it faithfully; add your own interpretation only in a separate, labelled paragraph.
Never quote a percentage that the report withheld for thin data.
