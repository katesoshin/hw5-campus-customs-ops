# Campus Customs MCP Server

The shared toolbox for the Campus Customs agent team. Every agent (Boss, Inventory,
Accounting, Facilities, Customer Service) works the ticket board through these tools instead
of touching the database directly. Built with [FastMCP](https://gofastmcp.com).

## Database

- Uses the working copy **`data/campus_customs_new.db`** only.
- The original `data/campus_customs.db` is never modified. To reset before a full run:
  `cp data/campus_customs.db data/campus_customs_new.db`
- On first connect the server adds three empty board tables to the working copy: `drafts`,
  `approvals`, `purchase_orders`. A reset clears them.
- Tools only return what is in the database. "Today" is `desk.date_today`, not the real clock.

## Tools

| Tool | Tables | What it does |
|---|---|---|
| `list_open_tickets()` | `tickets`, `desk` | Every unresolved ticket plus the shop's date. |
| `list_tickets()` | `tickets`, `desk` | Every ticket including resolved ones (used by the dashboard backend, not the agents). |
| `get_ticket(ticket_id)` | `tickets`, `drafts`, `approvals`, `purchase_orders` | One ticket with its links and anything already attached to it. |
| `add_ticket_note(ticket_id, agent, note)` | `tickets` | Appends a dated, signed note. |
| `set_ticket_status(ticket_id, status, agent, reason)` | `tickets`, `approvals` | open / in_progress / waiting_on_human / blocked / resolved. Won't resolve while approvals are pending. |
| `check_stock(sku, size, qty_needed=1)` | `inventory` | On-hand qty and location for one SKU + size, and the shortfall against `qty_needed`. |
| `quote_price(sku, qty, unit_price=None)` | `pricing` | Cost, list, discount %, unit and order margin; flags prices at or below cost. |
| `find_vendors(specialty_keyword=None)` | `vendors`, `invoices` | Vendors by specialty with lead days and `will_ship`. |
| `get_vendor_status(vendor_id)` | `vendors`, `invoices`, `desk` | Lead time, open invoices (flagged overdue against `date_today`), and `will_ship` (false while any invoice is unpaid). |
| `get_invoice(invoice_id)` | `invoices`, `vendors`, `desk` | One invoice: amount, due date, status, days overdue. |
| `get_lease(lease_id)` | `leases`, `desk` | Landlord, monthly rent, next due date, and days until rent is due. |
| `get_cash_position()` | `cash_accounts`, `invoices`, `leases`, `approvals` | Balance, bills due in the next 30 days, pending approvals, balance after each. |
| `request_payment(kind, ref_id, ticket_id, requested_by, reason)` | `approvals` | Files an invoice or rent payment for human approval. Amount read from the DB; no duplicates. |
| `create_purchase_order(vendor_id, sku, size, qty, ticket_id, requested_by)` | `purchase_orders`, `approvals` | Restock PO at unit cost, filed for approval. Refused if the vendor has an open invoice. |
| `list_approvals(status="pending")` | `approvals` | Pending / paid / rejected / all requests. |
| `draft_message(ticket_id, to_name, subject, body, author_agent)` | `drafts` | Saves a customer/landlord/vendor message as a draft. Nothing is ever sent. |
| `approve_and_pay(approval_id, approved_by)` | `approvals`, `payments`, `cash_accounts`, `invoices`, `leases`, `purchase_orders` | **Human only.** Pays an approved request; refuses overdrafts and agent approvers. |
| `reject_approval(approval_id, decided_by, note)` | `approvals`, `purchase_orders` | **Human only.** Rejects a request. |
| `close_ticket(ticket_id, closed_by, note)` | `tickets`, `approvals` | **Human / desk only.** Marks a ticket resolved; refused while it has pending approvals. |

The agent team (`backend/main.py`) gives each agent only the tools its role needs and never
exposes the two human-only tools.

## Run

```bash
python mcp_server/server.py
```

Runs over stdio for an MCP client.
