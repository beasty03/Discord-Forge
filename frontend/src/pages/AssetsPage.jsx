import { useState, useEffect, useRef } from "react";
import { api } from "../api.js";

const ACCEPT = { emoji: "image/png,image/gif,image/jpeg,image/webp", stickers: "image/png,image/gif,image/apng", soundboard: "audio/mp3,audio/mpeg,audio/ogg,audio/wav,audio/mp4" };
const ICON   = { emoji: "😄", stickers: "🎨", soundboard: "🔊" };

function toDataURL(file) {
  return new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = e => res(e.target.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });
}

function AssetRow({ item, onRemove }) {
  return (
    <div style={{display:'flex',alignItems:'center',gap:10,padding:'7px 10px',background:'var(--bg3)',borderRadius:'var(--r)',marginBottom:6}}>
      {item.file_data && (
        item.file_data.startsWith('data:image')
          ? <img src={item.file_data} alt="" style={{width:32,height:32,borderRadius:4,objectFit:'cover',flexShrink:0}}/>
          : <span style={{width:32,height:32,display:'flex',alignItems:'center',justifyContent:'center',fontSize:18,flexShrink:0}}>🔊</span>
      )}
      <div style={{flex:1}}>
        <div style={{fontSize:12,fontWeight:600,color:'var(--t0)'}}>{item.name||'Unnamed'}</div>
        {item.description&&<div style={{fontSize:11,color:'var(--t2)'}}>{item.description}</div>}
        {item.tags&&<div style={{fontSize:10,fontFamily:'var(--mono)',color:'var(--t2)'}}>{item.tags}</div>}
        {!item.file_data&&<div style={{fontSize:10,color:'var(--yellow)',fontFamily:'var(--mono)'}}>⚠ no file — push will skip</div>}
      </div>
      <button onClick={onRemove} style={{background:'transparent',border:'none',color:'var(--red)',cursor:'pointer',fontSize:16,padding:'0 4px',flexShrink:0}}>✕</button>
    </div>
  );
}

function AddAssetForm({ type, onAdd, onClose }) {
  const [name, setName]   = useState('');
  const [desc, setDesc]   = useState('');
  const [tags, setTags]   = useState('');
  const [file, setFile]   = useState(null);
  const [prev, setPrev]   = useState(null);
  const [busy, setBusy]   = useState(false);

  const handleFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    const data = await toDataURL(f);
    setFile(data);
    if (data.startsWith('data:image')) setPrev(data);
    if (!name) setName(f.name.replace(/\.[^.]+$/, '').replace(/[^a-z0-9_]/gi, '_').slice(0, 32));
  };

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    const item = { name: name.trim(), file_data: file || null };
    if (type === 'stickers') { item.description = desc; item.tags = tags; }
    await onAdd(item);
    setBusy(false);
  };

  return (
    <div style={{background:'var(--bg3)',border:'1px solid var(--border2)',borderRadius:'var(--r)',padding:14,marginBottom:14}}>
      <div style={{display:'flex',alignItems:'center',gap:8,marginBottom:12}}>
        <span style={{fontSize:13,fontWeight:700,color:'var(--t0)'}}>New {type.replace(/s$/,'')} {ICON[type]}</span>
        <button onClick={onClose} style={{marginLeft:'auto',background:'transparent',border:'none',color:'var(--t2)',cursor:'pointer',fontSize:14}}>✕</button>
      </div>
      <div style={{display:'flex',gap:10,marginBottom:10,flexWrap:'wrap'}}>
        <input
          style={{flex:1,minWidth:120,background:'var(--bg2)',border:'1px solid var(--border2)',color:'var(--t0)',fontFamily:'var(--mono)',fontSize:12,padding:'5px 9px',borderRadius:'var(--r)',outline:'none'}}
          placeholder="name (letters, digits, _)"
          value={name}
          onChange={e=>setName(e.target.value.replace(/[^a-z0-9_]/gi,'_').slice(0,32))}
        />
        {type==='stickers'&&<>
          <input style={{flex:1,minWidth:120,background:'var(--bg2)',border:'1px solid var(--border2)',color:'var(--t0)',fontFamily:'var(--mono)',fontSize:12,padding:'5px 9px',borderRadius:'var(--r)',outline:'none'}} placeholder="description" value={desc} onChange={e=>setDesc(e.target.value.slice(0,100))}/>
          <input style={{flex:1,minWidth:100,background:'var(--bg2)',border:'1px solid var(--border2)',color:'var(--t0)',fontFamily:'var(--mono)',fontSize:12,padding:'5px 9px',borderRadius:'var(--r)',outline:'none'}} placeholder="tags (comma-sep)" value={tags} onChange={e=>setTags(e.target.value.slice(0,200))}/>
        </>}
      </div>
      <div style={{display:'flex',alignItems:'center',gap:10}}>
        {prev&&<img src={prev} alt="" style={{width:40,height:40,borderRadius:4,objectFit:'cover',border:'1px solid var(--border2)'}}/>}
        <label style={{cursor:'pointer'}}>
          <span style={{fontSize:12,fontWeight:600,padding:'5px 12px',borderRadius:'var(--r)',border:'1px solid var(--border2)',background:'var(--bg2)',color:'var(--t1)',display:'inline-block'}}>
            {file ? '✓ File chosen' : `Choose ${type==='soundboard'?'Audio':'Image'}`}
          </span>
          <input type="file" accept={ACCEPT[type]} style={{display:'none'}} onChange={handleFile}/>
        </label>
        <button
          disabled={busy||!name.trim()}
          onClick={submit}
          style={{fontSize:12,fontWeight:700,padding:'5px 16px',borderRadius:'var(--r)',border:'1px solid var(--accent)',background:'var(--accent)',color:'#fff',cursor:busy||!name.trim()?'not-allowed':'pointer',opacity:!name.trim()?0.5:1}}
        >
          {busy?'Adding…':'Add'}
        </button>
      </div>
    </div>
  );
}

