# 5. Program authoring

Goal: produce a valid `program.yaml` for a subject the **learner** chooses. The engine provides no content.

0. For a new learner goal, onboarding comes first ([06](06-program-onboarding.md)). Start here only with an approved onboarding: run `python3 scripts/los.py onboarding brief <id>` and use its output as the goal/constraints. If it refuses, stop and return to onboarding. The program already exists (placeholder competencies); skip step 1.
1. Scaffold (programs created without onboarding only): `python3 scripts/los.py new-program <id> --title "<Title>"` (id: lowercase, digits, hyphens).
2. Interview the learner: goal, current level, time horizon, constraints, how they will use the skill.
3. Draft 5-30 competencies. Each needs an id (kebab-case), title, observable description ("can ..."), and
   prerequisites (ids; no cycles). Prefer small, assessable competencies over topic names.
4. Show the draft and graph to the learner; revise until they approve.
5. Tune `mastery_policy` and `lesson_policy` only if the learner has reasons; defaults are fine.
6. Optionally draft `materials/*.md` for the first competencies.
7. Run `python3 scripts/los.py validate --strict`. Fix every error and TODO.
8. Do not teach in this session. Tell the learner to start a lesson in a new conversation.

Never copy competencies from another program without the learner asking; programs are independent.
