# Campus Customs Multi-Agent Operations — Harness

The full reference for Campus Customs Multi-Agent Operations: the data the agents see, the MCP
tools they use, the five agents, the backend API, the dashboard, and the safety rules around real
customers and real money.

**Contents:** Data · Tables · How the tickets link · MCP tools · Agent team · All MCP tools · Safety ·
Backend routes · Dashboard · Full run results (Problem 9)

**Run it** (two terminals, course `.venv` active):

```bash
cd hw5/backend && uvicorn main:app --reload --port 8000     # API + agent team (talks to the MCP server)
cd hw5/frontend && npm run dev                               # dashboard at http://localhost:5173
```

Fresh start: the dashboard's **Fresh shift** button (or `POST /api/reset`) copies the original database
over the working copy. The audit trail is never cleared.

---

## Data

- **Original:** `data/campus_customs.db` — never modified; the reset point.
- **Working copy:** `data/campus_customs_new.db` — the MCP server and backend read and write
  this file only.
- **Reset before a full run:** `cp data/campus_customs.db data/campus_customs_new.db`

## Tables

### `desk`
Fields: `date_today` (TEXT), `notes` (TEXT)

Why it matters: `date_today` is "today" for the shop (2026-08-31), so every agent uses it, not
the real clock, to decide what is due or overdue.

### `tickets`
Fields: `id` (PK), `type`, `requester`, `subject`, `sku`, `size`, `qty`, `lease_id`
(→ `leases.id`), `invoice_id` (→ `invoices.id`), `status`, `notes`, `created_at`

Why it matters: the work queue on the board. Boss reads each ticket and routes it, and the
optional `sku`/`size`/`lease_id`/`invoice_id` links tell the team which other tables to check.

### `inventory`
Fields: `sku`, `name`, `size`, `qty`, `location` (PK = `sku` + `size`)

Why it matters: Inventory checks stock by SKU and size here to spot shortfalls (e.g. white tee S
and the crest mug are at 0).

### `pricing`
Fields: `sku` (PK), `unit_cost`, `list_price`

Why it matters: Accounting uses cost against price to check margins before approving a discount
or pricing a restock order.

### `vendors`
Fields: `id` (PK), `name`, `specialty`, `lead_days`

Why it matters: Inventory picks who can restock an item (by specialty), and `lead_days` sets
how long a restock takes.

### `invoices`
Fields: `id` (PK), `vendor_id` (→ `vendors.id`), `amount`, `due_date`, `status`, `description`

Why it matters: bills the shop owes. An open invoice past `date_today` is overdue, and a vendor
won't ship new product while it has an open unpaid invoice.

### `leases`
Fields: `id` (PK), `space_name`, `landlord`, `monthly_rent`, `next_due`, `notes`

Why it matters: Facilities tracks the shop space here. Rent is a cash obligation with a due
date that Accounting has to plan for.

### `cash_accounts`
Fields: `name` (PK), `balance`, `date`

Why it matters: the only money the shop has ($3,400 in `checking`). Every payment draws it down,
and the pay tool must refuse anything that would make it negative. No money comes in.

### `payments`
Fields: `id` (PK), `kind`, `ref_id`, `amount`, `account`, `paid_at`, `approved_by`

Why it matters: the payment ledger (empty at start). Each human-approved payment is recorded
here, with `ref_id` pointing to the invoice or lease it paid and `approved_by` naming the
approving human.

### Board tables (added by the MCP server)
The original database has no place for drafts, approval requests, or purchase orders, so the MCP
server creates these three empty tables in the working copy on first connect (a reset clears them).

#### `drafts`
Fields: `id` (PK), `ticket_id` (→ `tickets.id`), `to_name`, `subject`, `body`, `author_agent`,
`status` (always `draft`), `created_at`

Why it matters: every customer, landlord, or vendor message lands here as a draft for a human to
review and send. The system has no way to send anything.

#### `approvals`
Fields: `id` (PK), `kind` (`invoice` / `rent` / `purchase_order`), `ref_id`, `amount`, `ticket_id`,
`reason`, `requested_by`, `status` (`pending` / `paid` / `rejected`), `decided_by`, `decided_at`,
`decision_note`, `created_at`

Why it matters: the human approval queue. Agents can only add `pending` rows (the amount is read
from the database); only a named human moves one to `paid` (which writes `payments` and lowers
`cash_accounts`) or `rejected`.

