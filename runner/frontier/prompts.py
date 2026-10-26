"""The task prompt handed to each role. The role's behaviour comes from its role file
(loaded by the plugin wrapper); the prompt only carries this run's facts and the
verbatim inputs routed to it."""
from __future__ import annotations

from .config import Context


def header(ctx: Context, *, agent: str, stage: str, work_item: str, work_id: str) -> str:
    work_dir = f"work/{work_id}"
    return "\n".join([
        f"You are running the `{agent}` role of the frontier-delivery process, headless, for stage `{stage}`.",
        "There is no human in this session: do not ask questions. If you are blocked, return status: needs_input with the smallest question that unblocks you.",
        "",
        f"WORK_ITEM: {work_item}",
        f"WORK_ID: {work_id}",
        f"WORK_DIR: {work_dir}/",
        f"ENVELOPE_PATH: {work_dir}/envelopes/{agent}.yaml",
        f"PROCESS_ROOT: {ctx.process_root}",
        f"POLICY: {ctx.policy_source}",
        "",
        f"Write your handoff envelope to ENVELOPE_PATH (YAML, per process/handoffs.md) and also end your reply with it as a fenced yaml block.",
    ])


def verbatim(title: str, body: str | None) -> str:
    if not body:
        return ""
    return f"\n\n## {title} (verbatim; do not paraphrase)\n\n{body.strip()}\n"


def shaper(ctx, *, work_item, work_id, idea: str | None, choice: str | None, comments: str | None) -> str:
    text = header(ctx, agent="shaper", stage="shape", work_item=work_item, work_id=work_id)
    if choice:
        text += "\n\nPHASE: backlog. The human has chosen an option; write backlog.md and backlog.yaml for it."
    elif comments:
        text += "\n\nPHASE: backlog (re-shape). Revise the existing backlog only as the comments ask."
    else:
        text += "\n\nPHASE: options. Frame the problem and write options.md; return needs_input with the option titles."
    text += verbatim("The idea", idea)
    text += verbatim("The human's chosen option", choice)
    text += verbatim("The human's comments", comments)
    return text


def analyst(ctx, *, work_item, work_id, source: str | None, answer: str | None = None) -> str:
    text = header(ctx, agent="requirements-analyst", stage="intake", work_item=work_item, work_id=work_id)
    if source:
        text += "\n\nThe work item content has been fetched for you below; treat it as the source (source type: as given by the WORK_ITEM prefix, or inline for local:)."
    else:
        text += "\n\nFetch the work item with the tracker tools (see adapters/README.md)."
    text += verbatim("Work item content", source)
    text += verbatim("The human's answer to your earlier question", answer)
    return text


def planner(ctx, *, work_item, work_id, comments: str | None = None, answer: str | None = None) -> str:
    text = header(ctx, agent="planner", stage="plan", work_item=work_item, work_id=work_id)
    text += f"\n\nInputs: work/{work_id}/requirements.md and the repository. Write design.md (with the Acceptance test plan and Planned paths) and tasks.md."
    text += verbatim("The human's plan-gate comments", comments)
    text += verbatim("The human's answer to your earlier question", answer)
    return text


def implementer(ctx, *, work_item, work_id, branch: str, fix_iteration: int, findings: str | None, human_comments: str | None) -> str:
    text = header(ctx, agent="implementer", stage="implement", work_item=work_item, work_id=work_id)
    text += f"\n\nBRANCH: {branch} (already checked out; commit here, never push)\nFIX_ITERATION: {fix_iteration}"
    text += f"\nInputs: work/{work_id}/requirements.md, design.md, tasks.md (approved)."
    text += verbatim("Blocking findings to resolve", findings)
    text += verbatim("The human's review comments to address", human_comments)
    return text


def check(ctx, *, agent, work_item, work_id, base: str, branch: str) -> str:
    text = header(ctx, agent=agent, stage="verify", work_item=work_item, work_id=work_id)
    text += (
        f"\n\nReview the diff `git diff {base}...{branch}` (exclude work/) against work/{work_id}/requirements.md, design.md and tasks.md, "
        f"plus work/{work_id}/envelopes/implementer.yaml for the self-check. You have not seen the implementer's conversation; judge the artifact."
    )
    return text


def retro(ctx, *, work_item, work_id, merged: bool, review: str | None) -> str:
    text = header(ctx, agent="retro", stage="learn", work_item=work_item, work_id=work_id)
    text += f"\n\nThe PR was {'merged' if merged else 'closed without merging'}. Read work/{work_id}/ (state.yaml holds gate records and loop counts)."
    text += "\nIn headless mode, write lessons to the envelope and to work/{0}/retro.md; do not open PRs yourself.".format(work_id)
    text += verbatim("Human PR review comments", review)
    return text
