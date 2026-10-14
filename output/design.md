# Campus Customs Back Office: dashboard design

The dashboard lives in `frontend/` (React + Vite + TypeScript) and talks to the FastAPI backend at
`http://localhost:8000`. Start it with `npm run dev` from `frontend/`.

## The idea

Most agent dashboards look like log viewers. We wanted this one to feel like **a real shop's back
office**: tickets on a spike, a team of little coworkers on the floor, a cash register on the right,
and receipts you physically stamp. Someone running Campus Customs should be able to glance at it and
know three things right away: what's on the board, who's working on what, and how much money is left.
They should also enjoy sitting there while the team works.

The look is **Yale navy and white**: a clean, near-white page under a Yale-blue header bar with a
serif "Campus Customs" wordmark, so it feels like an official campus shop tool. Yale blue is kept for
the things that matter (live activity, money, and anything waiting on you), red is used only for
overdue bills and the PAID stamp, and everything else stays quiet gray and white.

## Layout: three zones, read left to right like a shift

| Zone | What it is | Why |
|---|---|---|
| **Left: the ticket spike** | The three tickets as **paper receipts torn off a pad**: ripped zig-zag edges top and bottom, cream paper, monospace receipt type, a "Campus Customs" header, dashed rules, the time the ticket came in, and a short barcode with the ticket number printed under it. Each hangs slightly tilted from a spike through a punched hole. | Tickets are physical things in a real shop, and a torn receipt says "a request came in" at a glance. The paper look keeps them apart from the live data around them. The selected receipt slides out with a navy outline that follows its torn edge. |
| **Center: the floor** | The selected ticket's header with a big **Send to the team →** button, then the floor where the five agents sit, then a tabbed panel: **Live wire** and **Shift report**. | The middle is where the action is, so the agents get the most space. |
| **Right: the register** | The checking balance on a glowing register display, the bills due, a "your name" sign-in, and the **approval tray** of paper receipts. | Money and approvals stay visible at all times. You never have to dig to find out what's pending or how much cash is left. |

On narrow screens the zones stack in the same order.

## How agents read differently

Each agent is a **small creature built in HTML + CSS** (no images): a soft pastel body, big sparkly
eyes that blink, rosy cheeks, tiny feet, and a role accessory. Even on break they gently breathe. The Boss is **Handsome Dan**, Yale's bulldog mascot, so the one in
charge is instantly recognizable and the desk feels like it belongs to a Yale shop. Each one has its own color, shape, accessory, and **voice**, so
you can tell who's talking without reading the name:

| Agent | Color | Shape + accessory | Voice in bubbles and the wire |
|---|---|---|---|
| Boss | Yale gold | **Handsome Dan**, Yale's bulldog: droopy ears, a tan eye patch, a jutting underbite with two fangs, and a gold **Y** tag on a navy collar. Sits at the top of the floor. | **bold** |
| Inventory | bright blue | **square**, with a little parcel on its head | plain |
| Accounting | Yale navy | egg-shaped, with **black round glasses** | `monospace, like a ledger` |
| Facilities | slate blue | sturdy, with a **hard hat** | slightly spaced, plain-spoken |
| Customer Service | teal | soft heart-ish, with a **headset** | *italic, warm* |

