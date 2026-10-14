"""Campus Customs MCP server — the shared toolbox for every agent on the team.

Reads and writes the working copy data/campus_customs_new.db only; the original
data/campus_customs.db is never touched. Every value returned comes straight from the
database — no tool makes up stock, prices, dates, or amounts.

Money rules live here, not in the agents:
  * Agents can only *request* a payment or purchase order. Nothing moves cash until a human
    calls approve_and_pay (a human-only tool the agent team is never given).
  * Amounts are always read from the database, never taken from the caller.
  * approve_and_pay refuses anything that would push the cash balance below zero.
  * There is no send tool. Customer and vendor messages are saved as drafts on the board.

Run as an MCP server (stdio):   python mcp_server/server.py
"""

from __future__ import annotations

import calendar
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP

HW5_DIR = Path(__file__).resolve().parent.parent
DB_PATH = HW5_DIR / "data" / "campus_customs_new.db"

# Tools only a human (via the backend / dashboard) may call. The agent team filters these out.
HUMAN_ONLY_TOOLS = frozenset({"approve_and_pay", "reject_approval", "close_ticket"})
AGENT_NAMES = frozenset({"boss", "inventory", "accounting", "facilities", "customer_service"})
TICKET_STATUSES = ("open", "in_progress", "waiting_on_human", "blocked", "resolved")

mcp = FastMCP("campus-customs")

# Board tables the original database doesn't have. Created on first connect, so a reset
# (copying the original over the working copy) starts with them empty again.
_BOARD_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id),
    to_name TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    author_agent TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS purchase_orders (
    id INTEGER PRIMARY KEY,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    sku TEXT NOT NULL,
    size TEXT NOT NULL,
    qty INTEGER NOT NULL,
    unit_cost REAL NOT NULL,
    total REAL NOT NULL,
    ticket_id INTEGER REFERENCES tickets(id),
    status TEXT NOT NULL,
    eta_date TEXT,
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    ticket_id INTEGER REFERENCES tickets(id),
    reason TEXT NOT NULL,
    requested_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    decided_by TEXT,
    decided_at TEXT,
    decision_note TEXT,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"Working copy not found at {DB_PATH}. "
            "Run: cp data/campus_customs.db data/campus_customs_new.db"
        )
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_BOARD_SCHEMA)
    return conn


def _shop_today(conn: sqlite3.Connection) -> str:
    """The shop's 'today' is desk.date_today, not the real clock."""
    return conn.execute("SELECT date_today FROM desk LIMIT 1").fetchone()["date_today"]


def _days_between(start: str, end: str) -> int:
    return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _add_month(day: str) -> str:
    d = date.fromisoformat(day[:10])
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return d.replace(year=year, month=month, day=min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def _balance(conn: sqlite3.Connection, account: str = "checking") -> float:
    row = conn.execute("SELECT balance FROM cash_accounts WHERE name = ?", (account,)).fetchone()
    return row["balance"] if row else 0.0


def _pending_total(conn: sqlite3.Connection) -> float:
    return conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS t FROM approvals WHERE status = 'pending'"
    ).fetchone()["t"]


def _ticket_exists(conn: sqlite3.Connection, ticket_id: int) -> bool:
    return conn.execute("SELECT 1 FROM tickets WHERE id = ?", (ticket_id,)).fetchone() is not None


def _check_agent(name: str) -> str | None:
    return None if name in AGENT_NAMES else f"Unknown agent '{name}'. Use one of: {sorted(AGENT_NAMES)}."


# --------------------------------------------------------------------------- tickets

@mcp.tool
def list_open_tickets() -> dict:
    """List every ticket on the board that is not resolved, plus the shop's date (desk.date_today)."""
    with _connect() as conn:
        today = _shop_today(conn)
        rows = conn.execute(
            "SELECT id, type, requester, subject, status, created_at FROM tickets "
            "WHERE status != 'resolved' ORDER BY id"
        ).fetchall()
    return {"shop_today": today, "tickets": [dict(r) for r in rows]}


