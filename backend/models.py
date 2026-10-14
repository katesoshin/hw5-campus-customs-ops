"""Data types shared by the Campus Customs agent team."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field

AgentName = Literal["boss", "inventory", "accounting", "facilities", "customer_service"]
AGENT_NAMES: tuple[AgentName, ...] = ("boss", "inventory", "accounting", "facilities", "customer_service")

TicketStatus = Literal["open", "in_progress", "waiting_on_human", "blocked", "resolved"]


# --------------------------------------------------------------------------- agent outputs

class HumanAction(BaseModel):
    """Something only a person can do: approve a payment, send a draft, make a judgement call."""

    kind: Literal["approve_payment", "approve_purchase_order", "send_draft", "decide", "other"]
    description: str = Field(description="One sentence a busy owner can act on.")
    approval_id: int | None = None
    draft_id: int | None = None
    amount: float | None = None


class AgentReport(BaseModel):
    """What a specialist (Inventory, Accounting, Facilities, Customer Service) hands back."""

    agent: AgentName
    ticket_id: int | None = None
    summary: str = Field(description="2-4 sentences: what you found and what you did.")
    facts: list[str] = Field(default_factory=list, description="Key numbers/dates exactly as the tools returned them.")
    actions_taken: list[str] = Field(default_factory=list, description="Writes you made: notes, drafts, approval requests, POs.")
    human_actions: list[HumanAction] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    recommended_next_step: str | None = None


class BossReport(BaseModel):
    """Boss's final word on a ticket (or on the board)."""

    ticket_ids: list[int]
    status: TicketStatus = Field(description="Status you set (or would set) on the ticket.")
    summary: str = Field(description="Plain-English wrap-up for the owner, 3-6 sentences.")
    delegations: list[str] = Field(default_factory=list, description="Who you asked and what they came back with.")
    human_actions: list[HumanAction] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    cash_note: str | None = Field(default=None, description="How this ticket affects checking, if it touches money.")


class DelegationResult(BaseModel):
    """Returned to an agent by the delegate tool."""

    to: AgentName
    ok: bool
    report: AgentReport | BossReport | None = None
    error: str | None = None


# --------------------------------------------------------------------------- audit trail

class AuditRecord(BaseModel):
    """One line in output/audit_trail.json. One record per agent-loop step plus run/delegation events."""

    ts: str
    run_id: str
    agent_run_id: str
    event: Literal["run_start", "step", "delegation", "run_end", "run_error"]
    agent: AgentName
    ticket_id: int | None = None
    chain: list[AgentName] = Field(description="Who called whom to get here, starting with the top-level agent.")
    depth: int
    step: int | None = None
    node: str | None = Field(default=None, description="UserPromptNode / ModelRequestNode / CallToolsNode / End")
    prompt: str | None = None
    model_text: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    tool_returns: list[dict[str, Any]] = Field(default_factory=list)
    delegate_to: AgentName | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    model: str | None = None
    usage: dict[str, int] = Field(default_factory=dict, description="Cumulative team usage for this run so far.")


# --------------------------------------------------------------------------- run-time dependencies

@dataclass
class RunBudget:
    """Shared across one top-level run so every delegated agent counts against the same caps."""

    delegations: int = 0


@dataclass
class TeamDeps:
    """Passed to every agent run. A new copy is made for each delegation hop."""

    agent: AgentName
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    ticket_id: int | None = None
    chain: tuple[AgentName, ...] = ()
    budget: RunBudget = field(default_factory=RunBudget)

    @property
    def depth(self) -> int:
        return len(self.chain) - 1

    def hop(self, to: AgentName) -> "TeamDeps":
        return TeamDeps(agent=to, run_id=self.run_id, ticket_id=self.ticket_id,
                        chain=(*self.chain, to), budget=self.budget)
