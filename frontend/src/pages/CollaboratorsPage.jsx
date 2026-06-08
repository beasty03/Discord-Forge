import { useState, useEffect } from "react";
import { api } from "../api.js";

const ALL_PERMS = ["view_server","edit_server","view_bots","edit_bots"];

export default function CollaboratorsPage({ server }) {
  const [collabs,   setCollabs]   = useState({});
  const [editing,   setEditing]   = useState(null); // username being edited
  const [editPerms, setEditPerms] = useState([]);
  const [invitePerms, setInvitePerms] = useState(["view_server"]);
  const [inviteLink,  setInviteLink]  = useState(null);
  const [msg,       setMsg]       = useState(null);

  const flash = (text, ok=true) => { setMsg({text,ok}); setTimeout(()=>setMsg(null),4000); };

  useEffect(() => {
    if (!server?.id) return;
    setCollabs({}); setEditing(null); setInviteLink(null);
    api.collaborators(server.id).catch(()=>null).then(r => {
      if (r?.collaborators) setCollabs(r.collaborators);
    });
  }, [server?.id]);

  const startEdit = (username, data) => {
    setEditing(username);
    const existing = Array.isArray(data) ? data : (data?.permissions || []);
    setEditPerms([...existing]);
  };

  const saveEdit = async () => {
    try {
      await api.collaboratorUpdate(server.id, editing, editPerms);
      setCollabs(c => ({...c, [editing]: {...(c[editing]||{}), permissions: editPerms}}));
      setEditing(null);
      flash("Permissions updated");
    } catch(e) { flash(e.message||"Failed", false); }
  };

  const remove = async (username) => {
    if (!window.confirm(`Remove ${username} as collaborator?`)) return;
    await api.collaboratorRemove(server.id, username).catch(()=>{});
    setCollabs(c => { const n={...c}; delete n[username]; return n; });
    flash("Collaborator removed");
  };

  const createInvite = async () => {
    if (!invitePerms.length) { flash("Select at least one permission", false); return; }
    try {
      const r = await api.inviteCreate(server.id, invitePerms);
      const base = window.location.origin;
      setInviteLink(base + r.invite_url);
      flash("Invite link created — valid for 7 days");
    } catch(e) { flash(e.message||"Failed", false); }
  };

  const entries = Object.entries(collabs);

  return (
    <div>
      <div className="df-page-title">Collaborators</div>
      <div className="df-page-sub">
        Manage team access for {server?.name||"—"}
        {msg && <span style={{marginLeft:14,fontSize:11,fontFamily:"var(--mono)",color:msg.ok?"var(--green)":"var(--red)"}}>{msg.text}</span>}
      </div>

      <div className="df-g2">
        <div>
          <div className="df-card" style={{marginBottom:14}}>
            <div className="df-card-hdr"><div className="df-card-title">Current Collaborators ({entries.length})</div></div>
            {entries.length === 0
              ? <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)",padding:"8px 0"}}>No collaborators yet. Generate an invite link to add people.</div>
              : entries.map(([username, data]) => {
                  const perms = Array.isArray(data) ? data : (data?.permissions || []);
                  const isEditing = editing === username;
                  return (
                    <div key={username} style={{padding:"10px 0",borderBottom:"1px solid var(--border)"}}>
                      <div className="df-flex" style={{marginBottom:6}}>
                        <div style={{flex:1}}>
                          <div style={{fontSize:13,fontWeight:700}}>{username}</div>
                          {data?.added_at && <div style={{fontSize:10,color:"var(--t2)",fontFamily:"var(--mono)"}}>added {data.added_at?.slice(0,10)}</div>}
                        </div>
                        <button className="df-btn df-btn-sm" style={{marginRight:6}} onClick={()=>isEditing?setEditing(null):startEdit(username,data)}>
                          {isEditing?"Cancel":"Edit"}
                        </button>
                        <button className="df-btn df-btn-danger df-btn-sm" onClick={()=>remove(username)}>Remove</button>
                      </div>

                      {!isEditing && (
                        <div style={{display:"flex",flexWrap:"wrap",gap:5}}>
                          {perms.map(p=><span key={p} className="df-badge df-bb">{p}</span>)}
                          {perms.length===0&&<span style={{fontSize:11,color:"var(--t2)"}}>no permissions</span>}
                        </div>
                      )}

                      {isEditing && (
                        <div>
                          <div style={{display:"flex",flexWrap:"wrap",gap:8,marginBottom:10}}>
                            {ALL_PERMS.map(p => {
                              const on = editPerms.includes(p);
                              return (
                                <label key={p} style={{display:"flex",alignItems:"center",gap:5,cursor:"pointer",fontSize:12,userSelect:"none"}}>
                                  <input type="checkbox" checked={on} onChange={()=>setEditPerms(ps=>on?ps.filter(x=>x!==p):[...ps,p])}/>
                                  {p}
                                </label>
                              );
                            })}
                          </div>
                          <button className="df-btn df-btn-accent df-btn-sm" onClick={saveEdit}>Save</button>
                        </div>
                      )}
                    </div>
                  );
                })
            }
          </div>
        </div>

        <div className="df-card" style={{alignSelf:"start"}}>
          <div className="df-card-hdr"><div className="df-card-title">Create Invite Link</div></div>
          <div style={{fontSize:12,color:"var(--t1)",marginBottom:12,lineHeight:1.5}}>
            Generate a one-time link (7 days). The recipient logs in and clicks the link to join.
          </div>

          <div style={{fontSize:11,fontWeight:700,color:"var(--t2)",marginBottom:8,textTransform:"uppercase",letterSpacing:".8px"}}>Permissions to grant</div>
          {ALL_PERMS.map(p => {
            const on = invitePerms.includes(p);
            return (
              <label key={p} style={{display:"flex",alignItems:"center",gap:8,padding:"5px 0",cursor:"pointer",fontSize:13,userSelect:"none"}}>
                <input type="checkbox" checked={on} onChange={()=>setInvitePerms(ps=>on?ps.filter(x=>x!==p):[...ps,p])}/>
                {p}
              </label>
            );
          })}

          <button className="df-btn df-btn-accent df-btn-sm" style={{marginTop:14,width:"100%"}} onClick={createInvite}>
            Generate Invite Link
          </button>

          {inviteLink && (
            <div style={{marginTop:12}}>
              <div style={{fontSize:11,color:"var(--t2)",marginBottom:4}}>Share this link:</div>
              <div style={{display:"flex",gap:6}}>
                <input className="df-s-input" readOnly value={inviteLink} style={{flex:1,fontSize:11,fontFamily:"var(--mono)"}}/>
                <button className="df-btn df-btn-sm" onClick={()=>navigator.clipboard?.writeText(inviteLink).then(()=>flash("Copied!"))}>Copy</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
