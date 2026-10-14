export type AgentName = "boss" | "inventory" | "accounting" | "facilities" | "customer_service";

export interface Ticket {
  id: number;
  type: string;
  requester: string;
  subject: string;
  sku: string | null;
  size: string | null;
  qty: number | null;
  status: string;
  notes: string | null;
  is_resolved: boolean;
  agent_running: boolean;
  created_at: string;
}

export interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
}

export interface HumanAction {
  kind: string;
  description: string;
  approval_id?: number | null;
  draft_id?: number | null;
  amount?: number | null;
}

export interface AgentOutput {
  agent?: AgentName;
  summary?: string;
  facts?: string[];
  actions_taken?: string[];
  human_actions?: HumanAction[];
  blockers?: string[];
  recommended_next_step?: string | null;
  // BossReport
  status?: string;
  delegations?: string[];
  cash_note?: string | null;
}

export interface AgentEvent {
  ts: string;
  run_id: string;
  ticket_id: number | null;
  agent: AgentName;
  event: "run_start" | "step" | "delegation" | "run_end" | "run_error";
  depth: number;
  chain: AgentName[];
  delegate_to: AgentName | null;
  said: string | null;
  tools: ToolCall[];
  output: AgentOutput | null;
  usage: { requests?: number; tool_calls?: number; input_tokens?: number; output_tokens?: number };
}

export interface Approval {
  id: number;
  kind: "invoice" | "rent" | "purchase_order";
  ref_id: number;
  amount: number;
  ticket_id: number | null;
  reason: string;
  requested_by: AgentName;
  status: string;
}

export interface Obligation {
  kind: string;
  ref_id: number;
  payee: string;
  amount: number;
  due_date: string;
  days_until_due: number;
}

export interface Cash {
  shop_today: string;
  checking_balance: number;
  pending_approval_total: number;
  balance_after_pending: number;
  obligations_next_30_days: Obligation[];
}

export interface Run {
  run_id: string;
  ticket_id: number;
  status: "running" | "done" | "error";
  result: AgentOutput | null;
  error: string | null;
  resolved?: boolean;
}

export interface Draft {
  id: number;
  to_name: string;
  subject: string;
  body: string;
  author_agent: AgentName;
  status: string;
}

export interface TicketDetail {
  ticket: Ticket;
  drafts: Draft[];
  approvals: Approval[];
}
