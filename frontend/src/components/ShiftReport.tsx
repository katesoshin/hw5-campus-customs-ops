import { AGENTS, type FloorState } from "../agents";
import type { AgentOutput, Draft } from "../types";
import { Creature } from "./Creature";

/** After the run: one card per agent that worked the ticket, plus Boss's wrap-up and the drafts left for a human. */
export function ShiftReport({ floor, boss, drafts }: { floor: FloorState; boss: AgentOutput | null; drafts: Draft[] }) {
  const worked = AGENTS.filter((a) => floor.agents[a.name].runs > 0);
  if (!worked.length) return <p className="empty">No shift report yet. It appears here when the team finishes the ticket.</p>;
  return (
    <div className="report">
      {boss && (
        <div className="report__boss">
          <div className="report__kicker">Boss's wrap-up · status <b>{boss.status?.replace(/_/g, " ")}</b></div>
          <p>{boss.summary}</p>
          {boss.cash_note && <p className="report__cash"><b>Cash:</b> {boss.cash_note}</p>}
          {!!boss.human_actions?.length && (
            <ul className="todo">
              {boss.human_actions.map((h, i) => <li key={i}>{h.description}</li>)}
            </ul>
          )}
        </div>
      )}
      <div className="report__grid">
        {worked.map((m) => {
          const s = floor.agents[m.name];
          const last = s.reports.at(-1);
          const uniqueTools = [...new Set(s.tools)];
          return (
            <article key={m.name} className={`card voice--${m.name}`} style={{ "--c": m.color } as React.CSSProperties}>
              <header>
                <Creature meta={m} status="done" size={34} />
                <div>
                  <h3>{m.label}</h3>
                  <small>{s.runs} {s.runs === 1 ? "turn" : "turns"} · {s.tools.length} tool calls</small>
                </div>
              </header>
              <p>{last?.summary ?? "—"}</p>
              {!!last?.actions_taken?.length && (
                <ul>{last.actions_taken.map((x, i) => <li key={i}>{x}</li>)}</ul>
              )}
              {!!last?.blockers?.length && <div className="card__blocker">Blocked: {last.blockers.join("; ")}</div>}
              <div className="chips">{uniqueTools.map((t) => <span key={t} className="chip"><code>{t}</code></span>)}</div>
            </article>
          );
        })}
      </div>
      {drafts.length > 0 && (
        <div className="drafts">
          <h3 className="section-title">Drafts waiting for a human to send <span>{drafts.length}</span></h3>
          {drafts.map((d) => (
            <details key={d.id} className="draft">
              <summary><b>#{d.id}</b> to {d.to_name}: “{d.subject}” <em>by {AGENTS.find((a) => a.name === d.author_agent)?.label}</em></summary>
              <pre>{d.body}</pre>
            </details>
          ))}
        </div>
      )}
    </div>
  );
}
