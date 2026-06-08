import { useState, useEffect, useCallback } from "react";

const SUITES = [
  {
    id:"server", title:"Server", desc:"Flask backend health, auth endpoints, core API and server management routes",
    icon:"🖥️", color:"#5b6cf9", colorRgb:"91,108,249", target:"http://127.0.0.1:5000",
    steps:[
      { id:"connectivity", num:1, name:"Connectivity",      desc:"Ping Flask, measure latency over 10 samples, inspect HTTP headers and redirects.",   checks:6,  endpoints:["GET /","GET /dashboard","GET /login","GET /uploads/","GET /about","GET /nonexistent"] },
      { id:"auth",         num:2, name:"Auth Endpoints",    desc:"Verify /login, /register, /auth/discord return expected responses.",                  checks:8,  endpoints:["GET /login","GET /register","GET /logout","GET /auth/discord","GET /auth/discord/callback","POST /login","POST /register"] },
      { id:"api",          num:3, name:"Core API",          desc:"Hit dashboard events, server health, scripts versions and other JSON endpoints.",     checks:11, endpoints:["GET /api/dashboard/server-health","GET /api/dashboard/events","GET /api/scripts/versions","GET /api/bots/available-cogs","..."] },
      { id:"servers",      num:4, name:"Server Management", desc:"Check /servers, /dashboard, server list API and per-server config endpoints.",        checks:14, endpoints:["GET /servers","GET /dashboard","GET /api/servers/list","GET /server/{id}/overview","..."] },
      { id:"bots-api",     num:5, name:"Bot Management API",desc:"Verify bot start/stop/restart endpoints, log streaming and bot list operations.",     checks:9,  endpoints:["GET /api/bots/list","POST /api/bots/start","POST /api/bots/stop","..."] },
    ],
  },
  {
    id:"bots", title:"Bots", desc:"Bot manager process health, instance status, log fetching and load testing",
    icon:"🤖", color:"#23d18b", colorRgb:"35,209,139", target:"http://127.0.0.1:5001",
    steps:[
      { id:"manager", num:1, name:"Manager Health",  desc:"Check bot_manager_direct.py is running on port 5001 and inspect debug payload.",      checks:5,  endpoints:["GET /","GET /api/status","GET /api/debug","GET /api/prereq/log","GET /nonexistent"] },
      { id:"status",  num:2, name:"Instance Status", desc:"List all discovered bots from both webapp (5000) and bot_manager (5001), reconcile.", checks:0,  endpoints:["GET :5000/api/bots/list","GET :5001/api/status"], dynamic:true },
      { id:"load",    num:3, name:"Load Test",       desc:"Fire concurrent requests at Flask & Bot Manager to measure throughput and P95 latency.", checks:50, endpoints:["GET / × 50 concurrent"], configurable:true },
    ],
  },
  {
    id:"func", title:"Functions", desc:"End-to-end Discord checks — guild presence, channels, permissions, scripts, commands and roles",
    icon:"🧩", color:"#c084fc", colorRgb:"192,132,252", target:"Discord API", requiresServer:true,
    steps:[
      { id:"config",      num:1, name:"Config",         desc:"Check local server config: guild_id, bot tokens, application IDs and repo paths.",          checks:1, endpoints:["GET /api/func-test/config/{sid}"] },
      { id:"guild",       num:2, name:"Guild Presence", desc:"Confirm the bot is in the Discord guild and can read basic guild information.",              checks:1, endpoints:["GET /api/func-test/guild/{sid}"] },
      { id:"channels",    num:3, name:"Channels",       desc:"Audit text & voice channels — compare configured channels against live Discord state.",      checks:1, endpoints:["GET /api/func-test/channels/{sid}"] },
      { id:"permissions", num:4, name:"Permissions",    desc:"Check the bot's computed guild permissions against required capabilities.",                   checks:1, endpoints:["GET /api/func-test/permissions/{sid}"] },
      { id:"scripts",     num:5, name:"Scripts",        desc:"Verify which cogs and scripts are installed per bot.",                                        checks:1, endpoints:["GET /api/bots/installed-cogs/{sid}"] },
      { id:"commands",    num:6, name:"Slash Commands", desc:"List all slash commands registered with Discord for this guild via the Discord API.",         checks:1, endpoints:["GET /api/func-test/commands/{sid}"] },
      { id:"assets",      num:7, name:"Assets",         desc:"Compare configured emojis, stickers and soundboard sounds against what's live in Discord.",   checks:3, endpoints:["GET /api/func-test/assets/{sid}"] },
      { id:"roles",       num:8, name:"Roles",          desc:"Compare configured roles against live Discord guild roles — colors, hoist, permissions.",      checks:1, endpoints:["GET /api/func-test/roles/{sid}"] },
      { id:"moderation",  num:9, name:"Moderation",     desc:"Check AutoMod rules, verification level, content filter and other moderation settings.",     checks:1, endpoints:["GET /api/func-test/automod/{sid}"], extra:true },
    ],
  },
];

