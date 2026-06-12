import { useState, useEffect } from "react";
import { api } from "../api.js";
import { fmtDate } from "../utils.js";

const TYPE_COLOR = {
  bot_online:   "var(--green)",
  bot_offline:  "var(--red)",
  member_sync:  "var(--cyan)",
  setup:        "var(--accent2)",
  rename:       "var(--yellow)",
  collab_add:   "var(--purple)",
  collab_remove:"var(--red)",
  collab_invite:"var(--purple)",
  command:      "var(--t1)",
};

export default function ActivityPage({ server, timezone = 'UTC' }) {
  const [events,  setEvents]  = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter,  setFilter]  = useState("all");

  useEffect(() => {
    if (!server?.id) return;
    setEvents([]); setLoading(true);
    api.envEvents(server.id).catch(()=>null).then(r => {
      setEvents(Array.isArray(r) ? r : []);
      setLoading(false);
    });
  }, [server?.id]);

  const types = ["all", ...new Set(events.map(e=>e.type).filter(Boolean))];
  const filtered = filter==="all" ? events : events.filter(e=>e.type===filter);

  const exportCSV = () => {
    const rows = [["Timestamp","Type","Actor","Description"],...filtered.map(e=>[e.ts,e.type,e.actor||"",e.description||""])];
    const csv  = rows.map(r=>r.map(c=>`"${String(c).replace(/"/g,'""')}"`).join(",")).join("\n");
    const a    = document.createElement("a");
    a.href = "data:text/csv;charset=utf-8," + encodeURIComponent(csv);
    a.download = `activity_${server?.id}_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
  };

  return (
    <div>
      <div className="df-page-title">Activity Log</div>
      <div className="df-page-sub">{server?.name||"—"} · {filtered.length} events</div>

      <div className="df-flex" style={{gap:8,marginBottom:14,flexWrap:"wrap"}}>
        {types.map(t => (
          <div key={t} className={`df-filter-chip ${filter===t?"active":""}`} onClick={()=>setFilter(t)} style={{whiteSpace:"nowrap"}}>
            {t}
          </div>
        ))}
        <div style={{flex:1}}/>
        <button className="df-btn df-btn-sm" onClick={exportCSV} disabled={!filtered.length}>Export CSV</button>
      </div>

      <div className="df-card">
        {loading && <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)",padding:"12px 0"}}>Loading…</div>}
        {!loading && filtered.length===0 && (
          <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)",padding:"12px 0"}}>No events yet for this server.</div>
        )}
        {filtered.map((e,i) => (
          <div key={i} className="df-hrow" style={{gap:12,alignItems:"flex-start"}}>
            <span style={{fontSize:18,lineHeight:1,flexShrink:0}}>{e.icon||"📌"}</span>
            <div style={{flex:1,minWidth:0}}>
              <div style={{display:"flex",alignItems:"center",gap:8,flexWrap:"wrap"}}>
                <span style={{fontSize:11,fontFamily:"var(--mono)",padding:"2px 7px",borderRadius:20,background:"var(--bg3)",color:TYPE_COLOR[e.type]||"var(--t1)",fontWeight:600,border:`1px solid ${TYPE_COLOR[e.type]||"var(--border)"}30`}}>
                  {e.type||"event"}
                </span>
                {e.actor && <span style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>by {e.actor}</span>}
              </div>
              <div style={{fontSize:12,color:"var(--t1)",marginTop:3,lineHeight:1.5}}>{e.description}</div>
            </div>
            <span style={{fontSize:10,color:"var(--t2)",fontFamily:"var(--mono)",whiteSpace:"nowrap",flexShrink:0}}>
              {fmtDate(e.ts, timezone)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
