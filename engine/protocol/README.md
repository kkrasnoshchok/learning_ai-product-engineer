# Protocol

Binding instructions for any tutor agent. The protocol is subject-agnostic: it says *how* to
run lessons, never *what* to teach (that is in each program's `program.yaml`).

1. [Session start](01-session-start.md): what a fresh lesson may and may not read
2. [Lesson flow](02-lesson-flow.md): structure of one lesson
3. [Assessment](03-assessment.md): evidence, scoring, logging
4. [Session close](04-session-close.md): handoff, derived state, validation
5. [Program authoring](05-program-authoring.md): authoring the curriculum of a program
6. [Program onboarding](06-program-onboarding.md): learner goal to approved program spec (precedes 05)
7. [Research and curriculum](07-research-and-curriculum.md): approved spec to researched, personalized, approved curriculum (replaces the manual drafting in 05 when used)

8. [Lesson lifecycle](08-lesson-lifecycle.md): planning, state machine, pause/resume/complete/abandon (with 02 as the tutoring dialogue)

Cross-cutting: [policies](../policies/README.md) (teaching, assessment, delegation) and [roles](../roles/README.md).

Precedence: learner's explicit request in chat > this protocol > a program's own `materials/`.
(A learner may skip steps; log what actually happened, not what was planned.)