#### `purchase_orders`
Fields: `id` (PK), `vendor_id` (→ `vendors.id`), `sku`, `size`, `qty`, `unit_cost`, `total`,
`ticket_id`, `status` (`pending_approval` / `approved` / `rejected`), `eta_date`, `created_by`, `created_at`

Why it matters: restock orders priced at `pricing.unit_cost`. Each PO gets an approval row, and it
only becomes `approved` (with `eta_date` = shop date + vendor lead days) when a human pays it.

## How the open tickets link to other tables

| Ticket | Type | Links | What the linked data shows |
|---|---|---|---|
| **101** Bulldog tee (Tauhid Zaman) | `customer_order` | `sku`/`size` → `inventory`; `invoice_id` 501 → `invoices` → `vendors` 1 | Wants 1 × CC-TEE-WHITE S; stock is **0**. Restock comes from Bulldog Print Co (apparel reprint, 5 lead days), but its invoice 501 ($840, "Rush reprint CC-TEE-WHITE S") was due 2026-08-28 and is still **open → overdue**, so the vendor won't ship until it's paid. |
| **102** Rent due (Elm City Properties) | `rent_notice` | `lease_id` 1 → `leases` | Chapel Street shop rent **$2,400** due **2026-09-02** (2 days out). |
| **103** Bulk hoodie discount (Yale AI Club) | `price_override` | `sku`/`size` → `inventory`, `pricing` | Wants **20** × CC-HOOD-NAVY M at a discount; only **8** on hand (short 12). Cost $22 vs list $58, so Accounting must check the margin at any discounted price. Restock would also come from Bulldog Print Co, which is blocked by invoice 501. |

**Cash check:** $3,400 in checking − $840 (invoice 501) − $2,400 (rent) = **$160 left**. Paying
both obligations leaves almost nothing for a hoodie restock (12 × $22 = $264 at cost), so the
team has to prioritize and every payment needs human approval.

---

## MCP tools

Server: `mcp_server/server.py` (FastMCP, name `campus-customs`), reading only
`data/campus_customs_new.db`. Every agent on the team uses these tools; every value they return
comes from the database, and "today" is `desk.date_today`. The three tools below were the
Problem 3 starting set; the full list (19 tools) is in **All MCP tools** further down.

### 1. `check_stock(sku, size, qty_needed=1)`
- **Reads:** `inventory`
- **Unlocks:** **103** (also 101)
- **Why it's the right tool:** Ticket 103 asks for 20 × CC-HOOD-NAVY in M. This tool looks up that
  exact SKU + size and returns `on_hand: 8, shortfall: 12`, so the team knows they can't fill
  the order from the shelf before anyone talks discounts. The same call on CC-TEE-WHITE S
  returns `on_hand: 0` for ticket 101.

