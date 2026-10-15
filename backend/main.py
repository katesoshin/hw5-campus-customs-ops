"""Campus Customs backend: the five-agent team and the API the React dashboard calls.

Start the API from the backend/ folder (virtualenv active):

    uvicorn main:app --reload --port 8000

Or work one ticket from the command line (also from backend/):

    python main.py --ticket 101
    python main.py --agent inventory --task "Is CC-TEE-WHITE S in stock?" --ticket 101

Sections in this file:
  1. Config        model (gpt-6-luna via Portkey), paths, token and delegation limits
  2. Audit trail   append-only output/audit_trail.json
  3. Agent team    Boss, Inventory, Accounting, Facilities, Customer Service (PydanticAI)
  4. API routes    FastAPI app for the dashboard
  5. CLI           python main.py --ticket N

Every shop read and write goes through the campus-customs MCP server (mcp_server/server.py); there
is no other shop-tools layer. The one exception is /api/reset, which copies the original database
file over the working copy. Data types live in models.py; agent prompts in prompts/.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import os
import shutil
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:  # so `import models` works however this file is started
    sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.client.transports import StdioTransport  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402
from pydantic_ai import Agent, RunContext  # noqa: E402
from pydantic_ai.exceptions import UsageLimitExceeded  # noqa: E402
from pydantic_ai.mcp import MCPToolset  # noqa: E402
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402
from pydantic_ai.usage import RunUsage, UsageLimits  # noqa: E402

from models import (  # noqa: E402
    AGENT_NAMES,
    AgentName,
    AgentReport,
    AuditRecord,
    BossReport,
    DelegationResult,
    TeamDeps,
)


# =========================================================================== 1. Config
# PORTKEY_API_KEY comes from hw5/.env (copy .env.example), falling back to the course-root .env.
# Never print, log, or return it.

HW5_DIR = BACKEND_DIR.parent
load_dotenv(HW5_DIR / ".env")  # this repo (copy .env.example to .env)
load_dotenv(HW5_DIR.parent / ".env")  # course root, if the repo sits inside the course folder

MODEL_NAME = "gpt-6-luna"  # the only model any agent uses
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"

PROMPTS_DIR = BACKEND_DIR / "prompts"
AUDIT_PATH = HW5_DIR / "output" / "audit_trail.json"
MCP_SERVER = HW5_DIR / "mcp_server" / "server.py"
MCP_PYTHON = sys.executable  # same interpreter as the backend, so FastMCP is importable
ORIGINAL_DB = HW5_DIR / "data" / "campus_customs.db"
WORKING_DB = HW5_DIR / "data" / "campus_customs_new.db"

# Token guardrails. One budget is shared by the whole team for a single top-level run:
# delegated agents draw from the same counters, so a delegation chain can't multiply the spend.
RUN_LIMITS = UsageLimits(request_limit=40, tool_calls_limit=80, total_tokens_limit=250_000)
# Per response. Reasoning tokens count toward max_tokens, so keep reasoning effort low.
MODEL_SETTINGS = OpenAIResponsesModelSettings(max_tokens=8_000, openai_reasoning_effort="low")
MAX_DELEGATION_DEPTH = 3  # boss -> accounting -> facilities is depth 2; one more hop allowed
MAX_DELEGATIONS_PER_RUN = 10
AUDIT_TEXT_LIMIT = 2_000  # characters kept per tool result / model text in the audit trail


@lru_cache(maxsize=1)
def build_model() -> OpenAIResponsesModel:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is missing. Copy .env.example to .env and add your key.")
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL, default_headers={"x-portkey-provider": "openai"})
    return OpenAIResponsesModel(MODEL_NAME, provider=OpenAIProvider(openai_client=client))


# =========================================================================== 2. Audit trail
# output/audit_trail.json is a JSON array that only ever grows: each write reads the existing records,
# adds the new one, and atomically replaces the file. Nothing is ever cleared between runs. If the
# file can't be parsed we stop (raise) rather than overwrite history.

_audit_lock = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def clip(value: Any, limit: int = AUDIT_TEXT_LIMIT) -> Any:
    """Keep audit records readable: long strings are truncated, structures are kept."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    return value


def audit_append(record: AuditRecord) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lock_path = AUDIT_PATH.with_suffix(".lock")
    with _audit_lock, open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)  # also guards against a second process (e.g. the API + a CLI run)
        records: list = []
        if AUDIT_PATH.exists() and AUDIT_PATH.stat().st_size:
            records = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise RuntimeError(f"{AUDIT_PATH} is not a JSON array; refusing to overwrite it.")
        records.append(record.model_dump(mode="json", exclude_none=True))
        tmp = AUDIT_PATH.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, AUDIT_PATH)


