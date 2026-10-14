import type { AgentEvent, AgentName, AgentOutput, ToolCall } from "./types";

export interface AgentMeta {
  name: AgentName;
  label: string;
  role: string;
  color: string;
  shape: "bulldog" | "box" | "ledger" | "house" | "heart";
  // where the station sits on the floor (percent of the floor box)
  x: number;
  y: number;
}

export const AGENTS: AgentMeta[] = [
  { name: "boss", label: "Boss", role: "Handsome Dan · routes the work", color: "#c9971c", shape: "bulldog", x: 50, y: 8 },
  { name: "inventory", label: "Inventory", role: "shelves & vendors", color: "#286dc0", shape: "box", x: 15, y: 38 },
  { name: "accounting", label: "Accounting", role: "cash & margins", color: "#00356b", shape: "ledger", x: 31, y: 71 },
  { name: "facilities", label: "Facilities", role: "the lease", color: "#5b6f8c", shape: "house", x: 69, y: 71 },
  { name: "customer_service", label: "Customer Service", role: "the voice", color: "#1f8a9e", shape: "heart", x: 85, y: 38 },
];

export const META: Record<AgentName, AgentMeta> = Object.fromEntries(AGENTS.map((a) => [a.name, a])) as Record<
  AgentName,
  AgentMeta
>;

const money = (v: unknown) => (typeof v === "number" ? `$${v.toLocaleString()}` : String(v));

/** Turn a tool call into the plain-English thing the agent is doing. */
export function describeTool(c: ToolCall): string {
  const a = c.args as Record<string, any>;
  switch (c.tool) {
    case "get_ticket": return `Reading ticket #${a.ticket_id}`;
    case "list_open_tickets": return "Scanning the board";
    case "add_ticket_note": return `Pinning a note: “${String(a.note ?? "").slice(0, 90)}${String(a.note ?? "").length > 90 ? "…" : ""}”`;
    case "set_ticket_status": return `Marking #${a.ticket_id} ${String(a.status).replace(/_/g, " ")}`;
    case "check_stock": return `Checking the shelf: ${a.sku} ${a.size} × ${a.qty_needed ?? 1}`;
    case "quote_price": return `Pricing ${a.qty} × ${a.sku}${a.unit_price != null ? ` at ${money(a.unit_price)}` : ""}`;
    case "find_vendors": return `Flipping through ${a.specialty_keyword ?? "all"} vendors`;
    case "get_vendor_status": return `Ringing vendor #${a.vendor_id}`;
    case "get_invoice": return `Pulling invoice ${a.invoice_id}`;
    case "get_lease": return `Reading lease #${a.lease_id}`;
    case "get_cash_position": return "Counting the cash drawer";
    case "request_payment": return `Filing ${a.kind} payment for your approval`;
    case "create_purchase_order": return `Writing a PO: ${a.qty} × ${a.sku} ${a.size}`;
    case "list_approvals": return "Checking the approval tray";
    case "draft_message": return `Drafting a note to ${a.to_name}`;
    case "delegate": return `Handing off to ${META[a.to as AgentName]?.label ?? a.to}`;
    default: return c.tool.replace(/_/g, " ");
  }
}

export type AgentStatus = "idle" | "working" | "waiting" | "done" | "error";

export interface AgentState {
  status: AgentStatus;
  line: string | null; // what they're saying / doing right now
  tools: string[]; // every tool they used this run, in order
  runs: number;
  waitingOn: AgentName | null;
  reports: AgentOutput[];
}

export interface FloorState {
  runId: string | null;
  agents: Record<AgentName, AgentState>;
  activeEdges: { from: AgentName; to: AgentName }[];
  usedEdges: { from: AgentName; to: AgentName }[];
  finished: boolean;
  tokens: number;
}

const blank = (): AgentState => ({ status: "idle", line: null, tools: [], runs: 0, waitingOn: null, reports: [] });

/** Replay one run's events into who's doing what on the floor. */
export function buildFloor(events: AgentEvent[]): FloorState {
  const agents = Object.fromEntries(AGENTS.map((a) => [a.name, blank()])) as Record<AgentName, AgentState>;
  let active: { from: AgentName; to: AgentName }[] = [];
  const used: { from: AgentName; to: AgentName }[] = [];
  let finished = false;
  let tokens = 0;
  for (const e of events) {
    const s = agents[e.agent];
    tokens = Math.max(tokens, (e.usage.input_tokens ?? 0) + (e.usage.output_tokens ?? 0));
    if (e.event === "run_start") {
      s.status = "working";
      s.runs += 1;
      s.line = e.depth === 0 ? "Picking up the ticket" : `Got a task from ${META[e.chain[e.chain.length - 2]]?.label}`;
    } else if (e.event === "step") {
      if (e.tools.length) {
        s.line = e.tools.map(describeTool).join(" · ");
        for (const t of e.tools) if (t.tool !== "delegate") s.tools.push(t.tool);
      }
      if (e.said) s.line = e.said;
      if (s.status !== "waiting") s.status = "working";
    } else if (e.event === "delegation" && e.delegate_to) {
      s.status = "waiting";
      s.waitingOn = e.delegate_to;
      s.line = `Waiting on ${META[e.delegate_to].label}`;
      active.push({ from: e.agent, to: e.delegate_to });
      if (!used.some((u) => u.from === e.agent && u.to === e.delegate_to)) used.push({ from: e.agent, to: e.delegate_to });
    } else if (e.event === "run_end") {
      s.status = "done";
      s.waitingOn = null;
      if (e.output) s.reports.push(e.output);
      s.line = e.output?.summary ?? "Done";
      active = active.filter((x) => x.to !== e.agent);
      for (const other of Object.values(agents)) if (other.waitingOn === e.agent) { other.status = "working"; other.waitingOn = null; }
      if (e.depth === 0) finished = true;
    } else if (e.event === "run_error") {
      s.status = "error";
      s.line = e.said ?? "Something went wrong";
      active = active.filter((x) => x.to !== e.agent);
      if (e.depth === 0) finished = true;
    }
  }
  return { runId: events.at(-1)?.run_id ?? null, agents, activeEdges: active, usedEdges: used, finished, tokens };
}