### 2. `get_vendor_status(vendor_id)`
- **Reads:** `vendors`, `invoices`, `desk`
- **Unlocks:** **101**
- **Why it's the right tool:** Ticket 101's tee is out of stock and the ticket links to invoice 501.
  For Bulldog Print Co (vendor 1), this tool shows invoice 501 ($840) is open and 3 days overdue
  against `date_today`, so `will_ship: false` (5-day lead time once it's paid). That's the real
  blocker on the restock.

### 3. `get_lease(lease_id)`
- **Reads:** `leases`, `desk`
- **Unlocks:** **102**
- **Why it's the right tool:** Ticket 102 is an emailed rent notice pointing at `lease_id` 1. This
  tool confirms the notice against the lease on file: Elm City Properties, $2,400 for the Chapel
  Street shop, due 2026-09-02, which is `days_until_due: 2` from `date_today`. Facilities can
  verify the amount and deadline before Accounting is asked to pay anything.

---

## Agent team

Built with PydanticAI in `backend/`. Every agent runs on **`gpt-6-luna`** through Portkey
(`PORTKEY_API_KEY` from the course-root `.env`), and gets shop facts only from the MCP server above.
There's no second tools layer.

| Agent | Prompt | Output | Job | MCP tools it can call |
|---|---|---|---|---|
| **Boss** | `backend/prompts/boss.md` | `BossReport` | Reads the board, routes each ticket, weighs the cash picture, sets ticket status, writes the owner's wrap-up. | `list_open_tickets`, `get_ticket`, `add_ticket_note`, `set_ticket_status`, `get_cash_position`, `list_approvals` |
| **Inventory** | `backend/prompts/inventory.md` | `AgentReport` | Stock by SKU + size, vendor match and lead time, whether the vendor will ship, restock POs. | `get_ticket`, `add_ticket_note`, `check_stock`, `find_vendors`, `get_vendor_status`, `quote_price`, `create_purchase_order`, `draft_message` |
| **Accounting** | `backend/prompts/accounting.md` | `AgentReport` | Cash and obligations, overdue invoices, discount margins, payment priority, payment requests. | `get_ticket`, `add_ticket_note`, `get_cash_position`, `get_invoice`, `get_vendor_status`, `get_lease`, `quote_price`, `request_payment`, `list_approvals` |
| **Facilities** | `backend/prompts/facilities.md` | `AgentReport` | The Chapel Street lease: verifies rent notices against the lease, urgency, landlord drafts; sends payment to Accounting. | `get_ticket`, `add_ticket_note`, `get_lease`, `get_cash_position`, `draft_message` |
| **Customer Service** | `backend/prompts/customer_service.md` | `AgentReport` | Customer-facing reply drafts with real stock and list price, never internal details. | `get_ticket`, `add_ticket_note`, `check_stock`, `quote_price`, `draft_message` |

**Full connectivity.** Every agent also has a `delegate(to, task)` tool that can call any other
agent (not itself). The caller waits for the teammate's `AgentReport`/`BossReport`.

**Files.**
- `backend/models.py`: data types (`AgentReport`, `BossReport`, `HumanAction`, `DelegationResult`, `AuditRecord`, `TeamDeps`, `RunBudget`).
- `backend/agents.py`: the five agents, per-role MCP tool filters, `delegate`, and the agent loop (`run_agent` steps through `agent.iter()` node by node).
- `backend/audit.py`: appends to `output/audit_trail.json`.
- `backend/config.py`: model, Portkey, limits.
- `backend/run.py`: CLI. `python -m backend.run --ticket 101`, or `--agent inventory --task "..."`.

**Audit trail.** `output/audit_trail.json` is a JSON array that only grows. It is never cleared
between runs. Each run writes `run_start`, then one `step` record per agent-loop node
(`UserPromptNode`, `ModelRequestNode`, `CallToolsNode`, `End`), a `delegation` record whenever
one agent calls another, then `run_end` (or `run_error`). Every record carries `run_id`, `agent`,
`ticket_id`, the delegation `chain` and `depth`, the model, the tool calls with their arguments,
the tool results, the model text or final output, and cumulative token usage.

## All MCP tools

| Tool | Tables | Reads / writes | Used by |
|---|---|---|---|
| `list_open_tickets()` | `tickets`, `desk` | read | Boss |
| `list_tickets()` | `tickets`, `desk` | read (all tickets, incl. resolved) | Dashboard / backend only |
| `get_ticket(ticket_id)` | `tickets`, `drafts`, `approvals`, `purchase_orders`, `desk` | read | all |
| `add_ticket_note(ticket_id, agent, note)` | `tickets` | write (appends to notes) | all |
| `set_ticket_status(ticket_id, status, agent, reason)` | `tickets`, `approvals` | write | Boss |
| `check_stock(sku, size, qty_needed)` | `inventory` | read | Inventory, Customer Service |
| `quote_price(sku, qty, unit_price)` | `pricing` | read | Inventory, Accounting, Customer Service |
| `find_vendors(specialty_keyword)` | `vendors`, `invoices` | read | Inventory |
| `get_vendor_status(vendor_id)` | `vendors`, `invoices`, `desk` | read | Inventory, Accounting |
| `get_invoice(invoice_id)` | `invoices`, `vendors`, `desk` | read | Accounting |
| `get_lease(lease_id)` | `leases`, `desk` | read | Accounting, Facilities |
| `get_cash_position()` | `cash_accounts`, `invoices`, `vendors`, `leases`, `approvals`, `desk` | read | Boss, Accounting, Facilities |
| `request_payment(kind, ref_id, ticket_id, requested_by, reason)` | `approvals` (amount read from `invoices` / `leases`) | write (pending request only) | Accounting |
| `create_purchase_order(vendor_id, sku, size, qty, ticket_id, requested_by)` | `purchase_orders`, `approvals` (reads `vendors`, `invoices`, `inventory`, `pricing`) | write (pending request only) | Inventory |
| `list_approvals(status)` | `approvals` | read | Boss, Accounting |
| `draft_message(ticket_id, to_name, subject, body, author_agent)` | `drafts` | write (never sent) | Inventory, Facilities, Customer Service |
| `approve_and_pay(approval_id, approved_by)` | `approvals`, `payments`, `cash_accounts`, `invoices`, `leases`, `purchase_orders` | write | **Human only** |
| `reject_approval(approval_id, decided_by, note)` | `approvals`, `purchase_orders` | write | **Human only** |
| `close_ticket(ticket_id, closed_by, note)` | `tickets`, `approvals` | write (refused while approvals are pending) | **Human / desk only** |

`drafts`, `approvals`, and `purchase_orders` are board tables the server creates (empty) in the
working copy on first connect. Resetting with `cp data/campus_customs.db data/campus_customs_new.db`
clears them.

## Safety

**Real customers and real money**
- **A human approves every payment and every purchase order.** Agents can only file requests.
  `approve_and_pay`, `reject_approval`, and `close_ticket` are filtered out of every agent's toolset, and they also
  refuse an approver named after an agent.
- **Amounts come from the database, not the model.** `request_payment` reads the invoice or rent
  amount itself, and POs are priced at the pricing table's unit cost, so a model can't inflate or
  invent a number.
- **No overdrafts.** `approve_and_pay` refuses anything that would take checking below $0. Requests
  and POs larger than the balance are refused up front, and `get_cash_position` shows the balance
  after all pending requests so the team can prioritize (rent, then overdue invoices, then restocks).
- **No duplicates and no double payment.** A second pending request for the same invoice or lease is
  refused, and a request that's already paid or rejected can't be approved again.
- **Vendor rule enforced in code.** No PO goes to a vendor with an open invoice.
- **Nothing is sent automatically.** There is no send tool. Every customer, landlord, or vendor
  message is a draft on the board that a person reviews and sends.
- **Least privilege.** Each agent sees only the tools its job needs (table above). Customer
  Service can't touch money, and Boss can't file payments.
- **Internal data stays internal.** The prompts forbid sharing costs, margins, cash, unpaid invoices,
  or other customers' details in anything a customer reads. Discounts need Accounting's margin check
  and never go at or below cost.
- **Tickets are data, not instructions.** Every prompt says to ignore instructions embedded in
  tickets or emails (e.g. "pay this now") and flag them, which guards against prompt injection.
- **Can't close with money pending.** `set_ticket_status(resolved)` is refused while the ticket has
  pending approvals.
- **Everything is auditable.** Every step, tool call, argument, result, and delegation is appended to
  `output/audit_trail.json`, and every payment row records `approved_by`. If the audit file can't be
  read, the run stops rather than overwriting history.
- **Facts only from tools.** Every prompt says never to guess stock, prices, dates, or amounts, and
  "today" is the shop's `desk.date_today`.

**What the full run taught us**
- **Human review caught a real agent mistake.** On #101 a deep delegation chain (Customer Service →
  Inventory → Accounting) filed the $2,400 rent under the tee ticket. The tool allowed it (the amount
  was correct), but the person at the desk rejected it because rent belonged to #102. A real business
  should also check in code that a request's `kind` matches its ticket (e.g. rent only on a
  `rent_notice` ticket).