function makeIssue(label, path, status, area) {
  const severity = status === 0 ? 'critical' : status >= 500 ? 'high' : 'medium';
  return {
    id: Date.now() + Math.random(),
    severity,
    area,
    title: `${label} → ${status || 'ERR'}`,
    code: status || 'ERR',
    url: path,
    auto: true,
    ts: 'just now',
  };
}

const INS_CSS = `
.ins-env-strip{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-bottom:20px}
.ins-env-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:14px 16px;display:flex;align-items:center;gap:12px;position:relative;overflow:hidden}
.ins-env-icon{width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.ins-env-name{font-size:13px;font-weight:700;color:var(--t0)}
.ins-env-url{font-size:10px;color:var(--t2);font-family:var(--mono);margin-top:2px}
.ins-env-status{display:flex;align-items:center;gap:5px;font-size:11px;font-weight:600;margin-top:5px}
.ins-env-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;box-shadow:0 0 6px currentColor}
.ins-env-ping{margin-left:auto;font-size:11px;font-family:var(--mono);color:var(--t1)}

.ins-runall{background:linear-gradient(135deg,var(--bg1),var(--bg2));border:1px solid rgba(35,209,139,0.25);border-radius:var(--rl);padding:18px 22px;margin-bottom:20px;position:relative;overflow:hidden}
.ins-runall::after{content:'';position:absolute;top:-30px;right:-30px;width:140px;height:140px;border-radius:50%;background:radial-gradient(circle,rgba(35,209,139,.12),transparent 70%)}
.ins-runall-top{display:flex;align-items:center;gap:14px;flex-wrap:wrap;position:relative;z-index:1}
.ins-runall-title{font-size:14px;font-weight:800;letter-spacing:-.3px}
.ins-runall-sub{font-size:11px;color:var(--t2);font-family:var(--mono);margin-top:2px}
.ins-stats{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;position:relative;z-index:1}
.ins-stat{background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:8px 14px;text-align:center;min-width:72px}
.ins-stat-val{font-size:18px;font-weight:800;font-family:var(--mono);letter-spacing:-.5px;line-height:1}
.ins-stat-lbl{font-size:10px;color:var(--t2);margin-top:3px}

.ins-suite{margin-bottom:24px}
.ins-suite-hdr{display:flex;align-items:center;gap:12px;padding:0 4px 12px;border-bottom:1px solid var(--border);margin-bottom:14px}
.ins-suite-icon{width:34px;height:34px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.ins-suite-title{font-size:15px;font-weight:800;letter-spacing:-.3px}
.ins-suite-meta{font-size:11px;color:var(--t2);font-family:var(--mono);margin-top:1px}
.ins-suite-actions{margin-left:auto;display:flex;gap:8px;align-items:center}

.ins-step-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.ins-step-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:16px 18px;cursor:pointer;transition:all .15s;position:relative;overflow:hidden}
.ins-step-card:hover{border-color:var(--border2);background:var(--bg2);transform:translateY(-2px)}
.ins-step-head{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.ins-step-num{font-size:10px;font-weight:700;font-family:var(--mono);padding:2px 8px;border-radius:20px;letter-spacing:.5px}
.ins-step-name{font-size:14px;font-weight:700;flex:1}
.ins-step-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:var(--bg4)}
.ins-step-dot.pass{background:var(--green);box-shadow:0 0 6px var(--green)}
.ins-step-dot.fail{background:var(--red);box-shadow:0 0 6px var(--red)}
.ins-step-dot.warn{background:var(--yellow);box-shadow:0 0 6px var(--yellow)}
.ins-step-dot.running{background:var(--accent);box-shadow:0 0 6px var(--accent)}
.ins-step-desc{font-size:12px;color:var(--t1);line-height:1.5;margin-bottom:12px;min-height:54px}
.ins-step-meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:10px;font-family:var(--mono);color:var(--t2)}
.ins-step-tag{padding:2px 7px;border-radius:5px;background:var(--bg3);color:var(--t2)}
.ins-step-tag.ep{color:var(--cyan)}

.ins-server-bar{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:10px 14px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.ins-server-bar-label{font-size:11px;color:var(--t2);font-family:var(--mono);text-transform:uppercase;letter-spacing:.5px}
.ins-server-sel{background:var(--bg3);border:1px solid var(--border2);color:var(--t0);font-family:var(--mono);font-size:12px;padding:5px 10px;border-radius:6px;outline:none;cursor:pointer}
.ins-server-sel:focus{border-color:var(--accent)}

.ins-progress{height:3px;background:var(--bg3);border-radius:3px;overflow:hidden;margin-top:12px;position:relative;z-index:1}
.ins-progress-fill{height:100%;background:linear-gradient(90deg,var(--green),var(--cyan));transition:width .3s}

.ins-log{background:var(--bg0);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;font-family:var(--mono);font-size:11px;line-height:1.7;max-height:280px;overflow-y:auto;margin-top:12px;position:relative;z-index:1}
.ins-log-line{display:flex;gap:8px;padding:2px 0}
.ins-log-ts{color:var(--t2);min-width:42px}
.ins-log-area{min-width:80px}
.ins-log-area.server{color:var(--accent2)}
.ins-log-area.bots{color:var(--green)}
.ins-log-area.func{color:var(--purple)}
.ins-log-msg{flex:1;color:var(--t1)}
.ins-log-res{font-weight:600;min-width:54px;text-align:right}
.r-ok{color:var(--green)}.r-fail{color:var(--red)}.r-warn{color:var(--yellow)}.r-skip{color:var(--t2)}

.ins-issue-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--r);padding:14px 18px;margin-bottom:10px;display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:center}
.ins-sev{font-size:9px;font-weight:700;font-family:var(--mono);padding:3px 8px;border-radius:20px;letter-spacing:.6px;text-transform:uppercase;white-space:nowrap}
.sev-critical{background:rgba(240,90,90,.18);color:var(--red);border:1px solid rgba(240,90,90,.3)}
.sev-high{background:rgba(249,200,70,.18);color:var(--yellow);border:1px solid rgba(249,200,70,.3)}
.sev-medium{background:rgba(192,132,252,.18);color:var(--purple);border:1px solid rgba(192,132,252,.3)}
.sev-low{background:rgba(0,212,255,.18);color:var(--cyan);border:1px solid rgba(0,212,255,.3)}
.ins-issue-title{font-size:13px;font-weight:700;color:var(--t0)}
.ins-issue-meta{font-size:11px;color:var(--t2);font-family:var(--mono);margin-top:3px;display:flex;gap:10px;flex-wrap:wrap}

.ins-detail-back{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--t2);cursor:pointer;margin-bottom:16px;transition:color .12s}
.ins-detail-back:hover{color:var(--accent2)}
.ins-detail-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:20px 24px;margin-bottom:16px}
.ins-detail-h{display:flex;align-items:center;gap:14px;margin-bottom:16px}
.ins-detail-icon{width:48px;height:48px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0}
.ins-detail-name{font-size:20px;font-weight:800;letter-spacing:-.4px}
.ins-detail-meta{font-size:11px;color:var(--t2);font-family:var(--mono);margin-top:2px}

.ins-ep-item{display:flex;align-items:center;gap:10px;padding:8px 12px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);margin-bottom:5px;font-family:var(--mono);font-size:12px}
.ins-ep-method{font-weight:700;color:var(--cyan);min-width:42px}
.ins-ep-path{flex:1;color:var(--t1)}
.ins-ep-status{font-size:11px;font-weight:600;color:var(--t2)}
.ins-ep-status.pass{color:var(--green)}
.ins-ep-status.fail{color:var(--red)}
.ins-ep-status.warn{color:var(--yellow)}

.ins-btn-suite-server{background:rgba(91,108,249,.12);border-color:rgba(91,108,249,.3);color:var(--accent2)}
.ins-btn-suite-server:hover{background:rgba(91,108,249,.22)}
.ins-btn-suite-bots{background:rgba(35,209,139,.12);border-color:rgba(35,209,139,.3);color:var(--green)}
.ins-btn-suite-bots:hover{background:rgba(35,209,139,.22)}
.ins-btn-suite-func{background:rgba(192,132,252,.12);border-color:rgba(192,132,252,.3);color:var(--purple)}
.ins-btn-suite-func:hover{background:rgba(192,132,252,.22)}
@keyframes ins-spin{to{transform:rotate(360deg)}}
.ins-spinner{width:12px;height:12px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:ins-spin .8s linear infinite;display:inline-block}
`;

