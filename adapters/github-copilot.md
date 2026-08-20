# GitHub Copilot adapter

The runnable wrappers live at the harness discovery path in this repo: [.github/agents/](../.github/agents/) (`*.agent.md`, including the `orchestrator`). Working in this repo, they are live as-is; for a product repo, vendor + copy per [README.md](README.md).

Usage:
- Select the **orchestrator** custom agent as the primary agent and give it the work-item reference (or inline requirements) to run a full delivery.
- Individual role agents (`planner`, `implementer`, `check-security`, …) can also be used standalone for a single stage.
- With the Azure Boards ↔ GitHub integration, custom agents in the target repo's `.github/agents/` appear in the Boards "Create pull request with GitHub Copilot" agent picker (GitHub-hosted repos only).

Caveats specific to this harness:
- Copilot custom agents don't spawn each other, so the orchestrator wrapper performs stages itself in strict role isolation (reading each role file before each stage). This is weaker than fresh-context checking — for high-stakes deliveries, run the check agents in separate sessions against the branch.
- Verify the `tools:` identifiers in the `*.agent.md` frontmatter against the current Copilot custom-agent docs — tool names evolve; treat the values here as intent (read/search vs edit vs command execution vs GitHub API).
- Repo-wide always-on instructions belong in `.github/copilot-instructions.md` / `AGENTS.md`, not here; these files define selectable roles.