**Creatures act out their state.** Idle agents are dimmed and "on break". A working agent bobs and
its mouth moves as if talking (Dan's underbite chomps). An agent waiting on someone else looks up and to the side at them.
When an agent is done, it smiles.

**Speech bubbles expand.** A bubble shows up to four lines. Hover to read the whole message, or
click to pin it open (click again to fold it). An open bubble floats above everything, even past the
edge of the floor.

**Speech bubbles are in plain English, not tool names.** Agents mostly act through tools, so the
board turns each call into a sentence: `check_stock` becomes "Checking the shelf: CC-TEE-WHITE S × 1",
`get_cash_position` becomes "Counting the cash drawer", and `delegate` becomes "Handing off to Accounting".
The raw tool name still shows as a chip in the Live wire for anyone auditing.

**The floor is a pentagon.** Dan sits at the top, Inventory and Customer Service on the far sides,
and Accounting and Facilities along the bottom, so every agent has room for a four-line speech bubble
without crowding its neighbors.

**Full connectivity is drawn, not just claimed.** All five agents are joined by faint wires, the
complete graph, because any agent can call any other. When one agent delegates, that wire lights up
blue with dashes flowing toward the agent being called. Afterwards it stays as a dotted trace, so
you can see the path the work took (e.g. Boss → Facilities → Accounting on rent).

**The Live wire** is the running log: a timestamp, the agent's name in its color, what it said or did,
and tool chips. Rows are **indented by delegation depth**, so a hand-off from Boss to Facilities to
Accounting reads like a nested conversation.

## The shift report

When a run finishes, the center panel **flips to the Shift report by itself**:
- **Boss's wrap-up** at the top: the outcome, a cash note, and a checklist of what *you* need to do.
- **One card per agent that actually worked**, with a colored top edge in the agent's color. Each
  card has a summary, actions taken, any blockers, and the tools it used. Agents who weren't called
  don't get a card, so you can see at a glance which specialists were really needed.
- **Drafts waiting for a human to send**: expandable, so you can read the exact customer or landlord
  message before sending it yourself (nothing is sent automatically).

## Money: the register and the receipts

- **Checking balance** is on a Yale-navy register display in white monospace. When a payment is
  approved, the number **rolls down** like a real register, and a small **"−$2,400.00"** floats up
  and fades. You can feel the money leave. A thin meter below shows what's left *if you approve
  everything pending*, and its number turns red if that would go negative.
- **Bills due** (open invoices and rent) are listed under the balance, with overdue ones in red.
- **Approval requests print as paper receipts**. They animate in like a receipt printer, have a
  torn zig-zag bottom, and show the amount, why it's needed, and which agent asked. Requests for the
  ticket you're looking at get a blue outline.
- **Approve & pay** slams a red **PAID** rubber stamp onto the receipt before it clears. You have to
  type your name at the desk first, because every payment records a named human approver. Agents
  can never approve. This is the only path that changes cash, and the backend refuses overdrafts.

## Resolved tickets

A ticket is resolved when the team's run is finished and nothing is waiting on an approval. That's
either right when the run ends, or the moment you approve or reject the last pending request for it.
A resolved ticket's receipt swaps its status pill for a navy **RESOLVED rubber stamp** that *thumps*
onto the paper, and the ticket header shows a clean navy **✓ RESOLVED** badge. The receipt fades back on the spike so open work stands out. A running
ticket's receipt pulses blue, and the top bar's "on air" light pulses blue and reads *team on shift · 2 at work*. When nobody is
working it turns into a little rose heart with a slow heartbeat: *floor is quiet*.

## Small things that make it a nice place to sit

- A **desk calendar** in the top bar shows the shop's date (Aug 31), not the real clock, which is
  the date every agent uses too.
- Paper stubs and receipts sit on a soft shadow over the white desk, so the physical things feel
  touchable next to the flat live data.
- **Fresh shift** resets the shop database for a new run and clears the floor. The audit trail is
  kept.
- A **token counter** under the run button shows what each run cost.
- Your name at the desk is remembered between visits.
- If the backend is down, a banner tells you exactly which command to run.
- All motion turns off for people who set *reduce motion* in their system settings.

## Why these choices

- **Physical metaphors (spike, register, receipts, stamps) for the human parts, live creatures for
  the AI parts.** The two kinds of actor look different on purpose, so it's always clear what the
  agents did versus what a person has to do.
- **Yale blue means "look here," red means "act now."** Everything else is muted gray and white,
  so live delegation, money, and pending approvals stand out without the page feeling busy, and the
  navy-and-white palette makes it feel like it belongs to a Yale shop.
- **Show the work, not just the result.** Plain-English bubbles, lit-up wires, and an indented wire
  make a multi-agent run understandable while it happens, and the shift report and dotted traces
  make it easy to compare against the Problem 6 plan afterwards.