// ── Hub ──────────────────────────────────────────────────

// Hit an endpoint, return {ms, status, ok, label}
async function probe(path, {method='GET', body=null, label=null}={}) {
  const t0 = performance.now();
  try {
    const res = await fetch(path, {
      method, credentials:'include',
      headers: body ? {'Content-Type':'application/json'} : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const ms = Math.round(performance.now()-t0);
    return { ms, status: res.status, ok: res.ok || res.status===302, label: label||path };
  } catch {
    return { ms: Math.round(performance.now()-t0), status: 0, ok: false, label: label||path };
  }
}

// Build the full check plan for a given suite and optional server_id
function buildChecks(suite, sid) {
  if (suite.id === 'server') return [
    {path:'/',          label:'GET /'},
    {path:'/dashboard', label:'GET /dashboard'},
    {path:'/app/',      label:'GET /app/'},
    {path:'/api/dashboard/server-health',                      label:'GET /api/dashboard/server-health'},
    {path:'/api/dashboard/events',                             label:'GET /api/dashboard/events'},
    {path:'/api/servers/list',                                 label:'GET /api/servers/list'},
    {path:'/api/bots/list',                                    label:'GET /api/bots/list'},
    {path:'/api/bots/available-scripts',                       label:'GET /api/bots/available-scripts'},
    {path:'/api/scripts/versions?path=Casino/blackjack',       label:'GET /api/scripts/versions'},
  ];
  if (suite.id === 'bots') return [
    {path:'/api/bots/list',    label:'GET /api/bots/list'},
    {path:'/api/agent/status', label:'GET /api/agent/status (Agent SDK)'},
  ];
  if (suite.id === 'func' && sid) return [
    {path:`/api/func-test/config/${sid}`,      label:'Config check'},
    {path:`/api/func-test/guild/${sid}`,       label:'Guild presence'},
    {path:`/api/func-test/channels/${sid}`,    label:'Channel audit'},
    {path:`/api/func-test/permissions/${sid}`, label:'Bot permissions'},
    {path:`/api/bots/installed-cogs/${sid}`,   label:'Installed cogs'},
    {path:`/api/func-test/commands/${sid}`,    label:'Slash commands'},
    {path:`/api/func-test/assets/${sid}`,      label:'Asset audit'},
    {path:`/api/func-test/roles/${sid}`,       label:'Role audit'},
    {path:`/api/func-test/automod/${sid}`,     label:'AutoMod rules'},
  ];
  return [];
}

async function runChecks(checks, suite, onCheck) {
  let pass=0, fail=0, warn=0;
  const failures = [];
  for (let i=0; i<checks.length; i++) {
    const c = checks[i];
    const r = await probe(c.path, {label:c.label});
    // 401 on agent/status means no agent connected — warn, not fail
    const result = r.ok ? 'ok' : r.status===0 ? 'fail' : r.status===401 ? 'warn' : (r.status>=400 ? 'fail' : 'warn');
    if (result==='ok') pass++; else if (result==='fail') { fail++; failures.push({...c, status:r.status, area:suite.id}); }
    else { warn++; failures.push({...c, status:r.status, area:suite.id}); }
    const pct = Math.round(((i+1)/checks.length)*100);
    const ts = String((performance.now()/1000).toFixed(2)).padStart(6,'0');
    onCheck({ts, area:suite.id, msg:`${r.label} → ${r.status||'ERR'} (${r.ms}ms)`, ms:r.ms, result});
    onCheck({_pct: pct, pass, fail, warn});
  }
  return {pass, fail, warn, failures};
}

function Hub({ selectedServer, setSelectedServer, runState, setRunState, issues, setIssues, openDetail, serverList }) {
  const totalChecks = SUITES.reduce((a,s)=>a+s.steps.reduce((b,st)=>b+(st.checks||0),0),0);

  // Live env health pings
  const [envHealth, setEnvHealth] = useState([
    { name:"Flask Server", url:"127.0.0.1:5000", icon:"🖥️", color:"var(--accent2)", bg:"rgba(91,108,249,.1)",  status:"…", ping:"…" },
    { name:"Bot Manager",  url:"127.0.0.1:5001", icon:"🤖", color:"var(--green)",   bg:"rgba(35,209,139,.1)",  status:"…", ping:"…" },
    { name:"Discord API",  url:"discord.com",    icon:"🌐", color:"var(--purple)",  bg:"rgba(192,132,252,.1)", status:"…", ping:"…" },
  ]);
  useEffect(()=>{
    (async()=>{
      const [flask, agent] = await Promise.all([
        probe('/api/dashboard/server-health', {label:'Flask'}),
        probe('/api/agent/status',            {label:'Agent'}),
      ]);
      // Discord API health via a Flask proxy endpoint
      const discord = await probe('/api/bots/test-github', {label:'Discord/GitHub'});
      setEnvHealth([
        { name:"Flask Server", url:"127.0.0.1:5000", icon:"🖥️", color:"var(--accent2)", bg:"rgba(91,108,249,.1)",  status:flask.ok?"online":"error",   ping:`${flask.ms}ms` },
        { name:"Agent/Mgr",   url:"agent",           icon:"🤖", color:"var(--green)",   bg:"rgba(35,209,139,.1)",  status:agent.ok?"online":"offline",  ping:`${agent.ms}ms` },
        { name:"Discord API",  url:"discord.com",    icon:"🌐", color:"var(--purple)",  bg:"rgba(192,132,252,.1)", status:discord.ok?"reachable":"error",ping:`${discord.ms}ms` },
      ]);
    })();
  },[]);

  const reset=()=>setRunState({phase:"idle",suite:null,progress:0,log:[],pass:0,fail:0,warn:0,skip:0});

  const runSuite = useCallback(async (suite) => {
    const checks = buildChecks(suite, selectedServer);
    if (!checks.length) {
      setRunState(s=>({...s,phase:"done",log:[...s.log,{ts:'0.00',area:suite.id,msg:'No checks — select a server for Func suite',ms:0,result:'skip'}]}));
      return;
    }
    setRunState(s=>({...s, phase:"running", suite:suite.id}));
    const {failures} = await runChecks(checks, suite, ev => {
      if (ev._pct !== undefined) {
        setRunState(s=>({...s, progress:ev._pct, pass:ev.pass, fail:ev.fail, warn:ev.warn}));
      } else {
        setRunState(s=>({...s, log:[...s.log, ev]}));
      }
    });
    if (failures.length) setIssues(iss=>[...failures.map(f=>makeIssue(f.label,f.path,f.status,f.area)), ...iss]);
    setRunState(s=>({...s, phase:"done"}));
  }, [selectedServer, setRunState, setIssues]);

  const runAll = useCallback(async () => {
    setRunState({ phase:"running", suite:"all", progress:0, log:[], pass:0, fail:0, warn:0, skip:0 });
    const allChecks = SUITES.flatMap(suite => buildChecks(suite, selectedServer).map(c=>({...c, suite})));
    if (!allChecks.length) { setRunState(s=>({...s,phase:"done"})); return; }
    const newIssues = [];
    for (let i=0; i<allChecks.length; i++) {
      const {suite, ...c} = allChecks[i];
      const r = await probe(c.path, {label:c.label});
      const result = r.ok ? 'ok' : r.status===0 ? 'fail' : (r.status>=400 ? 'fail' : 'warn');
      if (result !== 'ok') newIssues.push(makeIssue(c.label, c.path, r.status, suite.id));
      const ts = String((performance.now()/1000).toFixed(2)).padStart(6,'0');
      setRunState(s=>({
        ...s,
        progress: Math.round(((i+1)/allChecks.length)*100),
        log: [...s.log, {ts, area:suite.id, msg:`${r.label} → ${r.status||'ERR'} (${r.ms}ms)`, ms:r.ms, result}],
        pass: s.pass + (result==='ok'?1:0),
        fail: s.fail + (result==='fail'?1:0),
        warn: s.warn + (result==='warn'?1:0),
      }));
    }
    if (newIssues.length) setIssues(iss=>[...newIssues, ...iss]);
    setRunState(s=>({...s, phase:"done"}));
  }, [selectedServer, setRunState, setIssues]);

  return (
    <div>
      <div className="df-page-title">Deployment Inspector</div>
      <div className="df-page-sub">Diagnostics for Server · Bots · Discord guild infrastructure</div>

      <div className="ins-env-strip">
        {envHealth.map(e=>(
          <div key={e.name} className="ins-env-card">
            <div className="ins-env-icon" style={{background:e.bg,color:e.color}}>{e.icon}</div>
            <div style={{flex:1,minWidth:0}}>
              <div className="ins-env-name">{e.name}</div>
              <div className="ins-env-url">{e.url}</div>
              {(()=>{
                const c = e.status==='online'||e.status==='reachable' ? 'var(--green)' : e.status==='…' ? 'var(--t2)' : 'var(--red)';
                return (
                  <div className="ins-env-status" style={{color:c}}>
                    <div className="ins-env-dot" style={{background:c}}/>
                    {e.status}
                  </div>
                );
              })()}
            </div>
            <div className="ins-env-ping">{e.ping}</div>
          </div>
        ))}
      </div>

      <div className="ins-runall">
        <div className="ins-runall-top">
          <div style={{flex:1}}>
            <div className="ins-runall-title">⚡ Run All Diagnostics</div>
            <div className="ins-runall-sub">{totalChecks} checks across {SUITES.length} suites</div>
          </div>
          {runState.phase==="running"
            ? <button className="df-btn" disabled><span className="ins-spinner"/> Running…</button>
            : <button className="df-btn df-btn-success" onClick={runAll}>▶ Run All Tests</button>}
          <button className="df-btn" onClick={reset} disabled={runState.phase==="running"}>Reset</button>
          <button className="df-btn" onClick={()=>openDetail("issues")}>
            🐛 Issues
            {issues.length>0 && <span style={{marginLeft:6,background:"var(--red)",color:"#fff",fontSize:10,fontWeight:700,padding:"1px 6px",borderRadius:10,fontFamily:"var(--mono)"}}>{issues.length}</span>}
          </button>
        </div>

        <div style={{marginTop:14,position:"relative",zIndex:1}}>
          <div className="ins-server-bar">
            <span className="ins-server-bar-label">Target Server</span>
            <select className="ins-server-sel" value={selectedServer||""} onChange={e=>setSelectedServer(e.target.value)}>
              <option value="">— select for Func tests —</option>
              {serverList.map(s=><option key={s.id} value={s.id}>{s.icon} {s.name}</option>)}
            </select>
            <span style={{fontSize:10,color:"var(--t2)",fontFamily:"var(--mono)"}}>
              {selectedServer?"✓ Func suite enabled":"Func suite will be skipped"}
            </span>
          </div>
        </div>

        {runState.phase!=="idle" && (
          <>
            <div className="ins-stats">
              {[["pass",runState.pass,"var(--green)","Passed"],["fail",runState.fail,"var(--red)","Failed"],["warn",runState.warn,"var(--yellow)","Warnings"],["skip",runState.skip,"var(--t2)","Skipped"]].map(([k,v,c,l])=>(
                <div key={k} className="ins-stat"><div className="ins-stat-val" style={{color:c}}>{v}</div><div className="ins-stat-lbl">{l}</div></div>
              ))}
              <div className="ins-stat" style={{marginLeft:"auto"}}>
                <div className="ins-stat-val" style={{color:"var(--accent2)"}}>{runState.progress}%</div>
                <div className="ins-stat-lbl">{runState.phase==="running"?"Running":"Done"}</div>
              </div>
            </div>
            <div className="ins-progress"><div className="ins-progress-fill" style={{width:`${runState.progress}%`}}/></div>
            {runState.log.length>0 && (
              <div className="ins-log">
                {runState.log.map((l,i)=>(
                  <div key={i} className="ins-log-line">
                    <span className="ins-log-ts">{l.ts}</span>
                    <span className={`ins-log-area ${l.area}`}>[{l.area.toUpperCase()}]</span>
                    <span className="ins-log-msg">{l.msg}</span>
                    <span className={`ins-log-res r-${l.result}`}>{l.ms>0?`${l.ms}ms`:l.result.toUpperCase()}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      {SUITES.map(suite=>{
        const bg=`rgba(${suite.colorRgb},.1)`;
        const ringBg=`rgba(${suite.colorRgb},.18)`;
        const disabled=suite.requiresServer&&!selectedServer;
        return (
          <div key={suite.id} className="ins-suite">
            <div className="ins-suite-hdr">
              <div className="ins-suite-icon" style={{background:bg,color:suite.color}}>{suite.icon}</div>
              <div>
                <div className="ins-suite-title">{suite.title}</div>
                <div className="ins-suite-meta">Part {SUITES.indexOf(suite)+1} · {suite.target}{disabled?" · requires server selection":""}</div>
              </div>
              <div className="ins-suite-actions">
                <span style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>{suite.steps.length} steps · {suite.steps.reduce((a,s)=>a+(s.checks||0),0)} checks</span>
                <button className={`df-btn df-btn-sm ins-btn-suite-${suite.id} ${disabled?"df-btn-disabled":""}`} onClick={()=>!disabled&&runSuite(suite)}>
                  ▶ Run {suite.title}
                </button>
              </div>
            </div>
            <div className="ins-step-grid">
              {suite.steps.map(step=>(
                <div key={step.id} className="ins-step-card" onClick={()=>openDetail({suite:suite.id,step:step.id})}>
                  <div className="ins-step-head">
                    <div className="ins-step-num" style={{background:ringBg,color:suite.color}}>STEP {step.num}</div>
                    <div className="ins-step-name">{step.name}</div>
                    <div className="ins-step-dot"/>
                  </div>
                  <div className="ins-step-desc">{step.desc}</div>
                  <div className="ins-step-meta">
                    <span className="ins-step-tag">{step.dynamic?"dynamic":step.configurable?"configurable":`${step.checks} checks`}</span>
                    <span className="ins-step-tag ep">{step.endpoints.length} endpoint{step.endpoints.length!==1&&"s"}</span>
                    {step.extra&&<span className="ins-step-tag" style={{color:"var(--yellow)"}}>extra</span>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Step Detail ──────────────────────────────────────────

function StepDetail({ target, back }) {
  const suite=SUITES.find(s=>s.id===target.suite);
  const step=suite.steps.find(s=>s.id===target.step);
  const [running,setRunning]=useState(false);
  const [results,setResults]=useState([]);
  const ringBg=`rgba(${suite.colorRgb},.18)`;

  const run=async()=>{
    setRunning(true);setResults([]);
    for(const ep of step.endpoints){
      const parts=ep.split(' ');
      const method=parts[0];
      const path=parts[1]||'';
      // Skip placeholder/dynamic entries (contain { or ×)
      if(!path||path.includes('{')||ep.includes('×')||ep.includes('...')){
        setResults(r=>[...r,{endpoint:ep,ms:0,status:0,result:'skip'}]);
        continue;
      }
      const r=await probe(path,{method,label:ep});
      const result=r.ok?'pass':r.status===0?'fail':r.status>=400?'fail':'warn';
      setResults(prev=>[...prev,{endpoint:ep,ms:r.ms,status:r.status||0,result}]);
    }
    setRunning(false);
  };

  return (
    <div>
      <div className="ins-detail-back" onClick={back}>← Back to Inspector</div>
      <div className="ins-detail-card">
        <div className="ins-detail-h">
          <div className="ins-detail-icon" style={{background:ringBg,color:suite.color}}>{suite.icon}</div>
          <div style={{flex:1}}>
            <div className="ins-detail-name">Step {step.num} — {step.name}</div>
            <div className="ins-detail-meta">{suite.title} Suite · {step.checks||step.endpoints.length} checks · {suite.target}</div>
          </div>
          <button className="df-btn df-btn-accent" disabled={running} onClick={run}>
            {running?<><span className="ins-spinner"/> Running…</>:"▶ Run Step"}
          </button>
        </div>
        <div style={{fontSize:13,color:"var(--t1)",lineHeight:1.6,marginBottom:12}}>{step.desc}</div>
        <div>
          {step.endpoints.map((ep,i)=>{
            const r=results[i];
            const [method,...rest]=ep.split(" ");
            return (
              <div key={i} className="ins-ep-item">
                <span className="ins-ep-method">{method}</span>
                <span className="ins-ep-path">{rest.join(" ")}</span>
                {r?(<>
                  <span style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>{r.ms}ms</span>
                  <span className={`ins-ep-status ${r.result}`}>{r.status} {r.result==="pass"?"OK":r.result==="warn"?"GATED":"FAIL"}</span>
                </>):running&&i===results.length?(
                  <span style={{fontSize:11,color:"var(--accent2)"}}><span className="ins-spinner"/></span>
                ):(
                  <span className="ins-ep-status">— pending</span>
                )}
              </div>
            );
          })}
        </div>
        {results.length===step.endpoints.length&&results.length>0&&(
          <div className="ins-stats" style={{marginTop:14}}>
            {[["pass","var(--green)","Passed"],["warn","var(--yellow)","Warnings"],["fail","var(--red)","Failed"]].map(([k,c,l])=>(
              <div key={k} className="ins-stat"><div className="ins-stat-val" style={{color:c}}>{results.filter(r=>r.result===k).length}</div><div className="ins-stat-lbl">{l}</div></div>
            ))}
            <div className="ins-stat"><div className="ins-stat-val" style={{color:"var(--cyan)"}}>{Math.round(results.reduce((a,r)=>a+r.ms,0)/results.length)}ms</div><div className="ins-stat-lbl">Avg latency</div></div>
          </div>
        )}
      </div>
      <div className="ins-detail-card">
        <div style={{fontSize:11,fontWeight:700,color:"var(--t2)",letterSpacing:".9px",textTransform:"uppercase",marginBottom:10}}>Other steps in {suite.title}</div>
        <div className="ins-step-grid">
          {suite.steps.filter(s=>s.id!==step.id).map(s=>(
            <div key={s.id} className="ins-step-card" onClick={()=>back({suite:suite.id,step:s.id})}>
              <div className="ins-step-head">
                <div className="ins-step-num" style={{background:ringBg,color:suite.color}}>STEP {s.num}</div>
                <div className="ins-step-name">{s.name}</div>
              </div>
              <div className="ins-step-desc">{s.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Issues Page ──────────────────────────────────────────

function IssuesPage({ issues, setIssues, back }) {
  const [filter,setFilter]=useState("all");
  const filtered=filter==="all"?issues:issues.filter(i=>i.severity===filter);
  const counts={critical:issues.filter(i=>i.severity==="critical").length,high:issues.filter(i=>i.severity==="high").length,medium:issues.filter(i=>i.severity==="medium").length,low:issues.filter(i=>i.severity==="low").length};
  return (
    <div>
      <div className="ins-detail-back" onClick={back}>← Back to Inspector</div>
      <div className="df-page-title">Issues Log</div>
      <div className="df-page-sub">{issues.length} issues recorded · auto-logged from diagnostic runs</div>
      <div className="ins-stats" style={{marginBottom:20}}>
        {[["critical",counts.critical,"var(--red)"],["high",counts.high,"var(--yellow)"],["medium",counts.medium,"var(--purple)"],["low",counts.low,"var(--cyan)"]].map(([k,v,c])=>(
          <div key={k} className="ins-stat"><div className="ins-stat-val" style={{color:c}}>{v}</div><div className="ins-stat-lbl">{k[0].toUpperCase()+k.slice(1)}</div></div>
        ))}
        <div className="ins-stat" style={{marginLeft:"auto"}}><button className="df-btn df-btn-sm" onClick={()=>setIssues([])}>Clear All</button></div>
      </div>
      <div className="df-flex" style={{marginBottom:14,gap:6,flexWrap:"wrap"}}>
        {["all","critical","high","medium","low"].map(f=>(
          <div key={f} className={`df-filter-chip ${filter===f?"active":""}`} onClick={()=>setFilter(f)}>{f}</div>
        ))}
      </div>
      {filtered.length===0?(
        <div style={{textAlign:"center",padding:"40px 20px",color:"var(--t2)",fontSize:13}}>
          <div style={{fontSize:32,marginBottom:10,opacity:.5}}>✨</div>
          No issues — all clear!
        </div>
      ):filtered.map(issue=>(
        <div key={issue.id} className="ins-issue-card">
          <div className={`ins-sev sev-${issue.severity}`}>{issue.severity}</div>
          <div>
            <div className="ins-issue-title">{issue.title}</div>
            <div className="ins-issue-meta">
              <span>area: {issue.area}</span>
              <span>code: {issue.code}</span>
              <span>url: {issue.url}</span>
              {issue.auto&&<span style={{color:"var(--cyan)"}}>✓ auto-logged</span>}
              <span>· {issue.ts}</span>
            </div>
          </div>
          <div className="df-flex">
            <button className="df-btn df-btn-sm">View</button>
            <button className="df-btn df-btn-sm" onClick={()=>setIssues(iss=>iss.filter(i=>i.id!==issue.id))}>✕</button>
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Export ───────────────────────────────────────────────

export { INS_CSS };
export default function InspectorHub({ serverList }) {
  const [view,setView]=useState({page:"hub"});
  const [selectedServer,setSelectedServer]=useState(serverList[0]?.id||"");
  const [runState,setRunState]=useState({phase:"idle",suite:null,progress:0,log:[],pass:0,fail:0,warn:0,skip:0});
  const [issues,setIssues]=useState([]);

  const openDetail=(target)=>{ if(target==="issues") setView({page:"issues"}); else setView({page:"detail",target}); };
  const back=(jump)=>{ if(jump&&typeof jump==="object"&&jump.suite) setView({page:"detail",target:jump}); else setView({page:"hub"}); };

  return (
    <>
      <style>{INS_CSS}</style>
      {view.page==="hub"&&<Hub selectedServer={selectedServer} setSelectedServer={setSelectedServer} runState={runState} setRunState={setRunState} issues={issues} setIssues={setIssues} openDetail={openDetail} serverList={serverList}/>}
      {view.page==="detail"&&<StepDetail target={view.target} back={back}/>}
      {view.page==="issues"&&<IssuesPage issues={issues} setIssues={setIssues} back={back}/>}
    </>
  );
}
