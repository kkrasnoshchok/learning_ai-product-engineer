# Learning OS

A domain-agnostic, local-first, multi-agent learning environment. The repository is the memory;
a desktop coding agent (Claude Desktop Code tab or Codex Desktop) is the tutor; every lesson is a fresh conversation.

- **No hardcoded subject.** The engine ships protocol, schemas, and tooling. Competencies exist only in each program's `program.yaml`.
- **Many independent programs** under `programs/<id>/`, each with its own mastery and progress.
- **Global preferences** (`learner/preferences.yaml`) are separate from program state.
- **Subscription desktop agents only.** No API calls, keys, servers, or web UI. Tooling is offline, stdlib-only Python 3.
- **File-first.** Markdown for instructions and educational documents, YAML for config and state, JSONL for the append-only assessment log.
- **Fresh context per lesson.** A lesson sees only a generated *context pack*, never old conversations.

## Quick start

```bash
python3 scripts/los.py validate                                   # check the repo
python3 scripts/los.py new-program my-program --title "My Program" # scaffold (then author program.yaml)
python3 scripts/los.py context my-program                          # what a fresh lesson receives
make test                                                          # run the test suite
```

Then open this folder in **Claude Desktop (Code tab)** or **Codex Desktop**, start a *new* conversation, and say
`start a lesson on my-program` (Claude also has `/lesson my-program`). See [docs/claude.md](docs/claude.md) and [docs/codex.md](docs/codex.md).

## Layout

```
AGENTS.md  CLAUDE.md          agent entry points (Codex / Claude)
engine/                       subject-agnostic, read-only during lessons
  protocol/                   how lessons run (Markdown)
  schemas/                    data contracts (YAML)
  templates/                  program + lesson-record scaffolds
learner/preferences.yaml      GLOBAL preferences
programs/<id>/                one program: definition, materials, lessons, log, derived state
archive/                      gitignored; raw transcripts; never read by agents
scripts/                      los.py CLI + learning_os package (validate, context, log, rebuild)
tests/                        unittest suite + fixtures (abstract placeholder program)
docs/                         architecture, data formats, per-agent guides
adapters/ .claude/commands/   thin optional shortcuts
```

## From goal to curriculum

`onboarding` (protocol 06) -> `research` (plan, review, sources) -> `curriculum` (competency map, personalization, review, approval, activation), protocol 07. Claude: `/research <id>`, `/curriculum <id>`; Codex: the matching prompts in `adapters/codex/prompts/`.

## The lesson loop

```
new conversation -> los.py context <id> -> teach/assess (los.py log) -> write lessons/NNN.md -> los.py close <id> -> end conversation
```

Details: [docs/architecture.md](docs/architecture.md) · [docs/data-formats.md](docs/data-formats.md).

## Requirements

Python 3.10+ and git. Nothing to install.
