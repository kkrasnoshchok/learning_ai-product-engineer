# 6. Program onboarding

Goal: turn the **learner's** goal into an approved program specification. Subject-agnostic: you supply no content.
This session never teaches and never writes a curriculum. State lives only in `onboarding/<id>/state.yaml`
(edit it through the CLI, never by hand); `goals.md` / `program.draft.yaml` next to it are derived previews.

Start or resume (each GUI conversation does exactly one of these first):
- New: `python3 scripts/los.py onboarding start <id> --title "<Title>"` (refuses if `programs/<id>` or `onboarding/<id>` exists; pick another id).
- Resume / revise: `python3 scripts/los.py onboarding status <id>` is your whole briefing (state, gaps, next step, global preferences). `onboarding list` shows what is open. Do not ask the learner to repeat earlier answers.

Save after each stage with `onboarding update <id> --file -` (YAML on stdin; `goal`, `profile`, `constraints` merge key by key, lists are replaced). Never edit `state.yaml` or `programs/` by hand.

1. **Goal discovery** (`goal`): `statement`; `competency_outcomes` (what they should be able to do); `practical_outcomes`; measurable `success_criteria` (push back on vague ones); `motivation`; `applications`.
2. **Learner profiling** (`profile`): read the global preferences in `onboarding status` and reuse them; ask only what they do not cover. Record `prior_experience` and `knowledge_gaps` (`[]` once the learner confirms none). Offer a short diagnostic; if accepted, an `examiner` may write items. Record `diagnostics` (`prompt`, `outcome`, `assisted`). They are onboarding evidence, not mastery: do not `los.py log` them.
3. **Constraints** (`constraints`): `hours_per_week`, `depth`, `pace`, `deadline` (date or `none`); optionally `session_minutes`, `preferred_methods`, `other`. Per-program overrides only; do not copy global preferences.
4. **Specification**: record `assumptions` and `open_questions` (`id`, `text`, `blocking`, `answer`). Blocking questions must be answered before review. Do not design competencies.
5. **Review and approval**: `onboarding submit <id>` (fails while anything required is missing), then present `onboarding show <id>` and ask plainly whether to approve. Only on an explicit yes in chat run `onboarding approve <id> --revision <N> --statement "<their words>" --confirm`. If they want changes, `update` (this reopens the draft, bumps the revision and requires a new submit). Silence, enthusiasm about a detail, or "looks fine so far" is not approval.

Approval creates `programs/<id>/` (program.yaml with the frozen `spec`, goals.md, placeholder curriculum), never overwrites, and ends this session. Tell the learner to continue with curriculum authoring (protocol 05) in a **new** conversation, which must begin with `onboarding brief <id>`; it refuses until the onboarding is approved.
Safe to interrupt at any point: every `update` is saved; abandoned drafts are inert and can be resumed later.
