import { useState } from "react";
import { AGENTS, META, type FloorState } from "../agents";
import type { AgentName } from "../types";
import { Creature } from "./Creature";

const STATUS_LABEL = { idle: "on break", working: "working", waiting: "waiting", done: "done", error: "hit a snag" };

function pairs(): [AgentName, AgentName][] {
  const out: [AgentName, AgentName][] = [];
  AGENTS.forEach((a, i) => AGENTS.slice(i + 1).forEach((b) => out.push([a.name, b.name])));
  return out;
}

/** The floor: five stations wired to each other (full connectivity), live delegations glow. */
export function Floor({ floor }: { floor: FloorState }) {
  const [pinned, setPinned] = useState<AgentName | null>(null); // a bubble clicked open stays open
  const isActive = (a: AgentName, b: AgentName) => floor.activeEdges.some((e) => e.from === a && e.to === b);
  const wasUsed = (a: AgentName, b: AgentName) => floor.usedEdges.some((e) => (e.from === a && e.to === b) || (e.from === b && e.to === a));
  return (
    <div className="floor">
      <svg className="floor__wires" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden>
        {pairs().map(([a, b]) => {
          const A = META[a], B = META[b];
          const live = isActive(a, b) || isActive(b, a);
          const [from, to] = isActive(b, a) ? [B, A] : [A, B];
          return (
            <line
              key={`${a}-${b}`}
              x1={from.x} y1={from.y} x2={to.x} y2={to.y}
              className={`wire ${live ? "wire--live" : wasUsed(a, b) ? "wire--used" : ""}`}
              vectorEffect="non-scaling-stroke"
            />
          );
        })}
      </svg>
      {AGENTS.map((m) => {
        const s = floor.agents[m.name];
        return (
          <div
            key={m.name}
            className={`station station--${m.name} is-${s.status}`}
            style={{ left: `clamp(var(--edge), ${m.x}%, calc(100% - var(--edge)))`, top: `${m.y}%`, "--c": m.color } as React.CSSProperties}
          >
            <Creature meta={m} status={s.status} size={m.name === "boss" ? 70 : 58} />
            <div className="station__name">{m.label}{s.runs > 1 && <sup>×{s.runs}</sup>}</div>
            <div className="station__role">{m.role} · <em>{STATUS_LABEL[s.status]}</em></div>
            {s.line && (
              <button
                className={`bubble bubble--${m.name} ${pinned === m.name ? "is-open" : ""}`}
                key={s.line}
                title={pinned === m.name ? "Click to fold" : "Hover to read it all, click to keep it open"}
                onClick={() => setPinned(pinned === m.name ? null : m.name)}
              >
                {s.line}
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}
