#!/usr/bin/env bash
# Install frontier-delivery into a product repo. Run from the product repo root:
#
#   bash ~/repos/frontier-delivery/init/frontier-init.sh [--github] [--copilot] [--labels]
#        [--process-repo owner/repo] [--ref main]
#
# Always:     .frontier/policy.yaml (the gate policy, yours to edit)
#             .claude/settings.json (enables the frontier-delivery plugin from its marketplace)
# --github:   .github/workflows/frontier.yml (label- and comment-driven unattended mode)
# --labels:   creates the frontier:* labels with gh
# --copilot:  vendors the process as .frontier/process (git submodule) and copies the Copilot agents
#
# It never overwrites an existing file; it tells you what it skipped.
set -euo pipefail

PROCESS_REPO="markchivs73/frontier-delivery"
REF="main"
WITH_GITHUB=0
WITH_COPILOT=0
WITH_LABELS=0
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROCESS_ROOT="$(cd "$HERE/.." && pwd)"

while [ $# -gt 0 ]; do
  case "$1" in
    --github) WITH_GITHUB=1 ;;
    --copilot) WITH_COPILOT=1 ;;
    --labels) WITH_LABELS=1 ;;
    --process-repo) PROCESS_REPO="$2"; shift ;;
    --ref) REF="$2"; shift ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

if ! git rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "Run this from the root of a git repository." >&2; exit 1
fi
cd "$(git rev-parse --show-toplevel)"
if [ "$(pwd)" = "$PROCESS_ROOT" ]; then
  echo "This is the process repo itself; run it from a product repo." >&2; exit 1
fi

say() { printf '  %s\n' "$*"; }
place() {  # place <src> <dest>
  if [ -e "$2" ]; then say "skipped $2 (exists)"; else mkdir -p "$(dirname "$2")"; cp "$1" "$2"; say "wrote   $2"; fi
}

echo "frontier-delivery → $(pwd)"

# 1. Gate policy
place "$PROCESS_ROOT/policy/policy.yaml" ".frontier/policy.yaml"

# 2. Claude Code plugin, enabled for everyone who opens this repo
SETTINGS=".claude/settings.json"
PLUGIN_JSON=$(cat <<JSON
{
  "extraKnownMarketplaces": {
    "frontier": { "source": { "source": "github", "repo": "$PROCESS_REPO", "ref": "$REF" } }
  },
  "enabledPlugins": { "frontier-delivery@frontier": true }
}
JSON
)
if [ ! -e "$SETTINGS" ]; then
  mkdir -p .claude
  printf '%s\n' "$PLUGIN_JSON" > "$SETTINGS"
  say "wrote   $SETTINGS"
elif command -v jq >/dev/null 2>&1; then
  tmp="$(mktemp)"
  jq --argjson add "$PLUGIN_JSON" '. * $add' "$SETTINGS" > "$tmp" && mv "$tmp" "$SETTINGS"
  say "merged  $SETTINGS (plugin marketplace + enabledPlugins)"
else
  say "skipped $SETTINGS (exists and jq is missing); add this yourself:"
  printf '%s\n' "$PLUGIN_JSON"
fi

# 3. work/ must be committed: it is the shared memory between stages.
#    The runner's local ledger must not be: it holds sealed recommendations.
for entry in ".frontier/sealed.json" ".frontier/calibration.jsonl"; do
  if ! { [ -f .gitignore ] && grep -qxF "$entry" .gitignore; }; then
    printf '%s\n' "$entry" >> .gitignore && say "ignored $entry"
  fi
done
if [ -f .gitignore ] && grep -qE '^/?work/?$' .gitignore; then
  say "WARNING: .gitignore ignores work/. Delivery artifacts must be committed on delivery/ branches; remove that line."
fi

# 4. GitHub-native unattended mode
if [ "$WITH_GITHUB" = 1 ]; then
  dest=".github/workflows/frontier.yml"
  if [ -e "$dest" ]; then
    say "skipped $dest (exists)"
  else
    mkdir -p .github/workflows
    sed -e "s#__PROCESS_REPO__#$PROCESS_REPO#g" -e "s#__PROCESS_REF__#$REF#g" "$HERE/templates/frontier.yml" > "$dest"
    say "wrote   $dest"
  fi
fi

if [ "$WITH_LABELS" = 1 ]; then
  if command -v gh >/dev/null 2>&1; then
    while IFS='|' read -r name color desc; do
      gh label create "$name" --color "$color" --description "$desc" --force >/dev/null && say "label   $name"
    done <<'LABELS'
frontier:shape|5319e7|Shape this idea into a backlog
frontier:deliver|0e8a16|Deliver this story
frontier:story|c5def5|A shaped story
frontier:needs-decision|d93f0b|Waiting on a human decision
frontier:gate-backlog|fbca04|Backlog gate pending
frontier:gate-plan|fbca04|Plan gate pending
frontier:gate-merge|fbca04|Merge gate pending
frontier:escalated|b60205|Escalated to a human
LABELS
  else
    say "skipped labels (gh not installed); the workflow creates them on first use"
  fi
fi

# 5. Copilot needs the process files in the repo
if [ "$WITH_COPILOT" = 1 ]; then
  if [ -e .frontier/process/agents ]; then
    say "skipped .frontier/process (already vendored)"
  else
    git submodule add "https://github.com/$PROCESS_REPO" .frontier/process >/dev/null 2>&1 \
      && say "vendored .frontier/process (submodule; Copilot reads role files from it)" \
      || say "could not add the submodule; run: git submodule add https://github.com/$PROCESS_REPO .frontier/process"
  fi
  mkdir -p .github/agents
  for f in "$PROCESS_ROOT"/.github/agents/*.agent.md; do place "$f" ".github/agents/$(basename "$f")"; done
fi

cat <<EOF

Next steps
  1. Commit what was written above.
  2. Local, interactive: open Claude Code here and trust the folder; the plugin installs from
     $PROCESS_REPO. Try /frontier-delivery:shape <idea> or /frontier-delivery:deliver <issue>.
EOF
if [ "$WITH_GITHUB" = 1 ]; then cat <<EOF
  3. GitHub mode, one-off repo settings:
     - Secrets: ANTHROPIC_API_KEY (or CLAUDE_CODE_OAUTH_TOKEN).
     - Settings → Actions → General: allow GitHub Actions to create pull requests.
     - Branch protection on the default branch with required CI checks. The merge gate relies on it.
     - Protect the 'frontier/metrics' branch (the runner's gate ledger) so only Actions can push to it.
     - Settings → General: allow auto-merge (only used if you ever set gates.merge.mode: auto).
  4. Label an idea issue 'frontier:shape', or a story issue 'frontier:deliver'.
EOF
fi
