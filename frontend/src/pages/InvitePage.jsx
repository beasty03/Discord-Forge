import { useState, useEffect } from "react";
import { api } from "../api.js";

const INV_CSS = `
.inv-wrap{min-height:100vh;background:var(--bg0);display:flex;align-items:center;justify-content:center;padding:24px}
.inv-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:36px 40px;width:100%;max-width:440px;text-align:center}
.inv-icon{font-size:40px;margin-bottom:14px}
.inv-title{font-size:22px;font-weight:800;letter-spacing:-.5px;margin-bottom:6px}
.inv-sub{font-size:13px;color:var(--t1);margin-bottom:24px;line-height:1.6}
.inv-perms{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin-bottom:24px}
.inv-err{background:rgba(240,90,90,.1);border:1px solid rgba(240,90,90,.25);border-radius:var(--r);padding:10px 14px;font-size:12px;color:var(--red);margin-bottom:14px;font-family:var(--mono)}
.inv-ok{background:rgba(35,209,139,.1);border:1px solid rgba(35,209,139,.25);border-radius:var(--r);padding:14px;font-size:13px;color:var(--green);line-height:1.6}
`;

export default function InvitePage({ token, onDone }) {
  const [invite,  setInvite]  = useState(null);
  const [loading, setLoading] = useState(true);
  const [err,     setErr]     = useState(null);
  const [ok,      setOk]      = useState(null);
  const [busy,    setBusy]    = useState(false);

  useEffect(() => {
    api.fetchInvite(token).catch(()=>null).then(r => {
      setLoading(false);
      if (!r) setErr("This invite link is invalid, expired, or already used.");
      else    setInvite(r);
    });
  }, [token]);

  const accept = async () => {
    setBusy(true);
    try {
      const r = await api.acceptInvite(token);
      if (r?.ok) setOk(`You now have access to ${invite?.server_name||"the server"}!`);
      else        setErr(r?.error || "Could not accept invite.");
    } catch(e) { setErr(e.message || "Network error."); }
    setBusy(false);
  };

  return (
    <>
      <style>{INV_CSS}</style>
      <div className="inv-wrap">
        <div className="inv-card">
          <div className="inv-icon">🤝</div>
          {loading && <div style={{color:"var(--t2)",fontFamily:"var(--mono)",fontSize:13}}>Loading invite…</div>}
          {err && !ok && (
            <>
              <div className="inv-title">Invite Error</div>
              <div className="inv-err">{err}</div>
              <button className="df-btn df-btn-sm" onClick={onDone}>Go to Dashboard</button>
            </>
          )}
          {invite && !ok && (
            <>
              <div className="inv-title">You're invited!</div>
              <div className="inv-sub">
                <strong>{invite.created_by}</strong> has invited you to collaborate on<br/>
                <strong>{invite.server_name}</strong>
              </div>
              <div style={{fontSize:11,color:"var(--t2)",marginBottom:10,textTransform:"uppercase",letterSpacing:".8px"}}>Permissions granted</div>
              <div className="inv-perms">
                {(invite.permissions||[]).map(p=>(
                  <span key={p} className="df-badge df-bb">{p}</span>
                ))}
              </div>
              <button className="df-btn df-btn-accent" style={{width:"100%",padding:"11px"}} onClick={accept} disabled={busy}>
                {busy?"Accepting…":"Accept Invite"}
              </button>
            </>
          )}
          {ok && (
            <>
              <div className="inv-title">Access Granted</div>
              <div className="inv-ok" style={{marginBottom:20}}>{ok}</div>
              <button className="df-btn df-btn-accent df-btn-sm" onClick={onDone}>Go to Dashboard</button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
