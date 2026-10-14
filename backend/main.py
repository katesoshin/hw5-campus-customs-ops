"""Campus Customs backend: the API the React dashboard calls.

Start it from the backend/ folder (with the course .venv active):

    source ../../.venv/bin/activate
    uvicorn main:app --reload --port 8000

Every shop read and write goes through the campus-customs MCP server, the same toolbox the agents
use. The one exception is /api/reset, which copies the original database file over the working copy.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

HW5_DIR = Path(__file__).resolve().parent.parent
if str(HW5_DIR) not in sys.path:  # `uvicorn main:app` runs from backend/, so make `backend` importable
    sys.path.insert(0, str(HW5_DIR))

from fastapi import FastAPI, HTTPException, Query  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastmcp import Client  # noqa: E402
from fastmcp.client.transports import StdioTransport  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from backend import audit  # noqa: E402
from backend.agents import mcp_toolset, run_ticket  # noqa: E402
from backend.config import AUDIT_PATH, MCP_PYTHON, MCP_SERVER  # noqa: E402

ORIGINAL_DB = HW5_DIR / "data" / "campus_customs.db"
WORKING_DB = HW5_DIR / "data" / "campus_customs_new.db"

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


# --------------------------------------------------------------------------- tickets

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


# --------------------------------------------------------------------------- agent runs

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
        run["finished_at"] = audit.now()


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
                    "started_at": audit.now(), "finished_at": None, "result": None, "error": None}
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


# --------------------------------------------------------------------------- agent events

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


# --------------------------------------------------------------------------- approvals & cash

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


# --------------------------------------------------------------------------- reset

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
