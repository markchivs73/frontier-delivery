# Claude Code adapter

This repo is a Claude Code **plugin** (`frontier-delivery`) published through its own **marketplace** (`frontier`): [.claude-plugin/](../.claude-plugin/).

| Component | Where | Notes |
|---|---|---|
| Role subagents | [agents/](../agents/) | 9 thin wrappers: frontmatter (name, description, tool scoping) plus "read and follow `${CLAUDE_PLUGIN_ROOT}/roles/<role>.md`". Invoked as `frontier-delivery:<role>` |
| Commands | [commands/](../commands/) | `/frontier-delivery:shape`, `/frontier-delivery:deliver`, `/frontier-delivery:inbox` |
| Guard hook | [hooks/hooks.json](../hooks/hooks.json) → [runner/frontier/guard.py](../runner/frontier/guard.py) | PreToolUse on Bash and the file-writing tools. Needs `python3` on `PATH` |

## Install

In a product repo, `init/frontier-init.sh` writes this into `.claude/settings.json`, so everyone who trusts the repo gets the plugin:

```json
{
  "extraKnownMarketplaces": {
    "frontier": { "source": { "source": "github", "repo": "markchivs73/frontier-delivery", "ref": "main" } }
  },
  "enabledPlugins": { "frontier-delivery@frontier": true }
}
```

Or by hand: `/plugin marketplace add markchivs73/frontier-delivery`, then `/plugin install frontier-delivery@frontier`. To work on the process itself: `claude --plugin-dir ~/repos/frontier-delivery`.

## Run

```
/frontier-delivery:shape Users want to export reports
/frontier-delivery:deliver gh:myorg/myrepo#42
/frontier-delivery:deliver ado:myorg/myproject/1234
/frontier-delivery:deliver Users need a CSV export on the report page. ACs: WHEN the user clicks Export THE SYSTEM SHALL …
/frontier-delivery:inbox
```

How it maps:
- **Orchestrator = the main session** (through the command). Subagents cannot spawn subagents, so orchestration lives in the top-level conversation, which also hosts the gates naturally. For unattended runs the same rules are executed by the [runner](../runner/README.md), which starts each role as `claude -p --agent frontier-delivery:<role>`.
- **The guard** applies to every role subagent, and to headless runner sessions (`FRONTIER_STRICT=1`). Your own interactive main session is not restricted.
- Check wrappers are tool-scoped to read, search and run commands, plus `Write`, which the guard limits to `work/<id>/envelopes/`. The planner and shaper may write only under `work/`. The implementer can't touch the approved plan artifacts or governance files.
- MCP servers for ADO or GitHub must be configured where the delivery runs; see the tracker table in [README.md](README.md).
