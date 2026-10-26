# CLAUDE.md

Read and follow [AGENTS.md](AGENTS.md). It holds the repo instructions for all agents: the source-of-truth layout, the contract-sync rule, the safety invariants and the `check-` naming convention.

Claude Code specifics for this repo:
- This repo is itself the `frontier-delivery` plugin (manifest at [.claude-plugin/plugin.json](.claude-plugin/plugin.json)). Load your working copy with `claude --plugin-dir .`; the commands are then `/frontier-delivery:shape`, `/frontier-delivery:deliver` and `/frontier-delivery:inbox`.
- Role wrappers live in [agents/](agents/), commands in [commands/](commands/), and the guard hook config in [hooks/hooks.json](hooks/hooks.json). Wrappers must stay thin; role content is edited only in [roles/](roles/).
- The runner is plain Python: `PYTHONPATH=runner python -m frontier --help`. Tests: `python -m pytest tests`.
