# Claude Code adapter

The runnable wrappers live at the harness discovery paths in this repo: [.claude/agents/](../.claude/agents/) (8 role subagents) and [.claude/commands/deliver.md](../.claude/commands/deliver.md) (the orchestrator entry point). Working in this repo, they are live as-is; for a product repo, vendor + copy per [README.md](README.md).

Run a delivery from a Claude Code session:

```
/deliver ado:myorg/myproject/1234
/deliver gh:myorg/myrepo#42
/deliver Users need a CSV export on the report page. ACs: WHEN the user clicks Export THE SYSTEM SHALL ...
```

How it maps:
- **Orchestrator = the main session** (via `/deliver`) — Claude Code subagents cannot spawn subagents, so orchestration lives in the top-level conversation, which also hosts the two human gates naturally.
- **The 8 role wrappers** are thin subagents: frontmatter (name, description, tool scoping) + "read and follow `<process-root>/agents/<role>.md`". Role content lives only in the neutral definitions; wrappers resolve the process root (`.frontier/` if vendored, else repo root) themselves.
- Check wrappers are tool-scoped read-only (plus Bash where the role runs tests). `requirements-analyst`, `implementer`, and `retro` inherit the full toolset because they need MCP and/or write access — their read-only/branch discipline is enforced by their role contracts.
- MCP servers for ADO/GitHub must be configured in the repo where the delivery runs — see the tracker table and setup commands in [README.md](README.md).
