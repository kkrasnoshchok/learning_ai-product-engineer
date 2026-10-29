# Using Learning OS with Codex Desktop

Auth: your ChatGPT/Codex subscription sign-in in the desktop app. Nothing in this repo needs an API key.

## Setup (once)
1. Open Codex Desktop and add this folder (`learning-os/`) as a project.
2. Codex reads `AGENTS.md` at the project root, which holds the full contract (rules, protocol index, commands). No other configuration is required.
3. Edit `learner/preferences.yaml` to your taste.

## Create a program
1. New thread: "Onboard a new program with id `my-program` titled `My Program Title`." Codex follows `engine/protocol/06-program-onboarding.md`, saves progress in `onboarding/my-program/`, and creates the program only after your explicit approval. To resume, say "Resume onboarding for my-program" in a new thread.
2. Another new thread: "Author the curriculum for my-program" (`05-program-authoring.md`, starting from `onboarding brief`).

## Every lesson
1. Start a **new thread** (never continue an old lesson thread).
2. Say: "Start a lesson on my-program." Codex runs `python3 scripts/los.py context my-program` and proceeds per the protocol.
3. At the end say: "Close the lesson." Codex writes the lesson record and runs `python3 scripts/los.py close my-program --lesson N`.

## Optional shortcut prompts
`adapters/codex/prompts/*.md` mirror the Claude slash commands (`$1`, `$2` positional arguments). If your Codex version supports custom prompt files, copy them into its prompts folder (commonly `~/.codex/prompts/`); otherwise ignore them, since the plain-language phrases above work with `AGENTS.md` alone.

## Notes
- Approve command execution and file writes under `programs/` when prompted.
- Sandboxed runs must be able to write inside the project folder; the tooling needs no network.
- Verified here: the repository, scripts, and tests. The Codex Desktop UI steps follow its documented `AGENTS.md` behavior but were not exercised in this session.

## Subagents
`.codex/agents/*.toml` defines `curriculum_designer`, `researcher`, `examiner` (keys: `name`, `description`, `developer_instructions`).
`.codex/config.toml` sets `[agents] max_concurrent_threads_per_session = 3`. Ask explicitly: "spawn the examiner to ...".
Codex custom agents inherit the parent sandbox, so read-only behaviour is by instruction, not enforcement.
Not verified: no Codex binary exists in the authoring environment, so delegation in Codex Desktop was never run.
