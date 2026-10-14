import { useEffect, useRef } from "react";
import { META, describeTool } from "../agents";
import type { AgentEvent } from "../types";

const time = (ts: string) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/** The live wire: every event of the run, color-coded by agent and indented by delegation depth. */
export function Wire({ events }: { events: AgentEvent[] }) {
  const list = useRef<HTMLOListElement>(null);
  useEffect(() => {
    // keep the newest line in view inside the panel, without scrolling the whole page
    const panel = list.current?.parentElement;
    if (panel) panel.scrollTo({ top: panel.scrollHeight, behavior: "smooth" });
  }, [events.length]);
  if (!events.length) return <p className="empty">Nothing on the wire yet. Send this ticket to the team to watch them work.</p>;
  return (
    <ol className="wire-feed" ref={list}>
      {events.map((e, i) => {
        const m = META[e.agent];
        let text: React.ReactNode = e.said;
        if (e.event === "run_start") text = e.depth === 0 ? "clocks in on the ticket" : <>picks up: <q>{e.said}</q></>;
        if (e.event === "delegation") text = <>→ <b style={{ color: META[e.delegate_to!].color }}>{META[e.delegate_to!].label}</b>: <q>{e.said}</q></>;
        if (e.event === "run_end") text = <>reports back: {e.output?.summary}</>;
        if (e.event === "run_error") text = <>hit an error: {e.said}</>;
        return (
          <li key={i} className={`wire-row wire-row--${e.event} voice--${e.agent}`} style={{ "--c": m.color, "--d": e.depth } as React.CSSProperties}>
            <time>{time(e.ts)}</time>
            <span className="wire-row__who">{m.label}</span>
            <div className="wire-row__body">
              {text && <div className="wire-row__text">{text}</div>}
              {e.tools.length > 0 && (
                <div className="chips">
                  {e.tools.map((t, j) => (
                    <span key={j} className="chip" title={JSON.stringify(t.args)}>
                      <code>{t.tool}</code> {t.tool !== "delegate" && <span>{describeTool(t)}</span>}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
