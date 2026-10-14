import type { AgentMeta, AgentStatus } from "../agents";

/** A little desk creature, built from plain HTML + CSS. Each role wears its own accessory. */
export function Creature({ meta, status, size = 64 }: { meta: AgentMeta; status: AgentStatus; size?: number }) {
  const style = { "--c": meta.color, "--s": `${size}px` } as React.CSSProperties;
  if (meta.shape === "bulldog") return <HandsomeDan status={status} style={style} />;
  return (
    <div className={`creature creature--${meta.shape} is-${status}`} style={style} aria-hidden>
      <div className="creature__accessory" />
      <div className="creature__body">
        <div className="creature__eyes">
          <span className="eye"><i /></span>
          <span className="eye"><i /></span>
        </div>
        <div className="creature__cheeks"><b /><b /></div>
        <div className="creature__mouth" />
      </div>
      <div className="creature__feet"><b /><b /></div>
      <div className="creature__shadow" />
    </div>
  );
}

/** Boss is Handsome Dan, Yale's bulldog: jowls, droopy ears, underbite, and a Y on his collar. */
function HandsomeDan({ status, style }: { status: AgentStatus; style: React.CSSProperties }) {
  return (
    <div className={`creature dan is-${status}`} style={style} aria-hidden>
      <div className="dan__ear dan__ear--l" />
      <div className="dan__ear dan__ear--r" />
      <div className="dan__head">
        <div className="dan__patch" />
        <div className="dan__brow" />
        <div className="creature__eyes dan__eyes">
          <span className="eye"><i /></span>
          <span className="eye"><i /></span>
        </div>
        <div className="creature__cheeks dan__cheeks"><b /><b /></div>
        <div className="dan__muzzle">
          <div className="dan__nose" />
          <div className="dan__jowl dan__jowl--l" />
          <div className="dan__jowl dan__jowl--r" />
          <div className="creature__mouth dan__mouth" />
          <div className="dan__teeth"><b /><b /></div>
        </div>
      </div>
      <div className="dan__collar"><span>Y</span></div>
      <div className="creature__shadow" />
    </div>
  );
}