export default function AssetsPage({ server }) {
  const [assets,    setAssets]    = useState({ emoji:[], stickers:[], soundboard:[] });
  const [live,      setLive]      = useState(null);
  const [loading,   setLoading]   = useState(true);
  const [pushing,   setPushing]   = useState(false);
  const [addingFor, setAddingFor] = useState(null); // 'emoji'|'stickers'|'soundboard'|null
  const [msg,       setMsg]       = useState(null);

  const flash = (text, ok=true) => {
    setMsg({text,ok});
    setTimeout(()=>setMsg(null),5000);
    window.dispatchEvent(new CustomEvent('df:toast',{detail:{text,type:ok?'success':'error'}}));
  };

  const load = () => {
    if (!server?.id) return;
    setLoading(true);
    Promise.all([
      api.assets(server.id).catch(()=>null),
      api.assetsLive(server.id).catch(()=>null),
    ]).then(([cfg, lv]) => {
      if (cfg?.assets || cfg?.emoji) {
        const a = cfg.assets || cfg;
        setAssets({ emoji: a.emoji||[], stickers: a.stickers||[], soundboard: a.soundboard||[] });
      }
      setLive(lv);
      setLoading(false);
    });
  };

  useEffect(load, [server?.id]);

  const saveAssets = async (next) => {
    try {
      await api.assetsPost(server.id, { assets: next });
      setAssets(next);
      flash('Assets saved');
    } catch(e) { flash(e.message||'Save failed', false); }
  };

  const addItem = async (type, item) => {
    const next = { ...assets, [type]: [...(assets[type]||[]), item] };
    await saveAssets(next);
    setAddingFor(null);
  };

  const removeItem = (type, idx) => {
    const next = { ...assets, [type]: assets[type].filter((_,i)=>i!==idx) };
    saveAssets(next);
  };

  const push = async () => {
    setPushing(true);
    try {
      const res = await api.assetsPush(server.id);
      if (res?.ok) { flash('Assets pushed to Discord'); load(); }
      else flash(res?.error||'Push failed', false);
    } catch(e) { flash(e.message||'Push failed', false); }
    setPushing(false);
  };

  const liveSync = (type) => {
    const lv    = live?.[type]||[];
    const cfg   = assets[type]||[];
    const lvSet = new Set(lv.map(a=>(a.name||'').toLowerCase()));
    const cfSet = new Set(cfg.map(a=>(a.name||'').toLowerCase()));
    return {
      missing: cfg.filter(a=>!lvSet.has((a.name||'').toLowerCase())),
      extra:   lv.filter(a=>!cfSet.has((a.name||'').toLowerCase())),
      live:    lv,
    };
  };

  return (
    <div>
      <div className="df-page-title">Assets</div>
      <div className="df-page-sub" style={{display:'flex',alignItems:'center',gap:10,flexWrap:'wrap'}}>
        <span>Emoji, stickers and soundboard for {server?.name||'—'}</span>
        {msg&&<span style={{fontSize:11,fontFamily:'var(--mono)',color:msg.ok?'var(--green)':'var(--red)'}}>{msg.text}</span>}
        <div style={{marginLeft:'auto',display:'flex',gap:8}}>
          <button className="df-btn df-btn-sm" onClick={load}>Refresh</button>
          <button className="df-btn df-btn-accent df-btn-sm" onClick={push} disabled={pushing}>
            {pushing?'Pushing…':'Push all to Discord'}
          </button>
        </div>
      </div>

      {loading&&<div style={{fontSize:12,color:'var(--t2)',fontFamily:'var(--mono)',padding:20}}>Loading…</div>}

      {!loading&&['emoji','stickers','soundboard'].map(type=>{
        const sync  = liveSync(type);
        const items = assets[type]||[];
        return (
          <div key={type} className="df-card" style={{marginBottom:14}}>
            {/* Header */}
            <div style={{display:'flex',alignItems:'center',gap:10,marginBottom:12}}>
              <span style={{fontSize:18}}>{ICON[type]}</span>
              <div style={{flex:1}}>
                <div style={{fontSize:14,fontWeight:700,textTransform:'capitalize'}}>{type}</div>
                <div style={{fontSize:11,fontFamily:'var(--mono)',color:'var(--t2)'}}>
                  {items.length} configured · {sync.live.length} live on Discord
                </div>
              </div>
              {sync.missing.length>0&&<span className="df-badge df-by">{sync.missing.length} not live</span>}
              {sync.extra.length>0&&<span className="df-badge df-bc">{sync.extra.length} untracked</span>}
              {items.length>0&&sync.missing.length===0&&sync.extra.length===0&&<span className="df-badge df-bg">✓ synced</span>}
            </div>

            {/* Existing items */}
            {items.map((item,i)=>(
              <AssetRow key={i} item={item} onRemove={()=>removeItem(type,i)}/>
            ))}

            {/* Untracked live items */}
            {sync.extra.length>0&&(
              <div style={{marginTop:10}}>
                <div style={{fontSize:11,color:'var(--cyan)',fontFamily:'var(--mono)',marginBottom:6}}>Live on Discord (not in config)</div>
                {sync.extra.map((a,i)=>(
                  <div key={i} style={{display:'flex',alignItems:'center',gap:8,padding:'5px 10px',background:'var(--bg3)',borderRadius:'var(--r)',marginBottom:4,fontSize:12,color:'var(--t1)'}}>
                    <span style={{flex:1}}>{a.name||a.id}</span>
                    <span className="df-badge df-bc">discord only</span>
                  </div>
                ))}
              </div>
            )}

            {/* Add form / button */}
            {addingFor===type
              ? <AddAssetForm type={type} onAdd={(item)=>addItem(type,item)} onClose={()=>setAddingFor(null)}/>
              : (
                <button
                  onClick={()=>setAddingFor(type)}
                  style={{marginTop:10,fontSize:12,fontWeight:600,padding:'6px 14px',borderRadius:'var(--r)',border:'1.5px dashed var(--border2)',background:'transparent',color:'var(--t2)',cursor:'pointer',transition:'all .13s',width:'100%'}}
                  onMouseEnter={e=>{e.target.style.borderColor='var(--accent)';e.target.style.color='var(--accent)';}}
                  onMouseLeave={e=>{e.target.style.borderColor='var(--border2)';e.target.style.color='var(--t2)';}}
                >
                  + Add {type.replace(/s$/,'')}
                </button>
              )
            }
          </div>
        );
      })}
    </div>
  );
}
