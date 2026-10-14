import type { Approval, Ticket } from "../types";

const TYPE_LABEL: Record<string, string> = {
  customer_order: "Customer order",
  rent_notice: "Rent notice",
  price_override: "Price override",
};

// "2026-08-31T09:15:00-04:00" -> "08/31/26 09:15" (shop's local time, as written on the ticket)
const stamp = (iso: string) => {
  const [d, t] = iso.split("T");
  const [y, m, day] = d.split("-");
  return `${m}/${day}/${y.slice(2)} ${t?.slice(0, 5) ?? ""}`;
};

export function TicketRail({
  tickets, selected, onSelect, approvals,
}: { tickets: Ticket[]; selected: number | null; onSelect: (id: number) => void; approvals: Approval[] }) {
  return (
    <aside className="rail">
      <h2 className="section-title">Ticket spike <span>{tickets.filter((t) => !t.is_resolved).length} open</span></h2>
      <div className="rail__spike" aria-hidden />
      {tickets.map((t, i) => {
        const waiting = approvals.filter((a) => a.ticket_id === t.id).length;
        return (
          <button
            key={t.id}
            className={`stub ${selected === t.id ? "is-selected" : ""} ${t.is_resolved ? "is-resolved" : ""} ${t.agent_running ? "is-running" : ""}`}
            style={{ "--tilt": `${[-1.2, 0.8, -0.5][i % 3]}deg` } as React.CSSProperties}
            onClick={() => onSelect(t.id)}
          >
            <div className="stub__paper">
              <div className="stub__shop">Campus Customs</div>
              <div className="stub__rule" />
              <div className="stub__top">
                <span className="stub__no">#{t.id}</span>
                <span className="stub__type">{TYPE_LABEL[t.type] ?? t.type}</span>
              </div>
              <div className="stub__subject">{t.subject}</div>
              <div className="stub__who">{t.requester}</div>
              {t.sku && <div className="stub__item">{t.qty} × {t.sku} · {t.size}</div>}
              <div className="stub__rule" />
              <div className="stub__line">
                <span>Status</span>
                {/* resolved tickets get a rubber stamp in place of the status pill */}
                {t.is_resolved ? (
                  <span className="stamp stamp--stub" aria-label="Resolved">Resolved</span>
                ) : (
                  <span className={`pill pill--${t.status}`}>{t.agent_running ? "team working…" : t.status.replace(/_/g, " ")}</span>
                )}
              </div>
              <div className="stub__line">
                <span>{t.created_at ? stamp(t.created_at) : ""}</span>
                {waiting > 0 && <span className="stub__waiting">{waiting} to approve</span>}
              </div>
              <div className="stub__barcode" aria-hidden>
                <div className="stub__bars" />
                <span>{`0${t.id} ${(t.created_at ?? "").slice(5, 10).replace("-", "")} ${(t.created_at ?? "").slice(11, 16).replace(":", "")}`}</span>
              </div>
            </div>
          </button>
        );
      })}
    </aside>
  );
}