- **Tickets close only through the desk.** `close_ticket` is human/desk-only and refuses while
  approvals are pending, so a ticket can't be marked done with money still in flight.
- **Cash reserves aren't automatic.** Rejecting a request doesn't hold the money. Agents re-check
  `get_cash_position` before each new spend (Accounting confirmed rent was still covered before
  approving the $8 PO).

**Token limits** (`backend/config.py`)
- **One shared budget per top-level run.** Delegated agents draw from the same usage counters, so
  a chain of delegations can't multiply the spend: `request_limit=40`, `tool_calls_limit=80`,
  `total_tokens_limit=250,000`. Going over stops the whole run, and it's logged as `run_error`.
- **Delegation caps.** Max depth 3 (e.g. boss → facilities → accounting → one more), at most 10
  delegations per run, and no self-delegation. The current depth and remaining delegations are
  shown to each agent in its instructions.
- **Per-response cap.** `max_tokens=8,000` with `openai_reasoning_effort="low"`.
- **Small context.** Agents get tool results, not table dumps. Each prompt tells the agent to
  make one well-scoped delegation and not re-check facts. The audit trail clips long strings to
  2,000 characters.
- For scale, the Problem 9 runs used **39k tokens** (102, one chain) to **99k tokens** (101 run 1, which made
  seven agent calls up to depth 3). All four runs together used about 285k tokens, and each stayed under the 250k per-run cap.

---

## Backend routes

FastAPI in `backend/main.py`. Start it from `backend/` with the course venv active:
`source ../../.venv/bin/activate && uvicorn main:app --reload --port 8000`. Every route reads and
writes through the MCP server (except reset, which copies the DB file).

