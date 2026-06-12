import { useState, useEffect } from "react";
import { api } from "../api.js";
import { fmtDate } from "../utils.js";

export default function AgentPage({ timezone = 'UTC' }) {
  const [token,   setToken]   = useState(null);
  const [status,  setStatus]  = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy,    setBusy]    = useState(false);
  const [msg,     setMsg]     = useState(null);
  const [showTok, setShowTok] = useState(false);

  const flash = (text, ok=true) => { setMsg({text,ok}); setTimeout(()=>setMsg(null),4000); };

  const load = () => {
    setLoading(true);
    Promise.all([
      api.agentToken().catch(()=>null),
      api.agentStatus().catch(()=>null),
    ]).then(([t, s]) => {
      setToken(t);
      setStatus(s);
      setLoading(false);
    });
  };

  useEffect(load, []);

  const regen = async () => {
    if (!window.confirm("Regenerate token? The current token will stop working immediately.")) return;
    setBusy(true);
    try {
      const r = await api.agentRegenToken();
      setToken(r);
      flash("Token regenerated");
    } catch(e) { flash(e.message||"Failed", false); }
    setBusy(false);
  };

  return (
    <div>
      <div className="df-page-title">Agent</div>
      <div className="df-page-sub">
        Remote agent API token and status
        {msg && <span style={{marginLeft:14,fontSize:11,fontFamily:"var(--mono)",color:msg.ok?"var(--green)":"var(--red)"}}>{msg.text}</span>}
      </div>

      {loading && <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)"}}>Loading…</div>}

      {!loading && (
        <div style={{maxWidth:560,display:"flex",flexDirection:"column",gap:14}}>
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">API Token</div></div>
            <div style={{fontSize:12,color:"var(--t1)",marginBottom:14,lineHeight:1.6}}>
              Use this token to authenticate remote agent commands. Keep it secret.
            </div>
            <div className="df-flex" style={{gap:8,marginBottom:12}}>
              <input
                className="df-s-input"
                readOnly
                type={showTok?"text":"password"}
                value={token?.token||"—"}
                style={{flex:1,fontFamily:"var(--mono)",fontSize:11}}
              />
              <button className="df-btn df-btn-sm" onClick={()=>setShowTok(s=>!s)}>{showTok?"Hide":"Show"}</button>
              <button className="df-btn df-btn-sm" onClick={()=>navigator.clipboard?.writeText(token?.token||"").then(()=>flash("Copied!"))}>Copy</button>
            </div>
            {token?.created_at && (
              <div style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)",marginBottom:14}}>
                Created: {fmtDate(token.created_at, timezone)}
              </div>
            )}
            <button className="df-btn df-btn-danger df-btn-sm" onClick={regen} disabled={busy}>Regenerate Token</button>
          </div>

          {status && (
            <div className="df-card">
              <div className="df-card-hdr"><div className="df-card-title">Agent Status</div></div>
              {Object.entries(status).map(([k,v])=>(
                <div key={k} className="df-hrow">
                  <span className="df-hname" style={{fontFamily:"var(--mono)"}}>{k}</span>
                  <span style={{fontFamily:"var(--mono)",fontSize:12,color:"var(--t0)"}}>{String(v)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
