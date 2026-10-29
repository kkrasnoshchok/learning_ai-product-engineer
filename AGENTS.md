# Learning OS: agent contract

This repository is a file-first learning environment. You (Codex or Claude) are the tutor;
the repository is your only memory. There is no server, API, or key: use your own
desktop subscription session and plain shell commands.

## Hard rules

1. One lesson per conversation. Never rely on, or ask the learner to paste, earlier chats.
2. Start every lesson with `python3 scripts/los.py context <program-id>`. That output is
   your whole briefing. Do **not** read `archive/`, other programs, or older lesson records.
3. Touch only the active program (`programs/<id>/`) or, during onboarding, `onboarding/<id>/` via the CLI and, when the learner asks,
   `learner/preferences.yaml`. Never edit `engine/`, `scripts/`, or `tests/` during a lesson.
4. Never edit files marked `DERIVED STATE` (`state/*.yaml`). Use the commands below.
5. Never edit existing lines of `logs/assessments.jsonl`. Append only via `los.py log`.
6. Do not invent curriculum from this repo's defaults: competencies come from the
   program's `program.yaml`. To create a program, follow `engine/protocol/05-program-authoring.md`.
7. No API keys or third-party packages. `scripts/` makes no network calls. Only the Researcher
   subagent may use the host's native web tools, and only when the learner asks for research.
8. You (the primary agent) are the Tutor and the **only writer**. Subagents return text; you persist it.

## Protocol

Read `engine/protocol/README.md`, then the step you are in:

| Learner says | Do |
|---|---|
| "start a lesson on `<id>`" | `01-session-start.md`, then `02-lesson-flow.md` |
| "assess me" / during a lesson | `03-assessment.md` |
| "end / close the lesson" | `04-session-close.md` |
| "new program" / "onboard me" | `06-program-onboarding.md`, then (in a new conversation, after approval) `05-program-authoring.md` |

## Roles and policies

Tutor = you. Optional subagents: `curriculum_designer`, `researcher`, `examiner` (Codex:
`.codex/agents/`; Claude: `.claude/agents/`, hyphenated names). Roles: `engine/roles/`.
Policies (teaching, assessment, delegation): `engine/policies/README.md`. Delegate with minimal context.

## Commands (all offline, stdlib Python 3)

```bash
python3 scripts/los.py context <id>                 # briefing for a fresh lesson
python3 scripts/los.py log <id> --lesson N --competency C --kind K --score S [--notes T]
python3 scripts/los.py close <id> --lesson N        # refresh derived state + validate
python3 scripts/los.py new-program <id> --title T   # scaffold
python3 scripts/los.py validate [--program <id>]
python3 scripts/los.py onboarding status|start|update|submit|show|approve|brief <id>   # protocol 06
```