@mcp.tool
def list_tickets() -> dict:
    """List every ticket on the board, resolved or not, with its status (for the dashboard)."""
    with _connect() as conn:
        today = _shop_today(conn)
        rows = conn.execute(
            "SELECT id, type, requester, subject, sku, size, qty, lease_id, invoice_id, status, notes, created_at "
            "FROM tickets ORDER BY id"
        ).fetchall()
    return {"shop_today": today, "tickets": [dict(r) for r in rows]}


@mcp.tool
def get_ticket(ticket_id: int) -> dict:
    """Get one ticket with all its fields and links (sku/size/qty, lease_id, invoice_id), plus
    the drafts, approval requests, and purchase orders already attached to it."""
    with _connect() as conn:
        t = conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"found": False, "error": f"Ticket {ticket_id} does not exist."}
        drafts = conn.execute(
            "SELECT id, to_name, subject, body, author_agent, status, created_at FROM drafts WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchall()
        approvals = conn.execute(
            "SELECT id, kind, ref_id, amount, status, requested_by FROM approvals WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchall()
        pos = conn.execute(
            "SELECT id, vendor_id, sku, size, qty, total, status FROM purchase_orders WHERE ticket_id = ?",
            (ticket_id,),
        ).fetchall()
        today = _shop_today(conn)
    return {
        "found": True,
        "shop_today": today,
        "ticket": dict(t),
        "drafts": [dict(r) for r in drafts],
        "approvals": [dict(r) for r in approvals],
        "purchase_orders": [dict(r) for r in pos],
    }


@mcp.tool
def add_ticket_note(ticket_id: int, agent: str, note: str) -> dict:
    """Append a dated note to a ticket's notes so the team (and humans) can see what was found or done.
    Existing notes are kept; the new line is added at the end."""
    if err := _check_agent(agent):
        return {"ok": False, "error": err}
    note = note.strip()
    if not note:
        return {"ok": False, "error": "Note is empty."}
    with _connect() as conn:
        t = conn.execute("SELECT notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"ok": False, "error": f"Ticket {ticket_id} does not exist."}
        line = f"[{_shop_today(conn)} {agent}] {note[:600]}"
        notes = f"{t['notes']}\n{line}" if t["notes"] else line
        conn.execute("UPDATE tickets SET notes = ? WHERE id = ?", (notes, ticket_id))
    return {"ok": True, "ticket_id": ticket_id, "added": line}


@mcp.tool
def set_ticket_status(
    ticket_id: int,
    status: Literal["open", "in_progress", "waiting_on_human", "blocked", "resolved"],
    agent: str,
    reason: str,
) -> dict:
    """Move a ticket to a new status and record why in the ticket notes.
    Statuses: open, in_progress, waiting_on_human (needs an approval or a human reply),
    blocked (cannot move until something outside the team changes), resolved."""
    if err := _check_agent(agent):
        return {"ok": False, "error": err}
    with _connect() as conn:
        t = conn.execute("SELECT status, notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"ok": False, "error": f"Ticket {ticket_id} does not exist."}
        if status == "resolved":
            pending = conn.execute(
                "SELECT COUNT(*) AS n FROM approvals WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
            ).fetchone()["n"]
            if pending:
                return {"ok": False, "error": f"Ticket {ticket_id} still has {pending} pending approval(s)."}
        line = f"[{_shop_today(conn)} {agent}] status {t['status']} -> {status}: {reason.strip()[:300]}"
        notes = f"{t['notes']}\n{line}" if t["notes"] else line
        conn.execute("UPDATE tickets SET status = ?, notes = ? WHERE id = ?", (status, notes, ticket_id))
    return {"ok": True, "ticket_id": ticket_id, "old_status": t["status"], "new_status": status}


# --------------------------------------------------------------------------- inventory & pricing

@mcp.tool
def check_stock(sku: str, size: str, qty_needed: int = 1) -> dict:
    """Check how many of a SKU in a given size are on hand, and whether that covers qty_needed.

    Returns the on-hand quantity, shelf location, and the shortfall (0 if there is enough).
    """
    with _connect() as conn:
        row = conn.execute(
            "SELECT sku, name, size, qty, location FROM inventory WHERE sku = ? AND size = ?",
            (sku, size),
        ).fetchone()
        if row is None:
            sizes = [
                r["size"]
                for r in conn.execute("SELECT size FROM inventory WHERE sku = ?", (sku,))
            ]
            if sizes:
                return {"found": False, "error": f"No size {size} for {sku}.", "sizes_carried": sizes}
            return {"found": False, "error": f"SKU {sku} is not in inventory."}

    on_hand = row["qty"]
    shortfall = max(qty_needed - on_hand, 0)
    return {
        "found": True,
        "sku": row["sku"],
        "name": row["name"],
        "size": row["size"],
        "location": row["location"],
        "on_hand": on_hand,
        "qty_needed": qty_needed,
        "enough_stock": shortfall == 0,
        "shortfall": shortfall,
    }


@mcp.tool
def quote_price(sku: str, qty: int, unit_price: float | None = None) -> dict:
    """Price an order from the pricing table: unit cost, list price, and the margin at unit_price
    (defaults to list price). Shows the discount off list and flags any price at or below cost."""
    if qty <= 0:
        return {"found": False, "error": "qty must be at least 1."}
    with _connect() as conn:
        p = conn.execute("SELECT sku, unit_cost, list_price FROM pricing WHERE sku = ?", (sku,)).fetchone()
    if p is None:
        return {"found": False, "error": f"SKU {sku} has no pricing row."}
    price = p["list_price"] if unit_price is None else round(unit_price, 2)
    margin = round(price - p["unit_cost"], 2)
    return {
        "found": True,
        "sku": sku,
        "qty": qty,
        "unit_cost": p["unit_cost"],
        "list_price": p["list_price"],
        "unit_price": price,
        "discount_pct_off_list": round((1 - price / p["list_price"]) * 100, 1),
        "unit_margin": margin,
        "margin_pct_of_price": round(margin / price * 100, 1) if price else None,
        "order_revenue": round(price * qty, 2),
        "order_cost": round(p["unit_cost"] * qty, 2),
        "order_margin": round(margin * qty, 2),
        "at_or_below_cost": price <= p["unit_cost"],
    }


# --------------------------------------------------------------------------- vendors & invoices

@mcp.tool
def find_vendors(specialty_keyword: str | None = None) -> dict:
    """List vendors (optionally only those whose specialty contains the keyword, e.g. 'apparel'
    or 'mugs'), with lead time and whether each will ship right now (no open invoices)."""
    with _connect() as conn:
        sql = "SELECT id, name, specialty, lead_days FROM vendors"
        args: tuple = ()
        if specialty_keyword:
            sql += " WHERE specialty LIKE ?"
            args = (f"%{specialty_keyword}%",)
        vendors = conn.execute(sql + " ORDER BY id", args).fetchall()
        result = []
        for v in vendors:
            open_amt = conn.execute(
                "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS amt FROM invoices "
                "WHERE vendor_id = ? AND status = 'open'",
                (v["id"],),
            ).fetchone()
            result.append({**dict(v), "open_invoices": open_amt["n"], "open_amount": open_amt["amt"],
                           "will_ship": open_amt["n"] == 0})
    return {"vendors": result}


@mcp.tool
def get_vendor_status(vendor_id: int) -> dict:
    """Look up a vendor's lead time and unpaid invoices, and whether they will ship new product.

    A vendor will not ship while it has any open (unpaid) invoice. Overdue is judged against
    the shop's desk.date_today.
    """
    with _connect() as conn:
        vendor = conn.execute(
            "SELECT id, name, specialty, lead_days FROM vendors WHERE id = ?", (vendor_id,)
        ).fetchone()
        if vendor is None:
            return {"found": False, "error": f"Vendor {vendor_id} does not exist."}
        today = _shop_today(conn)
        invoices = conn.execute(
            "SELECT id, amount, due_date, status, description FROM invoices "
            "WHERE vendor_id = ? AND status = 'open' ORDER BY due_date",
            (vendor_id,),
        ).fetchall()

    open_invoices = [
        {
            "invoice_id": inv["id"],
            "amount": inv["amount"],
            "due_date": inv["due_date"],
            "description": inv["description"],
            "overdue": inv["due_date"] < today,
            "days_overdue": max(_days_between(inv["due_date"], today), 0),
        }
        for inv in invoices
    ]
    return {
        "found": True,
        "vendor_id": vendor["id"],
        "name": vendor["name"],
        "specialty": vendor["specialty"],
        "lead_days": vendor["lead_days"],
        "shop_today": today,
        "open_invoices": open_invoices,
        "total_open_amount": sum(inv["amount"] for inv in open_invoices),
        "will_ship": not open_invoices,
    }


@mcp.tool
def get_invoice(invoice_id: int) -> dict:
    """Look up one vendor invoice: vendor, amount, due date, status, and days overdue vs desk.date_today."""
    with _connect() as conn:
        inv = conn.execute(
            "SELECT i.*, v.name AS vendor_name FROM invoices i JOIN vendors v ON v.id = i.vendor_id "
            "WHERE i.id = ?",
            (invoice_id,),
        ).fetchone()
        if inv is None:
            return {"found": False, "error": f"Invoice {invoice_id} does not exist."}
        today = _shop_today(conn)
    days = _days_between(inv["due_date"], today)
    return {
        "found": True,
        "invoice_id": inv["id"],
        "vendor_id": inv["vendor_id"],
        "vendor_name": inv["vendor_name"],
        "amount": inv["amount"],
        "due_date": inv["due_date"],
        "status": inv["status"],
        "description": inv["description"],
        "shop_today": today,
        "overdue": inv["status"] == "open" and days > 0,
        "days_overdue": max(days, 0) if inv["status"] == "open" else 0,
    }


# --------------------------------------------------------------------------- facilities

@mcp.tool
def get_lease(lease_id: int) -> dict:
    """Look up a shop lease: landlord, monthly rent, next due date, and days until rent is due.

    Days are counted from the shop's desk.date_today; a negative number means rent is overdue.
    """
    with _connect() as conn:
        lease = conn.execute(
            "SELECT id, space_name, landlord, monthly_rent, next_due, notes FROM leases WHERE id = ?",
            (lease_id,),
        ).fetchone()
        if lease is None:
            return {"found": False, "error": f"Lease {lease_id} does not exist."}
        today = _shop_today(conn)

    days_until_due = _days_between(today, lease["next_due"])
    return {
        "found": True,
        "lease_id": lease["id"],
        "space_name": lease["space_name"],
        "landlord": lease["landlord"],
        "monthly_rent": lease["monthly_rent"],
        "next_due": lease["next_due"],
        "shop_today": today,
        "days_until_due": days_until_due,
        "overdue": days_until_due < 0,
        "notes": lease["notes"],
    }


# --------------------------------------------------------------------------- cash & approvals

@mcp.tool
def get_cash_position() -> dict:
    """The shop's cash: account balances, every bill it owes (open invoices and rent due in the next
    30 days), payments waiting for human approval, and what is left after those. There is no revenue."""
    with _connect() as conn:
        today = _shop_today(conn)
        accounts = [dict(r) for r in conn.execute("SELECT name, balance, date FROM cash_accounts")]
        invoices = conn.execute(
            "SELECT i.id, v.name AS vendor, i.amount, i.due_date FROM invoices i "
            "JOIN vendors v ON v.id = i.vendor_id WHERE i.status = 'open' ORDER BY i.due_date"
        ).fetchall()
        leases = conn.execute("SELECT id, landlord, monthly_rent, next_due FROM leases").fetchall()
        pending = [dict(r) for r in conn.execute(
            "SELECT id, kind, ref_id, amount, ticket_id, requested_by FROM approvals WHERE status = 'pending'"
        )]
        balance = _balance(conn)
    obligations = [
        {"kind": "invoice", "ref_id": i["id"], "payee": i["vendor"], "amount": i["amount"],
         "due_date": i["due_date"], "days_until_due": _days_between(today, i["due_date"])}
        for i in invoices
    ] + [
        {"kind": "rent", "ref_id": l["id"], "payee": l["landlord"], "amount": l["monthly_rent"],
         "due_date": l["next_due"], "days_until_due": _days_between(today, l["next_due"])}
        for l in leases if _days_between(today, l["next_due"]) <= 30
    ]
    obligations.sort(key=lambda o: o["due_date"])
    owed = sum(o["amount"] for o in obligations)
    pending_total = sum(p["amount"] for p in pending)
    return {
        "shop_today": today,
        "accounts": accounts,
        "checking_balance": balance,
        "obligations_next_30_days": obligations,
        "total_owed_next_30_days": owed,
        "pending_approvals": pending,
        "pending_approval_total": pending_total,
        "balance_after_pending": round(balance - pending_total, 2),
        "balance_after_all_obligations": round(balance - owed, 2),
    }


@mcp.tool
def request_payment(
    kind: Literal["invoice", "rent"], ref_id: int, ticket_id: int, requested_by: str, reason: str
) -> dict:
    """Ask a human to approve paying a vendor invoice (ref_id = invoice id) or a lease's rent
    (ref_id = lease id). The amount is read from the database. This does NOT pay anything — it
    files a pending approval that a human must approve on the dashboard."""
    if err := _check_agent(requested_by):
        return {"ok": False, "error": err}
    with _connect() as conn:
        if not _ticket_exists(conn, ticket_id):
            return {"ok": False, "error": f"Ticket {ticket_id} does not exist."}
        if kind == "invoice":
            row = conn.execute("SELECT amount, status FROM invoices WHERE id = ?", (ref_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"Invoice {ref_id} does not exist."}
            if row["status"] != "open":
                return {"ok": False, "error": f"Invoice {ref_id} is already {row['status']}."}
            amount = row["amount"]
        else:
            row = conn.execute("SELECT monthly_rent FROM leases WHERE id = ?", (ref_id,)).fetchone()
            if row is None:
                return {"ok": False, "error": f"Lease {ref_id} does not exist."}
            amount = row["monthly_rent"]
        dup = conn.execute(
            "SELECT id FROM approvals WHERE kind = ? AND ref_id = ? AND status = 'pending'", (kind, ref_id)
        ).fetchone()
        if dup:
            return {"ok": False, "error": f"Approval #{dup['id']} for this {kind} is already pending."}
        balance = _balance(conn)
        if amount > balance:
            return {"ok": False, "error": f"${amount:,.2f} is more than the ${balance:,.2f} in checking."}
        after_pending = balance - _pending_total(conn) - amount
        cur = conn.execute(
            "INSERT INTO approvals (kind, ref_id, amount, ticket_id, reason, requested_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, ref_id, amount, ticket_id, reason.strip()[:500], requested_by, _now()),
        )
    return {
        "ok": True,
        "approval_id": cur.lastrowid,
        "kind": kind,
        "ref_id": ref_id,
        "amount": amount,
        "status": "pending",
        "checking_balance": balance,
        "balance_if_all_pending_paid": round(after_pending, 2),
        "warning": None if after_pending >= 0 else "Pending approvals together exceed checking; a human must choose.",
    }


@mcp.tool
def create_purchase_order(
    vendor_id: int, sku: str, size: str, qty: int, ticket_id: int, requested_by: str
) -> dict:
    """Draft a restock purchase order at the pricing table's unit cost and file it for human approval.
    Refuses if the vendor still has an open invoice (they won't ship) or the SKU/size isn't carried.
    Nothing is ordered or paid until a human approves it."""
    if err := _check_agent(requested_by):
        return {"ok": False, "error": err}
    if qty <= 0:
        return {"ok": False, "error": "qty must be at least 1."}
    with _connect() as conn:
        if not _ticket_exists(conn, ticket_id):
            return {"ok": False, "error": f"Ticket {ticket_id} does not exist."}
        vendor = conn.execute("SELECT name, lead_days FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if vendor is None:
            return {"ok": False, "error": f"Vendor {vendor_id} does not exist."}
        if conn.execute("SELECT 1 FROM inventory WHERE sku = ? AND size = ?", (sku, size)).fetchone() is None:
            return {"ok": False, "error": f"{sku} size {size} is not a carried item."}
        open_inv = conn.execute(
            "SELECT id, amount FROM invoices WHERE vendor_id = ? AND status = 'open'", (vendor_id,)
        ).fetchall()
        if open_inv:
            ids = ", ".join(str(i["id"]) for i in open_inv)
            return {"ok": False, "error": f"{vendor['name']} won't ship: open invoice(s) {ids} must be paid first."}
        cost = conn.execute("SELECT unit_cost FROM pricing WHERE sku = ?", (sku,)).fetchone()
        if cost is None:
            return {"ok": False, "error": f"SKU {sku} has no pricing row."}
        total = round(cost["unit_cost"] * qty, 2)
        balance = _balance(conn)
        if total > balance:
            return {"ok": False, "error": f"PO total ${total:,.2f} is more than the ${balance:,.2f} in checking."}
        po = conn.execute(
            "INSERT INTO purchase_orders (vendor_id, sku, size, qty, unit_cost, total, ticket_id, status, "
            "created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?)",
            (vendor_id, sku, size, qty, cost["unit_cost"], total, ticket_id, requested_by, _now()),
        )
        appr = conn.execute(
            "INSERT INTO approvals (kind, ref_id, amount, ticket_id, reason, requested_by, created_at) "
            "VALUES ('purchase_order', ?, ?, ?, ?, ?, ?)",
            (po.lastrowid, total, ticket_id,
             f"Restock {qty} x {sku} {size} from {vendor['name']}", requested_by, _now()),
        )
        after_pending = balance - _pending_total(conn)
    return {
        "ok": True,
        "purchase_order_id": po.lastrowid,
        "approval_id": appr.lastrowid,
        "vendor": vendor["name"],
        "lead_days": vendor["lead_days"],
        "unit_cost": cost["unit_cost"],
        "total": total,
        "status": "pending_approval",
        "balance_if_all_pending_paid": round(after_pending, 2),
    }


@mcp.tool
def list_approvals(status: Literal["pending", "paid", "rejected", "all"] = "pending") -> dict:
    """List payment / purchase-order approval requests by status."""
    with _connect() as conn:
        sql = "SELECT * FROM approvals"
        rows = conn.execute(sql + " ORDER BY id" if status == "all" else sql + " WHERE status = ? ORDER BY id",
                            () if status == "all" else (status,)).fetchall()
    return {"approvals": [dict(r) for r in rows]}


@mcp.tool
def approve_and_pay(approval_id: int, approved_by: str) -> dict:
    """HUMAN ONLY. Approve a pending request and pay it from checking: records the payment, lowers the
    balance, and marks the invoice paid / moves rent's next due date a month / approves the PO.
    Refuses if checking would go below zero."""
    approved_by = approved_by.strip()
    if not approved_by or approved_by.lower() in AGENT_NAMES:
        return {"ok": False, "error": "Payments must be approved by a named human, not an agent."}
    with _connect() as conn:
        a = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if a is None:
            return {"ok": False, "error": f"Approval {approval_id} does not exist."}
        if a["status"] != "pending":
            return {"ok": False, "error": f"Approval {approval_id} is already {a['status']}."}
        balance = _balance(conn)
        if a["amount"] > balance:
            return {"ok": False, "error": f"Refused: ${a['amount']:,.2f} would overdraw checking (${balance:,.2f})."}
        today = _shop_today(conn)
        result: dict = {}
        if a["kind"] == "invoice":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE id = ?", (a["ref_id"],))
        elif a["kind"] == "rent":
            nxt = conn.execute("SELECT next_due FROM leases WHERE id = ?", (a["ref_id"],)).fetchone()["next_due"]
            result["lease_next_due"] = _add_month(nxt)
            conn.execute("UPDATE leases SET next_due = ? WHERE id = ?", (result["lease_next_due"], a["ref_id"]))
        else:
            lead = conn.execute(
                "SELECT v.lead_days FROM purchase_orders p JOIN vendors v ON v.id = p.vendor_id WHERE p.id = ?",
                (a["ref_id"],),
            ).fetchone()["lead_days"]
            result["eta_date"] = (date.fromisoformat(today) + timedelta(days=lead)).isoformat()
            conn.execute("UPDATE purchase_orders SET status = 'approved', eta_date = ? WHERE id = ?",
                         (result["eta_date"], a["ref_id"]))
        new_balance = round(balance - a["amount"], 2)
        conn.execute("UPDATE cash_accounts SET balance = ?, date = ? WHERE name = 'checking'", (new_balance, today))
        pay = conn.execute(
            "INSERT INTO payments (kind, ref_id, amount, account, paid_at, approved_by) "
            "VALUES (?, ?, ?, 'checking', ?, ?)",
            (a["kind"], a["ref_id"], a["amount"], today, approved_by),
        )
        conn.execute("UPDATE approvals SET status = 'paid', decided_by = ?, decided_at = ? WHERE id = ?",
                     (approved_by, _now(), approval_id))
    return {"ok": True, "approval_id": approval_id, "payment_id": pay.lastrowid, "kind": a["kind"],
            "amount": a["amount"], "checking_balance": new_balance, **result}


@mcp.tool
def reject_approval(approval_id: int, decided_by: str, note: str = "") -> dict:
    """HUMAN ONLY. Reject a pending payment / purchase-order request. Nothing is paid."""
    decided_by = decided_by.strip()
    if not decided_by or decided_by.lower() in AGENT_NAMES:
        return {"ok": False, "error": "Rejections must come from a named human, not an agent."}
    with _connect() as conn:
        a = conn.execute("SELECT kind, ref_id, status FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if a is None:
            return {"ok": False, "error": f"Approval {approval_id} does not exist."}
        if a["status"] != "pending":
            return {"ok": False, "error": f"Approval {approval_id} is already {a['status']}."}
        conn.execute(
            "UPDATE approvals SET status = 'rejected', decided_by = ?, decided_at = ?, decision_note = ? WHERE id = ?",
            (decided_by, _now(), note.strip()[:300], approval_id),
        )
        if a["kind"] == "purchase_order":
            conn.execute("UPDATE purchase_orders SET status = 'rejected' WHERE id = ?", (a["ref_id"],))
    return {"ok": True, "approval_id": approval_id, "status": "rejected"}


@mcp.tool
def close_ticket(ticket_id: int, closed_by: str, note: str = "") -> dict:
    """HUMAN / DESK ONLY. Mark a ticket resolved once the team's run is finished and nothing is waiting
    on approval. Refuses while the ticket has pending approvals."""
    closed_by = closed_by.strip()
    if not closed_by or closed_by.lower() in AGENT_NAMES:
        return {"ok": False, "error": "Tickets are closed by the desk or a named human, not an agent."}
    with _connect() as conn:
        t = conn.execute("SELECT status, notes FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if t is None:
            return {"ok": False, "error": f"Ticket {ticket_id} does not exist."}
        pending = conn.execute(
            "SELECT COUNT(*) AS n FROM approvals WHERE ticket_id = ? AND status = 'pending'", (ticket_id,)
        ).fetchone()["n"]
        if pending:
            return {"ok": False, "error": f"Ticket {ticket_id} still has {pending} pending approval(s)."}
        if t["status"] == "resolved":
            return {"ok": True, "ticket_id": ticket_id, "status": "resolved", "changed": False}
        line = f"[{_shop_today(conn)} {closed_by}] status {t['status']} -> resolved: {note.strip()[:300] or 'closed'}"
        notes = f"{t['notes']}\n{line}" if t["notes"] else line
        conn.execute("UPDATE tickets SET status = 'resolved', notes = ? WHERE id = ?", (notes, ticket_id))
    return {"ok": True, "ticket_id": ticket_id, "status": "resolved", "changed": True}


# --------------------------------------------------------------------------- customer & vendor messages

@mcp.tool
def draft_message(ticket_id: int, to_name: str, subject: str, body: str, author_agent: str) -> dict:
    """Save a draft email/reply to a customer, landlord, or vendor on the ticket. Drafts are NEVER
    sent by the system — a human reviews and sends them. Use for every outbound message."""
    if err := _check_agent(author_agent):
        return {"ok": False, "error": err}
    if not body.strip() or not to_name.strip():
        return {"ok": False, "error": "A draft needs a recipient and a body."}
    with _connect() as conn:
        if not _ticket_exists(conn, ticket_id):
            return {"ok": False, "error": f"Ticket {ticket_id} does not exist."}
        cur = conn.execute(
            "INSERT INTO drafts (ticket_id, to_name, subject, body, author_agent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticket_id, to_name.strip(), subject.strip()[:200], body.strip()[:4000], author_agent, _now()),
        )
    return {"ok": True, "draft_id": cur.lastrowid, "ticket_id": ticket_id, "status": "draft", "sent": False}


if __name__ == "__main__":
    mcp.run()
