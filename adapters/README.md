# Adapters

The role definitions in [roles/](../roles/) are harness-neutral and are the **source of truth**. The runnable wrappers live where each harness discovers them:

| Harness | Wrapper location (this repo) | How it is installed in a product repo |
|---|---|---|
| Claude Code | Plugin: [.claude-plugin/plugin.json](../.claude-plugin/plugin.json), [agents/](../agents/) (9 role subagents), [commands/](../commands/) (`shape`, `deliver`, `inbox`), [hooks/](../hooks/) (guard) | `.claude/settings.json` enables `frontier-delivery@frontier` from this repo's marketplace (written by `init/frontier-init.sh`); nothing is copied. See [claude-code.md](claude-code.md) |
| GitHub Copilot | [.github/agents/](../.github/agents/) `*.agent.md` (10 custom agents, including `orchestrator`) | The process is vendored at `.frontier/process/` (submodule) and the wrappers copied to `.github/agents/` (`frontier-init.sh --copilot`). See [github-copilot.md](github-copilot.md) |
| GitHub Actions (unattended) | [.github/workflows/frontier.yml](../.github/workflows/frontier.yml) (reusable) + [runner/](../runner/) | A small caller workflow (`frontier-init.sh --github`) |

Wrappers are thin: frontmatter plus "read and follow the role file". Keep role content out of wrappers; edits happen once, in `roles/`.

- **Claude Code wrappers** reference `${CLAUDE_PLUGIN_ROOT}/roles/<role>.md`, so they always read the role files shipped with the installed plugin version.
- **Copilot wrappers** resolve the process root themselves: `.frontier/process/` if present, otherwise the repo root (working in this repo).
- **The product repo** always keeps its own `.frontier/policy.yaml` (gate policy) and `work/` (delivery artifacts, committed on `delivery/<id>` branches).

## Tracker abstraction (ADO + GitHub via MCP)

Neutral agent definitions name **capabilities**, never concrete MCP tool names. This table is the single mapping from capability to the official MCP servers — the Requirements Analyst, Orchestrator, and Retro agents resolve their tracker operations here.

| Capability | Azure DevOps MCP (`@azure-devops/mcp`) | GitHub MCP (`github-mcp-server`) |
|---|---|---|
| Get work item / issue | `wit_get_work_item` | `get_issue` |
| List work item / issue comments | `wit_list_work_item_comments` | `get_issue_comments` |
| Get linked items | `wit_get_work_items_links` (relations) | issue timeline / linked references |
| Create branch | `repo_create_branch` | `create_branch` |
| Open draft PR | `repo_create_pull_request` (draft) | `create_pull_request` (`draft: true`) |
| Link PR to work item | PR create with work-item link / `wit_add_work_item_link` | closing keyword (`Closes #n`) in PR body |
| Read PR review comments (Retro) | `repo_list_pull_request_threads` | `get_pull_request_comments` / reviews |
| Trigger CI (optional gate) | `pipelines_run_pipeline` | `run_workflow` (actions toolset) |
| Read CI result | `build_get_log` / pipeline status | `get_workflow_run` / job logs |

> Tool names drift between server releases — treat this column pair as the mapping to maintain, and verify against the installed server's tool list (`docs/TOOLSET.md` in `microsoft/azure-devops-mcp`; toolset docs in `github/github-mcp-server`).

### MCP server setup

**Azure DevOps** — local (`npx -y @azure-devops/mcp <org>`) or the remote hosted server (Entra auth). Claude Code:
```bash
claude mcp add azure-devops -- npx -y @azure-devops/mcp <your-org>
```

**GitHub** — remote hosted server (`https://api.githubcopilot.com/mcp/`, OAuth/PAT) or local Docker. Claude Code:
```bash
claude mcp add --transport http github https://api.githubcopilot.com/mcp/
```

Grant read-only scopes wherever the role allows it (the Shaper, Requirements Analyst and all check agents are read-only by contract; only the Orchestrator and Implementer need branch and PR write). In GitHub-native mode the runner does all tracker writes itself with `gh`, so agents need no tracker write access at all.

## Work-item ID convention

`ado:<org>/<project>/<id>` | `gh:<owner>/<repo>#<n>` | `local:<slug>` (inline requirements, no tracker). The orchestrator derives the `work/<id>/` directory name by slugifying this reference.
