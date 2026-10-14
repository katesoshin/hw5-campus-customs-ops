"""The Campus Customs agent team: Boss, Inventory, Accounting, Facilities, Customer Service.

* One PydanticAI agent per role, all on gpt-6-luna via Portkey (config.build_model).
* Shop facts and every write go through the campus-customs MCP server — there is no other
  shop-tools layer. Each role sees only the MCP tools it needs; human-only tools are never exposed.
* Full connectivity: every agent has a `delegate` tool that can hand work to any other agent.
* Every agent-loop step (prompt, model request, tool calls, final output) is appended to
  output/audit_trail.json.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from pydantic_ai import Agent, RunContext
from pydantic_ai.exceptions import UsageLimitExceeded
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.usage import RunUsage

from . import audit
from .config import (
    MAX_DELEGATION_DEPTH,
    MAX_DELEGATIONS_PER_RUN,
    MCP_PYTHON,
    MCP_SERVER,
    MODEL_NAME,
    MODEL_SETTINGS,
    PROMPTS_DIR,
    RUN_LIMITS,
    build_model,
)
from .models import (
    AGENT_NAMES,
    AgentName,
    AgentReport,
    AuditRecord,
    BossReport,
    DelegationResult,
    TeamDeps,
)

# Tools a human calls from the dashboard. Never given to any agent.
HUMAN_ONLY_TOOLS = frozenset({"approve_and_pay", "reject_approval", "close_ticket"})

# Least privilege: which MCP tools each role may call.
AGENT_TOOLS: dict[AgentName, frozenset[str]] = {
    "boss": frozenset({
        "list_open_tickets", "get_ticket", "add_ticket_note", "set_ticket_status",
        "get_cash_position", "list_approvals",
    }),
    "inventory": frozenset({
        "get_ticket", "add_ticket_note", "check_stock", "find_vendors", "get_vendor_status",
        "quote_price", "create_purchase_order", "draft_message",
    }),
    "accounting": frozenset({
        "get_ticket", "add_ticket_note", "get_cash_position", "get_invoice", "get_vendor_status",
        "get_lease", "quote_price", "request_payment", "list_approvals",
    }),
    "facilities": frozenset({
        "get_ticket", "add_ticket_note", "get_lease", "get_cash_position", "draft_message",
    }),
    "customer_service": frozenset({
        "get_ticket", "add_ticket_note", "check_stock", "quote_price", "draft_message",
    }),
}

DESCRIPTIONS: dict[AgentName, str] = {
    "boss": "Owner's right hand. Reads the board, routes tickets, sets ticket status, writes the wrap-up.",
    "inventory": "Stock on hand, vendors and lead times, restock purchase orders (filed for human approval).",
    "accounting": "Cash, invoices, margins and discounts; files payment requests for human approval.",
    "facilities": "The Chapel Street lease: rent amount and due date, landlord contact drafts.",
    "customer_service": "Customer-facing replies: drafts answers to customers/clubs with real stock and prices.",
}

# One MCP connection shared by the whole team (opened once per top-level run in run_agent_task).
mcp_toolset = MCPToolset(Client(StdioTransport(MCP_PYTHON, [str(MCP_SERVER)], cwd=str(MCP_SERVER.parent.parent))))


def _toolset_for(name: AgentName):
    allowed = AGENT_TOOLS[name] - HUMAN_ONLY_TOOLS
    return mcp_toolset.filtered(lambda ctx, tool_def: tool_def.name in allowed)


def _teammates(me: AgentName) -> str:
    return "\n".join(f"- {n}: {DESCRIPTIONS[n]}" for n in AGENT_NAMES if n != me)


async def delegate(ctx: RunContext[TeamDeps], to: AgentName, task: str) -> DelegationResult:
    """Hand a piece of work to a teammate and wait for their report.

    Write `task` so it stands alone: the ticket number, the exact question, any numbers you already
    have, and what you want back. Don't delegate to yourself or bounce a task back unchanged.
    """
    me = ctx.deps
    if to == me.agent:
        return DelegationResult(to=to, ok=False, error="You can't delegate to yourself; do it with your own tools.")
    if me.depth + 1 > MAX_DELEGATION_DEPTH:
        return DelegationResult(to=to, ok=False, error=f"Delegation depth limit ({MAX_DELEGATION_DEPTH}) reached; "
                                "finish with what you have and report back.")
    if me.budget.delegations >= MAX_DELEGATIONS_PER_RUN:
        return DelegationResult(to=to, ok=False, error=f"Run delegation budget ({MAX_DELEGATIONS_PER_RUN}) used up.")
    me.budget.delegations += 1
    child = me.hop(to)
    audit.append(AuditRecord(
        ts=audit.now(), run_id=me.run_id, agent_run_id=f"{me.run_id}-delegation-{me.budget.delegations}",
        event="delegation", agent=me.agent, ticket_id=me.ticket_id, chain=list(me.chain), depth=me.depth,
        delegate_to=to, prompt=audit.clip(task), usage=_usage(ctx.usage),
    ))
    try:
        report = await run_agent(to, task, child, usage=ctx.usage)
    except UsageLimitExceeded:
        raise  # the team-wide token budget is spent: stop the whole run
    except Exception as exc:  # a teammate failing shouldn't crash the caller; it reports the error instead
        return DelegationResult(to=to, ok=False, error=f"{type(exc).__name__}: {exc}"[:500])
    return DelegationResult(to=to, ok=True, report=report)


def _make_agent(name: AgentName) -> Agent[TeamDeps, Any]:
    agent = Agent(
        build_model(),
        name=name,
        deps_type=TeamDeps,
        output_type=BossReport if name == "boss" else AgentReport,
        instructions=(PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"),
        toolsets=[_toolset_for(name)],
        tools=[delegate],
        model_settings=MODEL_SETTINGS,
        retries=2,
    )

    @agent.instructions
    def run_context(ctx: RunContext[TeamDeps]) -> str:
        d = ctx.deps
        left = MAX_DELEGATIONS_PER_RUN - d.budget.delegations
        return (
            f"## This run\n"
            f"- You are `{d.agent}`. Use `{d.agent}` as your agent name in any tool that asks for it.\n"
            f"- Ticket in focus: {d.ticket_id if d.ticket_id is not None else 'none (board-level task)'}\n"
            f"- Delegation chain so far: {' -> '.join(d.chain)} (depth {d.depth} of max {MAX_DELEGATION_DEPTH}); "
            f"{left} delegations left for the whole team this run.\n"
            f"## Teammates you can delegate to\n{_teammates(d.agent)}"
        )

    return agent


AGENTS: dict[AgentName, Agent[TeamDeps, Any]] = {}


def get_agent(name: AgentName) -> Agent[TeamDeps, Any]:
    if name not in AGENTS:
        AGENTS[name] = _make_agent(name)
    return AGENTS[name]


# --------------------------------------------------------------------------- the agent loop

def _usage(u: RunUsage) -> dict[str, int]:
    return {"requests": u.requests, "tool_calls": u.tool_calls,
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


def _describe(node: Any) -> dict[str, Any]:
    """Turn one graph node into the audit fields that matter: what was asked, called, and returned."""
    kind = type(node).__name__
    out: dict[str, Any] = {"node": kind}
    if kind == "UserPromptNode":
        out["prompt"] = audit.clip(str(node.user_prompt))
    elif kind == "ModelRequestNode":
        returns = []
        for part in node.request.parts:
            if part.part_kind in ("tool-return", "retry-prompt"):
                returns.append({
                    "tool": getattr(part, "tool_name", None),
                    "kind": part.part_kind,
                    "content": audit.clip(part.model_response_str() if part.part_kind == "tool-return"
                                          else str(part.content)),
                })
        out["tool_returns"] = returns
    elif kind == "CallToolsNode":
        calls, texts = [], []
        for part in node.model_response.parts:
            if part.part_kind == "tool-call":
                calls.append({"tool": part.tool_name, "args": audit.clip(part.args_as_dict())})
            elif part.part_kind == "text" and part.content.strip():
                texts.append(part.content)
        out["tool_calls"] = calls
        if texts:
            out["model_text"] = audit.clip("\n".join(texts))
    elif kind == "End":
        data = node.data.output
        out["output"] = data.model_dump(mode="json") if hasattr(data, "model_dump") else {"text": str(data)}
    return out


async def run_agent(name: AgentName, task: str, deps: TeamDeps, usage: RunUsage | None = None) -> Any:
    """Run one agent to completion, appending an audit record for every step of its loop."""
    agent = get_agent(name)
    base = dict(run_id=deps.run_id, agent_run_id=f"{deps.run_id}-{name}-{uuid.uuid4().hex[:6]}", agent=name,
                ticket_id=deps.ticket_id, chain=list(deps.chain), depth=deps.depth, model=MODEL_NAME)
    audit.append(AuditRecord(ts=audit.now(), event="run_start", prompt=audit.clip(task), **base))
    run_usage = usage
    try:
        async with agent.iter(task, deps=deps, usage=usage, usage_limits=RUN_LIMITS) as run:
            step = 0
            async for node in run:
                step += 1
                run_usage = run.usage
                audit.append(AuditRecord(ts=audit.now(), event="step", step=step, usage=_usage(run.usage),
                                         **_describe(node), **base))
            output = run.result.output
    except Exception as exc:
        audit.append(AuditRecord(ts=audit.now(), event="run_error", error=f"{type(exc).__name__}: {exc}"[:1000],
                                 usage=_usage(run_usage) if run_usage else {}, **base))
        raise
    audit.append(AuditRecord(ts=audit.now(), event="run_end", output=output.model_dump(mode="json"),
                             usage=_usage(run.usage), **base))
    return output


async def run_agent_task(name: AgentName, task: str, ticket_id: int | None = None,
                         run_id: str | None = None) -> Any:
    """Top-level entry point: open the MCP connection once and run `name` on `task`."""
    deps = TeamDeps(agent=name, ticket_id=ticket_id, chain=(name,))
    if run_id:
        deps.run_id = run_id
    async with mcp_toolset:
        return await run_agent(name, task, deps)


async def run_ticket(ticket_id: int, run_id: str | None = None) -> BossReport:
    """Hand a ticket to Boss, who works it with the team."""
    task = (
        f"Work ticket #{ticket_id}. Read it, route the pieces to the right teammates, make sure every "
        "fact comes from the tools, file any approvals or drafts that are needed, set the ticket status, "
        "and give the owner your wrap-up."
    )
    return await run_agent_task("boss", task, ticket_id=ticket_id, run_id=run_id)
