import type { AgentEvent, Approval, Cash, Run, Ticket, TicketDetail } from "./types";

// The FastAPI backend from Problem 7.
export const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
  return body as T;
}

export const api = {
  tickets: () => req<{ shop_today: string; tickets: Ticket[] }>("/api/tickets"),
  ticket: (id: number) => req<TicketDetail>(`/api/tickets/${id}`),
  runTicket: (id: number) => req<Run>(`/api/tickets/${id}/run`, { method: "POST" }),
  run: (runId: string) => req<Run>(`/api/runs/${runId}`),
  events: (ticketId: number, limit = 400) =>
    req<{ events: AgentEvent[]; running: Run[] }>(`/api/events?ticket_id=${ticketId}&limit=${limit}`),
  approvals: () => req<{ approvals: Approval[] }>("/api/approvals?status=pending"),
  approve: (id: number, by: string) =>
    req<{ checking_balance: number; ticket_resolved: boolean }>(`/api/approvals/${id}/approve`, {
      method: "POST",
      body: JSON.stringify({ approved_by: by }),
    }),
  reject: (id: number, by: string) =>
    req<{ ticket_resolved: boolean }>(`/api/approvals/${id}/reject`, {
      method: "POST",
      body: JSON.stringify({ approved_by: by, note: "Rejected at the desk" }),
    }),
  cash: () => req<Cash>("/api/cash"),
  reset: () => req<{ ok: boolean }>("/api/reset", { method: "POST" }),
};
