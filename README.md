# Campus Customs: Multi-Agent Operations

MGT 409 · HW5. A small Yale merch shop run by a team of five AI agents (Boss, Inventory, Accounting,
Facilities, Customer Service) that work a ticket board through a shared **MCP server**. A **FastAPI**
backend runs the team, and a **React** dashboard lets a human watch the agents and approve every payment.

- Every agent uses `gpt-6-luna` through Portkey (PydanticAI).
- Shop facts come only from the MCP server, which reads `data/campus_customs_new.db`.
- Agents can only *ask* for money. A named human clicks **Approve & pay** on the dashboard.

## What's in the repo

```
hw5/
├── AI_prompts.md
├── requirements.txt
├── .env.example
├── .gitignore
├── .mcp.json
├── README.md
├── data/
│   ├── campus_customs.db
│   └── campus_customs_new.db
├── mcp_server/
│   ├── server.py
│   └── README.md
├── frontend/
├── backend/
│   ├── main.py
│   ├── models.py
│   └── prompts/
│       ├── boss.md
│       ├── inventory.md
│       ├── accounting.md
│       ├── facilities.md
│       └── customer_service.md
└── output/
    ├── harness.md
    ├── mcp_smoke.json
    ├── desk_tickets.html
    ├── design.md
    ├── resolved_tickets.json
    ├── resolved_board.html
    ├── audit_trail.json
    └── github_url.txt
```

| Path | What it is |
|---|---|
| `AI_prompts.md` | Prompt log, one section per problem |
| `.env.example` | Copy to `.env` and add your `PORTKEY_API_KEY` (the real `.env` is never committed) |
| `.mcp.json` | MCP connection for Claude Code / other MCP clients |
| `data/campus_customs.db` | Original database: never modified, the reset point |
| `data/campus_customs_new.db` | Working copy the app reads and writes |
| `mcp_server/` | FastMCP server with the shop's tools (list in its README) |
| `frontend/` | React + Vite + TypeScript dashboard |
| `backend/main.py` | Agent team, audit trail, FastAPI routes, and a command-line runner |
| `backend/models.py` | Data types (agent reports, audit records, run state) |
| `backend/prompts/` | One prompt per agent |
| `output/` | Harness, design notes, plan vs. actual, results, audit trail, repo URL |

> Note: the working copy `data/campus_customs_new.db` is checked in **after** our full three-ticket
> run (checking = $152, all tickets resolved), so you can see the results. Reset it (below) before
> running the agents yourself.

## 1. Set up (once)

You need Python 3.11+ and Node 18+.

```bash
git clone https://github.com/katesoshin/hw5-campus-customs-ops.git
cd hw5-campus-customs-ops

python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # then put your real PORTKEY_API_KEY in .env

cd frontend && npm install && cd ..
```

## 2. Get a clean database

The app only touches the working copy. Whenever you want a fresh start, copy the original over it:

```bash
cp data/campus_customs.db data/campus_customs_new.db
```

(The dashboard's **↺ Fresh shift** button and `POST /api/reset` do the same thing.)

## 3. Start the MCP server

The backend starts the MCP server for you automatically (over stdio) when it boots, so for normal use
you can skip this step. To run it on its own, or to check it works before starting the backend:

```bash
python mcp_server/server.py
```

It talks over stdio, so it will sit and wait for an MCP client (stop it with Ctrl+C). Claude Code and
other MCP clients can connect with the included `.mcp.json`. The tool list is in `mcp_server/README.md`.

## 4. Start the FastAPI backend (terminal 1)

```bash
source .venv/bin/activate
cd backend
uvicorn main:app --reload --port 8000
```

The API runs at http://localhost:8000 (interactive docs at http://localhost:8000/docs).

## 5. Start the React board (terminal 2)

```bash
cd frontend
npm run dev
```

Open http://localhost:5173. The board calls the backend at `http://localhost:8000`.

## 6. Run all three tickets (the full run)

1. **Reset first.** Click **↺ Fresh shift** on the board, or run step 2 above with the backend stopped.
   Checking should read **$3,400.00** and tickets 101, 102 and 103 should be **open**.
2. Type your name in **At the desk** (it signs every approval).
3. Pick ticket **#101** and click **Send to the team →**. Watch the agents on the floor and the **Live wire**.
4. When requests print in the **Approval tray**, read them and click **Approve & pay** or **Reject**.
   A ticket shows **✓ Resolved** once its run is done and nothing is waiting on you.
5. Repeat for **#102** and **#103**.

Our own run's results (plan vs. actual, cash ledger, screenshots) are in `output/desk_tickets.html`,
`output/resolved_tickets.json` and `output/resolved_board.html`.

You can also run a ticket from the command line: `cd backend && python main.py --ticket 101`.

## Safety in one paragraph

Only a human can pay (`approve_and_pay` is never given to an agent and refuses agent names). Amounts
come from the database, never from the model. Payments that would overdraw checking are refused, as
are duplicates and purchase orders to a vendor with an unpaid invoice. There is no send tool: every
customer or landlord message is a draft. Every agent step is appended to `output/audit_trail.json`.
More detail is in `output/harness.md`.
