"""Running one role as a headless Claude Code session.

Each call is a fresh `claude -p --agent <role>` process, so every role, and in
particular every check agent, starts with a fresh context. The plugin (role
wrappers + guard hooks) is loaded from the process root with --plugin-dir
unless FRONTIER_PLUGIN_DIR says otherwise.
"""
from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from .config import Context


@dataclass
class AgentRun:
    agent: str
    returncode: int
    reply: str
    cost_usd: float | None = None
    stderr: str = ""


class ClaudeRunner:
    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.binary = os.environ.get("FRONTIER_CLAUDE_BIN", "claude")
        self.prefix = ctx.runner_setting("agent_prefix", "frontier-delivery:")
        self.timeout = int(os.environ.get("FRONTIER_AGENT_TIMEOUT", "3600"))

    def command(self, agent: str, prompt: str) -> list[str]:
        cmd = [self.binary, "-p", "--agent", f"{self.prefix}{agent}", "--output-format", "json"]
        plugin_dir = os.environ.get("FRONTIER_PLUGIN_DIR", str(self.ctx.process_root))
        if plugin_dir and plugin_dir != "installed":
            cmd += ["--plugin-dir", plugin_dir]
        mode = self.ctx.runner_setting("permission_mode")
        if mode:
            cmd += ["--permission-mode", mode]
        turns = self.ctx.runner_setting("max_turns") or {}
        limit = turns.get(agent, turns.get("default"))
        if limit:
            cmd += ["--max-turns", str(limit)]
        model = (self.ctx.runner_setting("models") or {}).get(agent)
        if model:
            cmd += ["--model", model]
        cmd.append(prompt)
        return cmd

    def run(self, agent: str, prompt: str) -> AgentRun:
        env = dict(os.environ, FRONTIER_STRICT="1", FRONTIER_PROCESS_ROOT=str(self.ctx.process_root))
        try:
            proc = subprocess.run(
                self.command(agent, prompt),
                cwd=self.ctx.repo, env=env, capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            return AgentRun(agent, 124, "", stderr=f"{agent} timed out after {self.timeout}s")
        reply, cost = proc.stdout, None
        try:
            data = json.loads(proc.stdout)
            reply = data.get("result") or ""
            cost = data.get("total_cost_usd")
        except (json.JSONDecodeError, AttributeError):
            pass
        return AgentRun(agent, proc.returncode, reply, cost, proc.stderr[-4000:])

    def run_parallel(self, prompts: dict[str, str]) -> dict[str, AgentRun]:
        with ThreadPoolExecutor(max_workers=len(prompts) or 1) as pool:
            futures = {agent: pool.submit(self.run, agent, prompt) for agent, prompt in prompts.items()}
            return {agent: f.result() for agent, f in futures.items()}


def clear_envelope(work_dir: Path, agent: str) -> None:
    path = work_dir / "envelopes" / f"{agent}.yaml"
    if path.exists():
        path.unlink()
