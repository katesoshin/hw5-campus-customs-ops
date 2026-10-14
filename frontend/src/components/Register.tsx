import { useEffect, useRef, useState } from "react";
import { META } from "../agents";
import type { Approval, Cash } from "../types";

const fmt = (n: number) => n.toLocaleString("en-US", { style: "currency", currency: "USD" });
const KIND = { invoice: "Vendor invoice", rent: "Rent", purchase_order: "Purchase order" };

/** Animate a number toward its new value, like a register display rolling over. */
function useRolling(value: number | null, ms = 1100) {
  const [shown, setShown] = useState(value ?? 0);
  const from = useRef<number | null>(null);
  useEffect(() => {
    if (value === null) return;
    const a = from.current;
    from.current = value;
    if (a === null || a === value) { setShown(value); return; } // first load: no roll from $0
    const start = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - start) / ms);
      setShown(a + (value - a) * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [value, ms]);
  return shown;
}

export function Register({
  cash, approvals, deskName, onDeskName, onApprove, onReject, selectedTicket,
}: {
  cash: Cash | null;
  approvals: Approval[];
  deskName: string;
  onDeskName: (s: string) => void;
  onApprove: (a: Approval) => Promise<void>;
  onReject: (a: Approval) => Promise<void>;
  selectedTicket: number | null;
}) {
  const balance = useRolling(cash?.checking_balance ?? null);
  const prev = useRef<number | null>(null);
  const [drop, setDrop] = useState<{ amt: number; key: number } | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [stamped, setStamped] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (cash == null) return;
    if (prev.current != null && cash.checking_balance < prev.current) {
      setDrop({ amt: prev.current - cash.checking_balance, key: Date.now() });
    }
    prev.current = cash.checking_balance;
  }, [cash?.checking_balance]);

  const act = async (a: Approval, fn: (a: Approval) => Promise<void>, stamp: boolean) => {
    setErr(null);
    if (!deskName.trim()) { setErr("Sign the desk log first: type your name above."); return; }
    setBusy(a.id);
    try {
      if (stamp) { setStamped(a.id); await new Promise((r) => setTimeout(r, 450)); }
      await fn(a);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(null); setStamped(null);
    }
  };

  const after = cash?.balance_after_pending ?? 0;
  const pct = cash && cash.checking_balance > 0 ? Math.max(0, Math.min(100, (after / cash.checking_balance) * 100)) : 0;

  return (
    <aside className="register">
      <div className="till">
        <div className="till__label">Checking · cash_accounts</div>
        <div className="till__display" aria-live="polite">
          {fmt(balance)}
          {drop && <span className="till__drop" key={drop.key}>−{fmt(drop.amt)}</span>}
        </div>
        <div className="till__meter" title="Balance left if every pending request is approved">
          <div className="till__meter-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="till__sub">
          {cash && cash.pending_approval_total > 0
            ? <>If you approve everything pending: <b className={after < 0 ? "neg" : ""}>{fmt(after)}</b></>
            : <>No money is waiting on you. No revenue comes in.</>}
        </div>
        {cash && (
          <ul className="bills">
            {cash.obligations_next_30_days.map((o) => (
              <li key={`${o.kind}-${o.ref_id}`} className={o.days_until_due < 0 ? "overdue" : ""}>
                <span>{o.payee}</span>
                <span>{fmt(o.amount)}</span>
                <em>{o.days_until_due < 0 ? `${-o.days_until_due}d overdue` : `due in ${o.days_until_due}d`}</em>
              </li>
            ))}
          </ul>
        )}
      </div>

      <label className="signin">
        <span>At the desk</span>
        <input value={deskName} onChange={(e) => onDeskName(e.target.value)} placeholder="your name (signs approvals)" />
      </label>

      <h2 className="section-title">Approval tray <span>{approvals.length}</span></h2>
      {err && <div className="flash">{err}</div>}
      {approvals.length === 0 && <p className="empty">Nothing to sign. Agents can only <em>ask</em> for money; requests land here.</p>}
      <div className="receipts">
        {approvals.map((a) => (
          <div key={a.id} className={`receipt ${a.ticket_id === selectedTicket ? "is-here" : ""} ${stamped === a.id ? "is-stamped" : ""}`}>
            <div className="receipt__head">
              <span>REQ #{a.id}</span>
              <span>ticket #{a.ticket_id}</span>
            </div>
            <div className="receipt__kind">{KIND[a.kind]} · ref {a.ref_id}</div>
            <div className="receipt__amt">{fmt(a.amount)}</div>
            <p className="receipt__why">{a.reason}</p>
            <div className="receipt__by" style={{ color: META[a.requested_by]?.color }}>asked by {META[a.requested_by]?.label}</div>
            <div className="receipt__actions">
              <button className="btn btn--pay" disabled={busy !== null} onClick={() => act(a, onApprove, true)}>
                {busy === a.id ? "Paying…" : "Approve & pay"}
              </button>
              <button className="btn btn--ghost" disabled={busy !== null} onClick={() => act(a, onReject, false)}>Reject</button>
            </div>
            <div className="receipt__stamp">PAID</div>
          </div>
        ))}
      </div>
    </aside>
  );
}
