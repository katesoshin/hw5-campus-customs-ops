# HW5 — AI Prompt Log

A by-problem record of what I asked Claude to do while building Campus Customs Multi-Agent
Operations: an MCP server, a FastAPI backend with a multi-agent team (Boss, Inventory,
Accounting, Facilities, Customer Service), and a React dashboard for watching the agents and
approving requests. One section per problem; each is filled in when we actually work that
problem.

---

## Problem 2 — Study the Campus Customs database

### Your prompts
Ok let's work on Problem 2. Open `data/campus_customs.db` and go through every table and its
fields. Then copy the original to `data/campus_customs_new.db`, since later problems will update
that working copy and I want the original kept clean so I can reset. Look at the 3 open tickets
too so you see how they link to the other tables. After that, start `output/harness.md`: for
each table, list the fields and add one short line on why that table matters for the agents.
We'll keep growing this harness in later problems.

---

## Problem 3 — Build the MCP server

### Your prompts
ok let's do problem 3, build the MCP server. write it in `mcp_server/` with FastMCP and have it
talk to `data/campus_customs_new.db`. you don't need to connect or run it yet.

every agent in this hw is going to use these tools. we'll add more later, but for now just write
3 tools you know we'll need for the tickets. keep the names clear and don't make up any data,
only use what's in the database.

in `output/harness.md`, list the 3 tools. for each one, say which table it reads, which ticket it
helps with (101, 102, 103), and one sentence on why it's the right tool for that ticket. make
sure to actually tie the tool to the ticket, not just something vague like "reads inventory."

also add a short `mcp_server/README.md` that says what the server is for, which db file it uses,
and the 3 tools.

---

## Problem 4 — Add the MCP server to vibe coder and test each tool

### Your prompts
Ok let's work on problem 4. add our MCP server to this project and save the connection json in
`.mcp.json` at the project root.

then test each of our 3 MCP tools and save the evidence in `output/mcp_smoke.json`. for every
tool, include the prompt I asked you, the tool name, and the tool output.

### Follow-up prompt
and the tool output has to match the values in `data/campus_customs_new.db`.

---

## Problem 5 — Build the agent team and grow the MCP tools

### Your prompts
ok let's work on problem 5. build the agent team with PydanticAI: Boss, Inventory, Accounting,
Facilities, and Customer Service. they should be able to delegate to each other freely. use
gpt-6-luna through my PORTKEY_API_KEY for every agent.

put one detailed prompt per agent in `backend/prompts/` with the shop rules that agent needs, data
types in `backend/models.py`, and the agents under `backend/`. add whatever MCP tools they need for
the open tickets. all shop data has to go through MCP.

log every agent step to `output/audit_trail.json`, appending and never wiping it. then update
`output/harness.md` with the agents, the tools and their tables, and a short safety and
token-limits section, and update the MCP README.

---

## Problem 6 — Plan the three tickets

### Your prompts
before we wire the backend, write down what you expect the team to do on each open ticket. build
`output/desk_tickets.html` as a page I can double-click, with one tab each for 101, 102, and 103,
plus Cash and Reflection tabs that just say "coming later" for now.

each ticket tab gets an Expected section (leave room for an Actual section after we run the
agents): who Boss calls first and why, the specific delegations we expect, and which MCP tools that
run should use. don't just send every specialist on every ticket. we'll compare this plan to what
actually happens.

---

## Problem 7 — Backend routes

### Your prompts
ok let's do problem 7. the React dashboard needs a backend to call, so build `backend/main.py`
with FastAPI. I need routes to list the 3 tickets with open/resolved status, run the agent team on
a ticket, return recent agent events (what each agent said and which tools it used), approve a
payment or PO when a human clicks approve (this is the only thing that moves cash), return the
checking balance, and reset the database for a fresh run.

it should start from `backend/` with `uvicorn main:app --reload --port 8000`. add a one-line list
of the routes to `output/harness.md`.

---

## Problem 8 — Agent dashboard

### Your prompts
ok let's do problem 8. build the dashboard in `frontend/` with React + Vite + TypeScript, calling our
backend at `http://localhost:8000` (and allow the Vite origin on the backend). the board should list
the three tickets, let me start the team on one, show each agent talking and working live, mark the
ticket resolved when the run finishes, summarize what each agent did, let a human approve payments
or POs, and show the checking balance dropping after a payment.

make it look good and feel like a desk people would actually want to sit at. it should start with
`npm run dev`. then write `output/design.md` on the layout, how the agents look different, how
resolved tickets and cash show up, and why.

---

## Problem 9 — Resolve the tickets

### Your prompts
ok let's do problem 9. reset `data/campus_customs_new.db` so we start clean and note the starting
checking balance, then run all three tickets on the board until each one is resolved.

in `output/desk_tickets.html`, fill each ticket's Actual section (which agents worked, what they
delegated, which tools they used) next to the Expected plan. on the Cash tab, itemize the money:
the starting balance, how cash changed as each ticket resolved and why, and an ending balance that
matches `cash_accounts`.

also save `output/resolved_tickets.json` (status, outcome, what each agent did, human approvals) and
`output/resolved_board.html` with a screenshot of the board for each resolved ticket. keep appending
to the audit trail, and finish `output/harness.md`.

---

## Problem 10 — Reflection

### Your prompts
ok let's do problem 10. I'll give you my reflections, and you put them into the Reflection tab in
`output/desk_tickets.html`, one section per question: how I'd evaluate the agents on each ticket and
why (they really need to be faster, the run took over 15 minutes), how each ticket's actual run
compared to my expected plan, what would have been simpler with one agent, three new problems the
team could solve with our tools, and three it couldn't (plus what I'd need to add).

keep my wording plain, and back each point with the ticket tabs and Cash tab on the same page.
