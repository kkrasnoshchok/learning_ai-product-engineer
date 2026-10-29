# Protocol

Binding instructions for any tutor agent. The protocol is subject-agnostic: it says *how* to
run lessons, never *what* to teach (that is in each program's `program.yaml`).

1. [Session start](01-session-start.md): what a fresh lesson may and may not read
2. [Lesson flow](02-lesson-flow.md): structure of one lesson
3. [Assessment](03-assessment.md): evidence, scoring, logging
4. [Session close](04-session-close.md): handoff, derived state, validation
5. [Program authoring](05-program-authoring.md): creating a new program

Precedence: learner's explicit request in chat > this protocol > a program's own `materials/`.
(A learner may skip steps; log what actually happened, not what was planned.)
