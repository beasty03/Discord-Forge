import { useState, useEffect } from "react";
import { api } from "../api.js";

const EVENTS = ["bot_online","bot_offline","member_sync","command"];

export default function IntegrationsPage({ server }) {
  const [hooks,    setHooks]    = useState([]);
  const [sel,      setSel]      = useState(null);
  const [log,      setLog]      = useState([]);
  const [addOpen,  setAddOpen]  = useState(false);
  const [addForm,  setAddForm]  = useState({ name:"", url:"", channel:"" });
  const [busy,     setBusy]     = useState(false);
  const [msg,      setMsg]      = useState(null);

  const flash = (text, ok=true) => { setMsg({text,ok}); setTimeout(()=>setMsg(null),4000); };

  useEffect(() => {
    if (!server?.id) return;
    setSel(null); setHooks([]);
    api.integrations(server.id).catch(()=>null).then(r => { if (r) setHooks(r); });
  }, [server?.id]);

  useEffect(() => {
    if (!sel || !server?.id) return;
    api.integrationLog(server.id, sel.id).catch(()=>null).then(r => { if (r) setLog(r); });
  }, [sel?.id, server?.id]);

  const create = async () => {
    if (!addForm.url.startsWith("https://")) { flash("URL must start with https://", false); return; }
    if (!addForm.name.trim()) { flash("Name required", false); return; }
    setBusy(true);
    try {
      const r = await api.integrationCreate(server.id, addForm);
      setHooks(h => [...h, r.integration]);
      setAddForm({ name:"", url:"", channel:"" }); setAddOpen(false);
      flash("Webhook created");
    } catch(e) { flash(e.message||"Failed", false); }
    setBusy(false);
  };

  const del = async (wid) => {
    if (!window.confirm("Delete this webhook?")) return;
    await api.integrationDelete(server.id, wid).catch(()=>{});
    setHooks(h => h.filter(x => x.id !== wid));
    if (sel?.id === wid) setSel(null);
    flash("Deleted");
  };

  const test = async (wid) => {
    setBusy(true);
    try {
      await api.integrationTest(server.id, wid);
      flash("Test sent successfully");
      // refresh last_used
      api.integrations(server.id).then(r => { if(r) setHooks(r); });
    } catch(e) { flash(e.message||"Test failed", false); }
    setBusy(false);
  };

  const toggleEvent = async (wid, evt, hook) => {
    const current = hook.notify_events || [];
    const next = current.includes(evt) ? current.filter(e=>e!==evt) : [...current, evt];
    const updated = await api.integrationPatch(server.id, wid, { notify_events: next }).catch(()=>null);
    if (updated) {
      setHooks(h => h.map(x => x.id===wid ? {...x, notify_events: next} : x));
      if (sel?.id===wid) setSel(s => ({...s, notify_events: next}));
    }
  };

  return (
    <div>
      <div className="df-page-title">Integrations</div>
      <div className="df-page-sub">
        Notification webhooks for {server?.name||"—"}
        {msg && <span style={{marginLeft:14,fontSize:11,fontFamily:"var(--mono)",color:msg.ok?"var(--green)":"var(--red)"}}>{msg.text}</span>}
      </div>

      <div style={{display:"grid",gridTemplateColumns:sel?"1fr 360px":"1fr",gap:14}}>
        <div>
          <div className="df-card" style={{marginBottom:14}}>
            <div className="df-card-hdr">
              <div className="df-card-title">Webhooks ({hooks.length})</div>
              <button className="df-btn df-btn-accent df-btn-sm" onClick={()=>setAddOpen(o=>!o)}>+ Add</button>
            </div>
            {addOpen && (
              <div style={{display:"flex",flexDirection:"column",gap:8,padding:"12px 0",borderBottom:"1px solid var(--border)",marginBottom:8}}>
                <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:8}}>
                  <input className="df-s-input" placeholder="Webhook name" value={addForm.name} onChange={e=>setAddForm(f=>({...f,name:e.target.value}))}/>
                  <input className="df-s-input" placeholder="#channel (label only)" value={addForm.channel} onChange={e=>setAddForm(f=>({...f,channel:e.target.value}))}/>
                </div>
                <input className="df-s-input" placeholder="https://discord.com/api/webhooks/..." value={addForm.url} onChange={e=>setAddForm(f=>({...f,url:e.target.value}))}/>
                <div className="df-flex">
                  <button className="df-btn df-btn-accent df-btn-sm" onClick={create} disabled={busy}>Create</button>
                  <button className="df-btn df-btn-sm" onClick={()=>setAddOpen(false)}>Cancel</button>
                </div>
              </div>
            )}
            {hooks.length === 0
              ? <div style={{fontSize:12,color:"var(--t2)",padding:"12px 0",fontFamily:"var(--mono)"}}>No webhooks yet. Click + Add to create one.</div>
              : hooks.map(h => (
                <div key={h.id} className="df-hrow" style={{cursor:"pointer",background:sel?.id===h.id?"var(--accent3)":undefined}} onClick={()=>setSel(sel?.id===h.id?null:h)}>
                  <div style={{flex:1}}>
                    <div style={{fontSize:13,fontWeight:600}}>{h.name}</div>
                    <div style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>{h.channel||"—"} · last used: {h.last_used?h.last_used.slice(0,16):"never"}</div>
                  </div>
                  <button className="df-btn df-btn-sm" style={{marginRight:6}} onClick={e=>{e.stopPropagation();test(h.id);}} disabled={busy}>Test</button>
                  <button className="df-btn df-btn-danger df-btn-sm" onClick={e=>{e.stopPropagation();del(h.id);}}>Delete</button>
                </div>
              ))
            }
          </div>
        </div>

        {sel && (
          <div>
            <div className="df-card" style={{marginBottom:14}}>
              <div className="df-card-hdr">
                <div className="df-card-title">{sel.name}</div>
                <button className="df-btn df-btn-sm" onClick={()=>setSel(null)}>✕</button>
              </div>
              <div style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)",marginBottom:14,wordBreak:"break-all"}}>{sel.url}</div>

              <div style={{fontSize:12,fontWeight:700,color:"var(--t1)",marginBottom:8}}>Notify on events</div>
              {EVENTS.map(evt => {
                const on = (sel.notify_events||[]).includes(evt);
                return (
                  <div key={evt} className="df-hrow" style={{cursor:"pointer"}} onClick={()=>toggleEvent(sel.id,evt,sel)}>
                    <div style={{flex:1,fontSize:12,fontFamily:"var(--mono)"}}>{evt}</div>
                    <div style={{width:14,height:14,borderRadius:3,border:"1.5px solid var(--border2)",background:on?"var(--accent)":"var(--bg3)",display:"flex",alignItems:"center",justifyContent:"center",flexShrink:0}}>
                      {on&&<span style={{fontSize:9,color:"#fff",fontWeight:700}}>✓</span>}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="df-card">
              <div className="df-card-hdr"><div className="df-card-title">Fire Log</div><span style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>last 20</span></div>
              {log.length===0
                ? <div style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>No fires yet.</div>
                : log.map((l,i) => (
                  <div key={i} className="df-hrow" style={{fontSize:11,fontFamily:"var(--mono)"}}>
                    <span style={{color:"var(--t2)",minWidth:110}}>{l.ts?.slice(0,16)}</span>
                    <span style={{flex:1,color:"var(--t1)"}}>{l.event}: {l.msg}</span>
                    <span style={{color:l.ok?"var(--green)":"var(--red)",fontWeight:700}}>{l.ok?"ok":"fail"}</span>
                  </div>
                ))
              }
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
