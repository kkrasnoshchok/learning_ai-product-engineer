# 7. Research and curriculum design

Goal: turn an **approved onboarding** into an evidence-based, personalized, approved curriculum, then activate it.
Subject-agnostic: you supply no content. All state lives in `programs/<id>/design/` and is edited only through the CLI.
Each GUI conversation does **one stage** and starts with `python3 scripts/los.py curriculum status <id>` (the whole
briefing: stage and next step), then the matching `brief`. Never rely on chat history; never read `archive/` or other programs.

| Stage | Who | Commands |
|---|---|---|
| 1 Research planning | Tutor (Researcher may advise) | `research init`, `research plan-update --file -`, `research plan-show`, `research plan-submit` |
| 2 Plan review | Tutor + learner | present `plan-show`; on an explicit yes: `research plan-approve --revision N --statement "<words>" --confirm` |
| 3 Source research | Researcher returns text; Tutor records | `research brief [--question q]`, `research add --file -` |
| 4 Competency discovery | Curriculum Designer returns text; Tutor records | `curriculum competencies-set --file -` |
| 5 Personalization + curriculum | Curriculum Designer returns text; Tutor records | `curriculum brief`, `curriculum update --file -`, `curriculum check` |
| 6 Review | Tutor + learner | `curriculum submit`, present `curriculum show`; revise with `update` (new revision, back to draft) |
| 7 Approval, activation | Tutor | `curriculum approve --revision N --statement "<words>" --confirm`, then `curriculum activate --revision N` |

## Rules

1. **Planning is not research.** `research init` seeds learner outcomes from the approved spec. Define questions (each tied to an outcome), source categories (official docs, papers/textbooks, courses, industry practice, competency frameworks, job postings, projects, expert articles/case studies), quality criteria, information gaps and one task per question. Research execution is refused until the learner approves the plan.
2. **Never fabricate.** Record only what a tool actually returned. A source is `discovered` (seen in a result), `inspected` (opened and read; needs `accessed` date and `inspection`), `verified` (inspected, rated, corroborated) or `unavailable`. A `claim` may be `verified` only with an inspected source; a `hypothesis` or `recommendation` is model-generated and never `verified`. There is no quote field: paraphrase. Do not invent URLs, dates or authors; use `published: unknown`.
3. **No browsing, no inspection.** If the host has no web tools, run `research add` with `browsing: unavailable` and a `limitations` entry; leave tasks `pending` (or `blocked` with a note). Sources the learner supplies or that exist as local files may be `inspected` with `inspection: learner-provided | local-file`. Do not work around missing tools.
4. **Domain map first, learner second.** `competencies-set` takes domain-wide competencies grounded in registry sources: objectives, prerequisites, priority, level, sources, assessment criteria (one per objective), applications. It rejects duplicate ids, missing/cyclic prerequisites, unknown sources and invalid objective references. It contains nothing about the learner.
5. **Self-report is not mastery.** In `personalization.decisions` every competency is `study`, `verify` (needs a diagnostic assessment in a module) or `deprioritize`. Deprioritizing needs `diagnostic` or `goal` evidence, never `self_reported` or `constraint` alone; a deprioritized prerequisite of a studied competency needs `diagnostic` evidence. Each decision keeps its rationale and evidence refs (the traceable explanation). `sequence` lists included competencies in prerequisite order.
6. **Realistic and measurable.** Modules carry objectives (`competency:objective`), inspected resources, exercises, an independent assessment, completion criteria and honest `est_hours`; add checkpoints and, when useful, a capstone. `curriculum check` compares total hours with `hours_per_week` and the deadline. Do not build the curriculum around one course or book.
7. **Revisions and approval.** Every change to a plan or curriculum bumps its revision and returns it to `draft`. Approve only the revision the learner reviewed, on their explicit yes. Approved revisions are frozen in `versions/` with a content hash; `validate` detects later edits. A stale basis (spec, plan or map changed) must be `curriculum rebase`d and re-reviewed.
8. **Activation** replaces only `program.yaml` `competencies` (and a `curriculum` pointer). It refuses unapproved revisions and refuses to drop competencies that have logged assessments or lessons; logs, lessons and mastery history are never rewritten. A previous approved revision can be re-activated at any time.
9. **Single writer.** Subagents return text (YAML for the Tutor to submit). Only the Tutor runs the commands above, one at a time. Hand a subagent only the brief it needs, not whole registries or transcripts.
10. The Examiner may review assessment items and rubrics in a draft; it never logs or changes progress.

Do not teach in these sessions. After activation, tell the learner to start lessons in a **new** conversation.