# =========================================================================== 3. Agent team
# * One PydanticAI agent per role, all on gpt-6-luna via Portkey (build_model).
# * Shop facts and every write go through the campus-customs MCP server. Each role sees only the MCP
#   tools it needs; human-only tools are never exposed.
# * Full connectivity: every agent has a `delegate` tool that can hand work to any other agent.
# * Every agent-loop step (prompt, model request, tool calls, final output) is appended to the audit trail.

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

# One MCP connection shared by the whole team (kept open for the API's lifetime, or per CLI run).
mcp_toolset = MCPToolset(Client(StdioTransport(MCP_PYTHON, [str(MCP_SERVER)], cwd=str(HW5_DIR))))


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
    audit_append(AuditRecord(
        ts=now(), run_id=me.run_id, agent_run_id=f"{me.run_id}-delegation-{me.budget.delegations}",
        event="delegation", agent=me.agent, ticket_id=me.ticket_id, chain=list(me.chain), depth=me.depth,
        delegate_to=to, prompt=clip(task), usage=_usage(ctx.usage),
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


def _usage(u: RunUsage) -> dict[str, int]:
    return {"requests": u.requests, "tool_calls": u.tool_calls,
            "input_tokens": u.input_tokens, "output_tokens": u.output_tokens}


def _describe(node: Any) -> dict[str, Any]:
    """Turn one graph node into the audit fields that matter: what was asked, called, and returned."""
    kind = type(node).__name__
    out: dict[str, Any] = {"node": kind}
    if kind == "UserPromptNode":
        out["prompt"] = clip(str(node.user_prompt))
    elif kind == "ModelRequestNode":
        returns = []
        for part in node.request.parts:
            if part.part_kind in ("tool-return", "retry-prompt"):
                returns.append({
                    "tool": getattr(part, "tool_name", None),
                    "kind": part.part_kind,
                    "content": clip(part.model_response_str() if part.part_kind == "tool-return"
                                    else str(part.content)),
                })
        out["tool_returns"] = returns
    elif kind == "CallToolsNode":
        calls, texts = [], []
        for part in node.model_response.parts:
            if part.part_kind == "tool-call":
                calls.append({"tool": part.tool_name, "args": clip(part.args_as_dict())})
            elif part.part_kind == "text" and part.content.strip():
                texts.append(part.content)
        out["tool_calls"] = calls
        if texts:
            out["model_text"] = clip("\n".join(texts))
    elif kind == "End":
        data = node.data.output
        out["output"] = data.model_dump(mode="json") if hasattr(data, "model_dump") else {"text": str(data)}
    return out


async def run_agent(name: AgentName, task: str, deps: TeamDeps, usage: RunUsage | None = None) -> Any:
    """The agent loop: run one agent to completion, appending an audit record for every step."""
    agent = get_agent(name)
    base = dict(run_id=deps.run_id, agent_run_id=f"{deps.run_id}-{name}-{uuid.uuid4().hex[:6]}", agent=name,
                ticket_id=deps.ticket_id, chain=list(deps.chain), depth=deps.depth, model=MODEL_NAME)
    audit_append(AuditRecord(ts=now(), event="run_start", prompt=clip(task), **base))
    run_usage = usage
    try:
        async with agent.iter(task, deps=deps, usage=usage, usage_limits=RUN_LIMITS) as run:
            step = 0
            async for node in run:
                step += 1
                run_usage = run.usage
                audit_append(AuditRecord(ts=now(), event="step", step=step, usage=_usage(run.usage),
                                         **_describe(node), **base))
            output = run.result.output
    except Exception as exc:
        audit_append(AuditRecord(ts=now(), event="run_error", error=f"{type(exc).__name__}: {exc}"[:1000],
                                 usage=_usage(run_usage) if run_usage else {}, **base))
        raise
    audit_append(AuditRecord(ts=now(), event="run_end", output=output.model_dump(mode="json"),
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


# =========================================================================== 4. API routes

mcp_client = Client(StdioTransport(MCP_PYTHON, [str(MCP_SERVER)], cwd=str(HW5_DIR)))

# Agent runs started from the dashboard, keyed by run_id (in memory; the audit trail is the durable record).
RUNS: dict[str, dict[str, Any]] = {}
_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI):
    # One MCP connection for the routes and one kept open for the agent team, for the server's lifetime.
    async with mcp_client, mcp_toolset:
        yield


app = FastAPI(title="Campus Customs API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],  # the Vite dashboard
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",  # any other local port Vite falls back to
    allow_methods=["*"],
    allow_headers=["*"],
)


async def call_tool(name: str, args: dict | None = None) -> dict:
    result = await mcp_client.call_tool(name, args or {}, raise_on_error=False)
    if result.is_error:
        raise HTTPException(502, f"MCP tool {name} failed: {result.content[0].text if result.content else ''}")
    return result.structured_content or json.loads(result.content[0].text)


def _running_for(ticket_id: int | None = None) -> list[dict]:
    return [r for r in RUNS.values() if r["status"] == "running" and (ticket_id is None or r["ticket_id"] == ticket_id)]


# ---- tickets

@app.get("/api/tickets")
async def list_tickets() -> dict:
    """All tickets with their status and whether each is open or resolved."""
    data = await call_tool("list_tickets")
    for t in data["tickets"]:
        t["is_resolved"] = t["status"] == "resolved"
        t["agent_running"] = bool(_running_for(t["id"]))
    return data


@app.get("/api/tickets/{ticket_id}")
async def get_ticket(ticket_id: int) -> dict:
    """One ticket with its notes, drafts, approvals, and purchase orders."""
    data = await call_tool("get_ticket", {"ticket_id": ticket_id})
    if not data.get("found"):
        raise HTTPException(404, data.get("error", "Ticket not found"))
    return data


# ---- agent runs

async def _close_if_clear(ticket_id: int, note: str) -> bool:
    """Resolve the ticket on the board if nothing is waiting on a human approval."""
    result = await call_tool("close_ticket", {"ticket_id": ticket_id, "closed_by": "desk", "note": note})
    return bool(result.get("ok"))


async def _run(run_id: str, ticket_id: int) -> None:
    run = RUNS[run_id]
    try:
        report = await run_ticket(ticket_id, run_id=run_id)
        run.update(status="done", result=report.model_dump(mode="json"))
        # Run finished: resolve now, or as soon as a human clears the last pending approval.
        run["resolved"] = await _close_if_clear(ticket_id, f"team run {run_id} finished, nothing pending")
    except Exception as exc:  # recorded in the audit trail too (run_error)
        run.update(status="error", error=f"{type(exc).__name__}: {exc}"[:500])
    finally:
        run["finished_at"] = now()


@app.post("/api/tickets/{ticket_id}/run", status_code=202)
async def run_ticket_route(ticket_id: int) -> dict:
    """Start the agent team on a ticket. Returns at once with a run_id; watch /api/events or /api/runs/{run_id}."""
    found = await call_tool("get_ticket", {"ticket_id": ticket_id})
    if not found.get("found"):
        raise HTTPException(404, found.get("error", "Ticket not found"))
    if _running_for(ticket_id):
        raise HTTPException(409, f"The team is already working ticket {ticket_id}.")
    run_id = uuid.uuid4().hex[:12]
    RUNS[run_id] = {"run_id": run_id, "ticket_id": ticket_id, "status": "running",
                    "started_at": now(), "finished_at": None, "result": None, "error": None}
    task = asyncio.create_task(_run(run_id, ticket_id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return RUNS[run_id]


@app.get("/api/runs")
async def list_runs() -> dict:
    """Runs started since the server came up, newest first."""
    return {"runs": sorted(RUNS.values(), key=lambda r: r["started_at"], reverse=True)}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict:
    """Status of one run, with Boss's final report once it's done."""
    if run_id not in RUNS:
        raise HTTPException(404, "Unknown run_id")
    return RUNS[run_id]


# ---- agent events

def _event_view(r: dict) -> dict | None:
    """Boil one audit record down to what the board shows: who, what they said, which tools."""
    said = r.get("model_text")
    if r["event"] == "run_end":
        said = (r.get("output") or {}).get("summary")
    elif r["event"] in ("run_start", "delegation"):
        said = r.get("prompt")
    elif r["event"] == "run_error":
        said = r.get("error")
    tools = [{"tool": c["tool"], "args": c.get("args", {})} for c in r.get("tool_calls", [])
             if c["tool"] != "final_result"]
    if r["event"] == "step" and not said and not tools:
        return None  # bookkeeping nodes (prompt/request plumbing) aren't interesting on the board
    return {
        "ts": r["ts"], "run_id": r["run_id"], "ticket_id": r.get("ticket_id"), "agent": r["agent"],
        "event": r["event"], "depth": r["depth"], "chain": r.get("chain", []),
        "delegate_to": r.get("delegate_to"), "said": said, "tools": tools,
        "output": r.get("output") if r["event"] == "run_end" else None,
        "usage": r.get("usage", {}),
    }


@app.get("/api/events")
async def events(
    limit: int = Query(50, ge=1, le=500),
    ticket_id: int | None = None,
    run_id: str | None = None,
    after: str | None = Query(None, description="Only events with ts later than this (for polling)."),
) -> dict:
    """Recent agent events from output/audit_trail.json, oldest first: what each agent said and which tools it used."""
    records = json.loads(AUDIT_PATH.read_text(encoding="utf-8")) if AUDIT_PATH.exists() else []
    out = []
    for r in records:
        if ticket_id is not None and r.get("ticket_id") != ticket_id:
            continue
        if run_id and r["run_id"] != run_id:
            continue
        if after and r["ts"] <= after:
            continue
        if (view := _event_view(r)) is not None:
            out.append(view)
    return {"events": out[-limit:], "running": _running_for()}


# ---- approvals & cash

class Decision(BaseModel):
    approved_by: str = Field(min_length=1, description="Name of the human approving or rejecting.")
    note: str = ""


@app.get("/api/approvals")
async def approvals(status: str = Query("pending", pattern="^(pending|paid|rejected|all)$")) -> dict:
    """Payment and purchase-order requests the agents have filed."""
    return await call_tool("list_approvals", {"status": status})


@app.post("/api/approvals/{approval_id}/approve")
async def approve(approval_id: int, body: Decision) -> dict:
    """A human approves a request. This is the only route that moves cash: it records the payment,
    lowers checking, and marks the invoice paid / advances rent / approves the PO. Overdrafts are refused."""
    result = await call_tool("approve_and_pay", {"approval_id": approval_id, "approved_by": body.approved_by})
    if not result.get("ok"):
        raise HTTPException(409, result.get("error", "Approval refused"))
    result["ticket_resolved"] = await _after_decision(approval_id, body.approved_by)
    return result


@app.post("/api/approvals/{approval_id}/reject")
async def reject(approval_id: int, body: Decision) -> dict:
    """A human rejects a request. Nothing is paid."""
    result = await call_tool("reject_approval",
                             {"approval_id": approval_id, "decided_by": body.approved_by, "note": body.note})
    if not result.get("ok"):
        raise HTTPException(409, result.get("error", "Rejection refused"))
    result["ticket_resolved"] = await _after_decision(approval_id, body.approved_by)
    return result


async def _after_decision(approval_id: int, human: str) -> bool:
    """Once the team's run on a ticket is finished, the last human decision closes it."""
    rows = (await call_tool("list_approvals", {"status": "all"}))["approvals"]
    ticket_id = next((a["ticket_id"] for a in rows if a["id"] == approval_id), None)
    if ticket_id is None or _running_for(ticket_id):
        return False
    return await _close_if_clear(ticket_id, f"{human} decided the last pending approval")


@app.get("/api/cash")
async def cash() -> dict:
    """Current checking balance from cash_accounts, plus what's pending and owed."""
    pos = await call_tool("get_cash_position")
    return {
        "shop_today": pos["shop_today"],
        "checking_balance": pos["checking_balance"],
        "pending_approval_total": pos["pending_approval_total"],
        "balance_after_pending": pos["balance_after_pending"],
        "obligations_next_30_days": pos["obligations_next_30_days"],
    }


# ---- reset

@app.post("/api/reset")
async def reset() -> dict:
    """Copy the original database over the working copy for a fresh run. The audit trail is kept."""
    if _running_for():
        raise HTTPException(409, "An agent run is in progress; wait for it to finish before resetting.")
    shutil.copyfile(ORIGINAL_DB, WORKING_DB)
    RUNS.clear()
    tickets = await call_tool("list_tickets")  # also recreates the empty board tables
    cash_now = await call_tool("get_cash_position")
    return {"ok": True, "tickets": [{"id": t["id"], "status": t["status"]} for t in tickets["tickets"]],
            "checking_balance": cash_now["checking_balance"], "audit_trail": "kept"}


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "working_db": WORKING_DB.name, "running": len(_running_for())}


# =========================================================================== 5. CLI

def cli() -> None:
    parser = argparse.ArgumentParser(description="Run the Campus Customs agent team.")
    parser.add_argument("--ticket", type=int, help="ticket id to work")
    parser.add_argument("--agent", choices=AGENT_NAMES, help="run one agent directly instead of Boss")
    parser.add_argument("--task", help="task text for --agent")
    args = parser.parse_args()

    if args.agent:
        if not args.task:
            parser.error("--agent needs --task")
        result = asyncio.run(run_agent_task(args.agent, args.task, ticket_id=args.ticket))
    elif args.ticket is not None:
        result = asyncio.run(run_ticket(args.ticket))
    else:
        parser.error("give --ticket, or --agent with --task")
    print(json.dumps(result.model_dump(mode="json"), indent=2))


if __name__ == "__main__":
    cli()
