---
description: Show everything frontier-delivery is waiting on you for - pending gates and escalations, locally and on GitHub
argument-hint: "[owner/repo]"
---

Show me my frontier-delivery decision inbox. Be brief: one line per item, most urgent (escalations) first.

1. **Local:** read every `work/*/state.yaml` in this repo (or run `PYTHONPATH=${CLAUDE_PLUGIN_ROOT}/runner python3 -m frontier status` if Python is available). List each item whose stage is `escalate`, or that has a gate with `pending: true`. Show the work item, the gate or escalation, and the question.
2. **GitHub** (if `gh` is authenticated): `gh search issues --label frontier:needs-decision --state open --json repository,number,title,url,labels` (limited to $ARGUMENTS if given). Show the repo, the number with its link, the title, and which gate label is set (`frontier:gate-backlog`, `frontier:gate-plan`, `frontier:gate-merge`) or `frontier:escalated`.
3. For each item, say in one short phrase what I need to do: choose an option, approve or ask for changes on a plan, review a PR, or answer a question. Include the reply syntax when it's a GitHub item (`/option`, `/approve`, `/changes`, `/answer`, `/reject`).
4. If nothing is waiting, say so in one line.
