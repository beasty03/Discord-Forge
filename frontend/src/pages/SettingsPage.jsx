import { useState, useEffect } from "react";
import { api } from "../api.js";

export default function SettingsPage({ server, onServerDeleted }) {
  const [form,     setForm]     = useState({ server_name:"", env_name:"" });
  const [busy,     setBusy]     = useState(false);
  const [delInput, setDelInput] = useState("");
  const [msg,      setMsg]      = useState(null);

  const flash = (text, ok=true) => { setMsg({text,ok}); setTimeout(()=>setMsg(null),5000); };

  useEffect(() => {
    if (!server?.id) return;
    setForm({ server_name: server.name||"", env_name: server.name||"" });
  }, [server?.id]);

  const save = async () => {
    if (!form.server_name.trim()) { flash("Server name cannot be empty", false); return; }
    setBusy(true);
    try {
      await api.serverSettings(server.id, { server_name: form.server_name.trim() });
      flash("Settings saved");
    } catch(e) { flash(e.message||"Save failed", false); }
    setBusy(false);
  };

  const rename = async () => {
    if (!form.env_name.trim()) { flash("Name cannot be empty", false); return; }
    setBusy(true);
    try {
      await api.renameEnv(server.id, form.env_name.trim());
      flash("Environment renamed");
    } catch(e) { flash(e.message||"Rename failed", false); }
    setBusy(false);
  };

  const deleteServer = async () => {
    if (delInput !== server?.name) { flash("Type the server name exactly to confirm", false); return; }
    setBusy(true);
    try {
      await api.deleteServer(server.id);
      onServerDeleted?.();
    } catch(e) { flash(e.message||"Delete failed", false); setBusy(false); }
  };

  return (
    <div>
      <div className="df-page-title">Settings</div>
      <div className="df-page-sub">
        Environment configuration for {server?.name||"—"}
        {msg && <span style={{marginLeft:14,fontSize:11,fontFamily:"var(--mono)",color:msg.ok?"var(--green)":"var(--red)"}}>{msg.text}</span>}
      </div>

      <div style={{maxWidth:580,display:"flex",flexDirection:"column",gap:14}}>
        {/* General settings */}
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">General</div></div>
          <div className="df-sgap">
            <div className="df-setting-row">
              <div><div className="df-s-label">Server Name</div><div className="df-s-hint">Display name in DiscordForge</div></div>
              <input className="df-s-input" value={form.server_name} onChange={e=>setForm(f=>({...f,server_name:e.target.value}))} maxLength={80}/>
            </div>
          </div>
          <div className="df-flex df-mt14">
            <button className="df-btn df-btn-accent df-btn-sm" onClick={save} disabled={busy}>{busy?"Saving…":"Save"}</button>
            <button className="df-btn df-btn-sm" onClick={()=>setForm(f=>({...f,server_name:server?.name||""}))}>Reset</button>
          </div>
        </div>

        {/* Environment label */}
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">Environment Label</div></div>
          <div style={{fontSize:12,color:"var(--t1)",marginBottom:12}}>
            A friendly display label separate from the server name, used in activity logs.
          </div>
          <div className="df-setting-row">
            <div className="df-s-label">Label</div>
            <input className="df-s-input" value={form.env_name} onChange={e=>setForm(f=>({...f,env_name:e.target.value}))} maxLength={80}/>
          </div>
          <div className="df-flex df-mt14">
            <button className="df-btn df-btn-accent df-btn-sm" onClick={rename} disabled={busy}>Rename</button>
          </div>
        </div>

        {/* Info */}
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">Environment Info</div></div>
          {[
            ["Server ID",  server?.id||"—"],
            ["Guild ID",   server?.guild_id||"—"],
            ["Boost Tier", `Level ${server?.boostLevel||0}`],
            ["Boosts",     server?.boosts||0],
          ].map(([k,v])=>(
            <div key={k} className="df-hrow">
              <span className="df-hname">{k}</span>
              <span style={{fontFamily:"var(--mono)",fontSize:12,color:"var(--t0)"}}>{v}</span>
            </div>
          ))}
        </div>

        {/* Danger zone */}
        <div className="df-card" style={{border:"1px solid rgba(240,90,90,.25)"}}>
          <div className="df-card-hdr"><div className="df-card-title" style={{color:"var(--red)"}}>Danger Zone</div></div>
          <div style={{fontSize:12,color:"var(--t1)",marginBottom:14,lineHeight:1.6}}>
            Permanently deletes this server environment and all its data including the installation directory.
            This cannot be undone.
          </div>
          <div style={{fontSize:11,color:"var(--t2)",marginBottom:6}}>
            Type <span style={{fontFamily:"var(--mono)",color:"var(--t0)"}}>{server?.name}</span> to confirm:
          </div>
          <div className="df-flex" style={{gap:8}}>
            <input
              className="df-s-input"
              placeholder={server?.name}
              value={delInput}
              onChange={e=>setDelInput(e.target.value)}
              style={{flex:1}}
            />
            <button
              className="df-btn df-btn-danger df-btn-sm"
              onClick={deleteServer}
              disabled={busy || delInput !== server?.name}
            >
              Delete Server
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
