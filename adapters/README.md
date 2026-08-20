# Adapters

The role definitions in [agents/](../agents/) are harness-neutral and are the **source of truth**. The runnable wrappers live where each harness discovers them:

| Harness | Wrapper location (this repo) | Notes |
|---|---|---|
| Claude Code | [.claude/agents/](../.claude/agents/) + [.claude/commands/deliver.md](../.claude/commands/deliver.md) | 8 role subagents + the `/deliver` orchestrator command — see [claude-code.md](claude-code.md) |
| GitHub Copilot | [.github/agents/](../.github/agents/) `*.agent.md` | 9 custom agents incl. `orchestrator` — see [github-copilot.md](github-copilot.md) |

Wrappers are thin: frontmatter + "read and follow `<process-root>/agents/<role>.md`". Keep role content out of wrappers — edits happen once, in `agents/`.

## Where deliveries run — two modes

**In this repo** (trying the process out, or dogfooding on the process itself): the wrappers are already in the harness discovery paths above; nothing to install. The process root is the repo root.

**In a product repo** (the normal case): vendor this repo as `.frontier/`, then copy the wrappers into the target's own discovery paths — harnesses do not look inside a vendored subdirectory:

```bash
# from the target repo root — submodule (recommended) or copy
git submodule add <this-repo-url> .frontier
# or: cp -R /path/to/frontier-delivery .frontier && rm -rf .frontier/.git

mkdir -p .claude/agents .claude/commands .github/agents
cp .frontier/.claude/agents/*.md        .claude/agents/
cp .frontier/.claude/commands/*.md      .claude/commands/
cp .frontier/.github/agents/*.agent.md  .github/agents/
```

Every wrapper resolves the process root itself: `.frontier/` if present, else the repo root — so the same files work unmodified in both modes.

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

Grant read-only scopes wherever the role allows it (Requirements Analyst and all check agents are read-only by contract; only the Orchestrator/Implementer need branch + PR write).

## Work-item ID convention

`ado:<org>/<project>/<id>` | `gh:<owner>/<repo>#<n>` | `local:<slug>` (inline requirements, no tracker). The orchestrator derives the `work/<id>/` directory name by slugifying this reference.
