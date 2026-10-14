import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { buildFloor } from "./agents";
import type { AgentEvent, Approval, Cash, Draft, Ticket } from "./types";
import { TicketRail } from "./components/TicketRail";
import { Floor } from "./components/Floor";
import { Wire } from "./components/Wire";
import { Register } from "./components/Register";
import { ShiftReport } from "./components/ShiftReport";

const SHIFT_KEY = "cc-desk-shift-start"; // events before the last reset belong to an old shift
const NAME_KEY = "cc-desk-name";

export default function App() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [shopToday, setShopToday] = useState("");
  const [cash, setCash] = useState<Cash | null>(null);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [tab, setTab] = useState<"wire" | "report">("wire");
  const [offline, setOffline] = useState(false);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [deskName, setDeskName] = useState(() => localStorage.getItem(NAME_KEY) ?? "");
  const [shiftStart, setShiftStart] = useState(() => localStorage.getItem(SHIFT_KEY) ?? "");
  const watching = useRef(false);

  const ticket = tickets.find((t) => t.id === selected) ?? null;
  const anyRunning = tickets.some((t) => t.agent_running);

  const refreshBoard = useCallback(async () => {
    try {
      const [t, c, a] = await Promise.all([api.tickets(), api.cash(), api.approvals()]);
      setTickets(t.tickets);
      setShopToday(t.shop_today);
      setCash(c);
      setApprovals(a.approvals);
      setOffline(false);
      setSelected((s) => s ?? t.tickets.find((x) => !x.is_resolved)?.id ?? t.tickets[0]?.id ?? null);
    } catch {
      setOffline(true);
    }
  }, []);

  const refreshTicket = useCallback(async (id: number) => {
    try {
      const [ev, detail] = await Promise.all([api.events(id), api.ticket(id)]);
      const fresh = ev.events.filter((e) => !shiftStart || e.ts > shiftStart);
      const lastRun = fresh.at(-1)?.run_id;
      setEvents(lastRun ? fresh.filter((e) => e.run_id === lastRun) : []);
      setDrafts(detail.drafts);
    } catch {
      setOffline(true);
    }
  }, [shiftStart]);

  // Board: tickets, cash, approvals. Faster while the team is working.
  useEffect(() => {
    refreshBoard();
    const id = setInterval(refreshBoard, anyRunning ? 1500 : 4000);
    return () => clearInterval(id);
  }, [refreshBoard, anyRunning]);

  // The selected ticket's run, polled live while it's being worked.
  useEffect(() => {
    if (selected == null) return;
    refreshTicket(selected);
    if (!ticket?.agent_running) return;
    const id = setInterval(() => refreshTicket(selected), 1200);
    return () => clearInterval(id);
  }, [selected, ticket?.agent_running, refreshTicket]);

  const floor = useMemo(() => buildFloor(events), [events]);
  const bossReport = useMemo(() => events.find((e) => e.event === "run_end" && e.depth === 0)?.output ?? null, [events]);

  // When a run we were watching finishes, flip to the shift report.
  useEffect(() => {
    if (ticket?.agent_running) watching.current = true;
    else if (watching.current && floor.finished) {
      watching.current = false;
      setTab("report");
      refreshBoard();
      if (selected != null) refreshTicket(selected);
    }
  }, [ticket?.agent_running, floor.finished, refreshBoard, refreshTicket, selected]);

  const select = (id: number) => {
    setTab("wire");
    if (id === selected) { refreshTicket(id); return; } // re-clicking the open ticket just refreshes it
    setSelected(id);
    setEvents([]);
  };

  const start = async () => {
    if (!ticket) return;
    setStarting(true);
    setNotice(null);
    try {
      await api.runTicket(ticket.id);
      watching.current = true;
      setTab("wire");
      await refreshBoard();
      await refreshTicket(ticket.id);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setStarting(false);
    }
  };

  const approve = async (a: Approval) => {
    const r = await api.approve(a.id, deskName.trim());
    setNotice(r.ticket_resolved ? `Paid. Ticket #${a.ticket_id} is resolved.` : `Paid. Checking is now $${r.checking_balance.toLocaleString()}.`);
    await refreshBoard();
  };
  const reject = async (a: Approval) => {
    const r = await api.reject(a.id, deskName.trim());
    setNotice(r.ticket_resolved ? `Rejected. Ticket #${a.ticket_id} is resolved.` : `Request #${a.id} rejected. Nothing was paid.`);
    await refreshBoard();
  };

  const reset = async () => {
    if (!confirm("Start a fresh shift? This resets the shop database to its original values. The audit trail is kept.")) return;
    try {
      await api.reset();
      const now = new Date().toISOString();
      localStorage.setItem(SHIFT_KEY, now);
      setShiftStart(now);
      setEvents([]); setDrafts([]); setTab("wire");
      setNotice("Fresh shift. Database reset to the original values.");
      await refreshBoard();
    } catch (e) {
      setNotice((e as Error).message);
    }
  };

  const onDeskName = (s: string) => { setDeskName(s); localStorage.setItem(NAME_KEY, s); };
  const working = Object.values(floor.agents).filter((a) => a.status === "working" || a.status === "waiting").length;

  return (
    <div className="desk">
      <header className="topbar">
        <div className="brand">
          <span className="brand__mark">Campus Customs</span>
          <span className="brand__sub">back office · Chapel Street shop</span>
        </div>
        <div className="topbar__mid">
          {shopToday && (
            <div className="calendar" title="The shop's date (desk.date_today)">
              <span>{new Date(shopToday + "T12:00").toLocaleString("en-US", { month: "short" })}</span>
              <b>{new Date(shopToday + "T12:00").getDate()}</b>
            </div>
          )}
          <div className={`onair ${anyRunning ? "is-live" : ""}`}>
            <i /> {anyRunning ? `team on shift · ${working} at work` : "floor is quiet"}
          </div>
        </div>
        <button className="btn btn--ghost" onClick={reset} disabled={anyRunning}>↺ Fresh shift</button>
      </header>

      {offline && (
        <div className="offline">
          Can't reach the backend at <code>http://localhost:8000</code>. Start it from <code>hw5/backend</code> with{" "}
          <code>uvicorn main:app --reload --port 8000</code>.
        </div>
      )}
      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}

      <div className="layout">
        <TicketRail tickets={tickets} selected={selected} onSelect={select} approvals={approvals} />

        <main className="center">
          {ticket && (
            <section className={`case ${ticket.is_resolved ? "is-resolved" : ""}`}>
              <div className="case__info">
                <div className="case__no">#{ticket.id}</div>
                <div>
                  <h1>{ticket.subject}</h1>
                  <p>{ticket.requester} · {ticket.notes?.split("\n")[0]}</p>
                </div>
              </div>
              <div className="case__go">
                {ticket.is_resolved ? (
                  <div className="resolved-badge resolved-badge--big">Resolved</div>
                ) : (
                  <button className="btn btn--go" onClick={start} disabled={starting || ticket.agent_running}>
                    {ticket.agent_running ? <>Team on it<span className="dots" /></> : starting ? "Calling the team…" : "Send to the team →"}
                  </button>
                )}
                {floor.tokens > 0 && <small>{floor.tokens.toLocaleString()} tokens this run</small>}
              </div>
            </section>
          )}

          <Floor floor={floor} />

          <div className="tabs" role="tablist">
            <button role="tab" aria-selected={tab === "wire"} onClick={() => setTab("wire")}>Live wire</button>
            <button role="tab" aria-selected={tab === "report"} onClick={() => setTab("report")}>Shift report</button>
          </div>
          <section className="panel" key={tab}>
            {tab === "wire" ? <Wire events={events} /> : <ShiftReport floor={floor} boss={bossReport} drafts={drafts} />}
          </section>
        </main>

        <Register
          cash={cash}
          approvals={approvals}
          deskName={deskName}
          onDeskName={onDeskName}
          onApprove={approve}
          onReject={reject}
          selectedTicket={selected}
        />
      </div>
    </div>
  );
}