- `GET /api/tickets`: all 3 tickets with status, `is_resolved`, and whether the team is working one right now.
- `GET /api/tickets/{id}`: one ticket with its notes, drafts, approvals, and POs.
- `POST /api/tickets/{id}/run`: starts the agent team (Boss) on that ticket in the background and returns a `run_id` (409 if that ticket is already running).
- `GET /api/runs` and `GET /api/runs/{run_id}`: run status (`running` / `done` / `error`) and Boss's final report.
- `GET /api/events?limit=&ticket_id=&run_id=&after=`: recent agent events from the audit trail, showing what each agent said, which tools it called (with args), and its delegations. Pass `after` to poll for new events only.
- `GET /api/approvals?status=pending`: payment and PO requests the agents filed.
- `POST /api/approvals/{id}/approve` `{"approved_by": "<human>"}`: the only route that moves cash. It pays the request, lowers checking, and marks the invoice paid / advances rent / approves the PO. It refuses overdrafts, agent names, and repeats.
- `POST /api/approvals/{id}/reject` `{"approved_by": "<human>", "note": ""}`: rejects a request; nothing is paid.
- `GET /api/cash`: current checking balance from `cash_accounts`, plus pending total and bills due.
- `POST /api/reset`: copies `campus_customs.db` over `campus_customs_new.db` for a fresh run (refused while a run is going). The audit trail is kept.
- `GET /api/health`: liveness check.

**Resolving tickets:** when a run finishes, the backend closes the ticket (`close_ticket`) if nothing
on it is waiting for approval. Otherwise it closes as soon as a human approves or rejects the last
pending request. CORS allows the Vite dashboard at `http://localhost:5173`.

## Dashboard

React + Vite + TypeScript in `frontend/`, calling the routes above at `http://localhost:8000`
(`VITE_API_URL` overrides it). Start with `npm run dev` from `frontend/` and open
`http://localhost:5173`. The full design write-up is in `output/design.md`.

| Area | What it shows | Routes it uses |
|---|---|---|
| Ticket spike (left) | The 3 tickets as torn paper receipts, with status, a "N to approve" badge, a pulsing glow while the team works, and a RESOLVED stamp | `GET /api/tickets`, `GET /api/approvals` |
| Ticket header | Ticket details and the **Send to the team →** button (disabled while running or resolved) | `POST /api/tickets/{id}/run` |
| The floor (center) | The five agents as HTML/CSS creatures (Boss = Handsome Dan), joined by wires for full connectivity. Live hand-offs glow, past ones stay dotted. Each agent has a status and a plain-English bubble you can expand | `GET /api/events?ticket_id=` (polled every 1.2s while running) |
| Live wire tab | Every step: who, what they said or did, tool chips with arguments, indented by delegation depth | `GET /api/events` |
| Shift report tab | Boss's wrap-up and owner checklist, one card per agent that worked (summary, actions, blockers, tools), and drafts waiting to be sent | `GET /api/events`, `GET /api/tickets/{id}` |
| Register (right) | Checking balance (rolls down after a payment), bills due, a name field that signs approvals, and the approval tray of receipts with **Approve & pay** / **Reject** | `GET /api/cash`, `POST /api/approvals/{id}/approve`, `.../reject` |
| Top bar | Shop date, "team on shift" light (a heart when the floor is quiet), and **Fresh shift** (reset) | `POST /api/reset` |

A ticket shows **resolved** when its run is finished and nothing on it is pending: either right
when the run ends, or as soon as a human approves or rejects its last pending request.

---

## Full run results (Problem 9)

Clean reset, then 101 → 102 → 103 run from the dashboard, with every payment approved on the
dashboard by a named human (Kate). Details are in `output/desk_tickets.html` (Expected vs Actual and
Cash tabs), `output/resolved_tickets.json`, and `output/resolved_board.html` (screenshots).

| Ticket | Agents (who Boss called first) | Money | Tokens |
|---|---|---|---|
| 101 Bulldog tee | **Inventory** → Accounting, Customer Service (+ a follow-up run for the PO) | −$840 invoice 501, −$8 PO; rent request filed here by mistake **rejected** | 183.5k (2 runs) |
| 102 Rent due | **Facilities** → Accounting (chain) | −$2,400 rent | 39.0k |
| 103 Bulk hoodies | **Inventory** → Accounting, Customer Service | $0 (restock $264 > $152 left, held) | 62.1k |

Checking **$3,400.00 → $152.00** (paid $3,248.00). This matches `cash_accounts` and the sum of `payments`.
