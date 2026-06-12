import { useState, useEffect } from "react";
import { THEMES, getRootCSS, getOverlay, getThemeList } from './themes/index.js';
import CreateServerModal from "./CreateServerModal";
import InspectorHub from "./InspectorHub";
import IntegrationsPage  from "./pages/IntegrationsPage.jsx";
import CollaboratorsPage from "./pages/CollaboratorsPage.jsx";
import SettingsPage      from "./pages/SettingsPage.jsx";
import ActivityPage      from "./pages/ActivityPage.jsx";
import AssetsPage        from "./pages/AssetsPage.jsx";
import AgentPage         from "./pages/AgentPage.jsx";
import LoginPage         from "./pages/auth/LoginPage.jsx";
import RegisterPage      from "./pages/auth/RegisterPage.jsx";
import ForgotPasswordPage from "./pages/auth/ForgotPasswordPage.jsx";
import InvitePage        from "./pages/InvitePage.jsx";
import { api, setCSRF } from "./api.js";

// BOT placeholder — replaced by /api/bots/list data at runtime
const BOT_DEFAULT = { name:"—", id:"—", prefix:"!", version:"—", uptime:"—", ping:0, guilds:0, commands:0, shards:[], recentCmds:[] };

const CHANNELS = [
  {id:"c1",name:"general",       type:"text", category:"Community",nsfw:false,slowmode:0, perms:"everyone",topic:"Main chat"},
  {id:"c2",name:"announcements", type:"text", category:"Community",nsfw:false,slowmode:0, perms:"readonly", topic:"Server news"},
  {id:"c3",name:"rules",         type:"text", category:"Community",nsfw:false,slowmode:0, perms:"readonly", topic:""},
  {id:"c4",name:"bot-commands",  type:"text", category:"Bots",     nsfw:false,slowmode:3, perms:"everyone", topic:"Use bots here"},
  {id:"c5",name:"music",         type:"text", category:"Bots",     nsfw:false,slowmode:0, perms:"everyone", topic:""},
  {id:"c6",name:"gaming-1",      type:"voice",category:"Voice",    nsfw:false,slowmode:0, perms:"everyone", topic:""},
  {id:"c7",name:"gaming-2",      type:"voice",category:"Voice",    nsfw:false,slowmode:0, perms:"everyone", topic:""},
  {id:"c8",name:"staff-chat",    type:"text", category:"Staff",    nsfw:false,slowmode:0, perms:"staff",    topic:"Staff only"},
];

const ROLES = [
  {id:"r1",name:"@everyone",  color:"#888",   position:0,managed:false,hoist:false,members:4821,perms:["view_channels","send_messages","read_history","add_reactions","connect","speak"]},
  {id:"r2",name:"Member",     color:"#5865f2",position:1,managed:false,hoist:true, members:3910,perms:["view_channels","send_messages","read_history","add_reactions","connect","speak","embed_links","attach_files"]},
  {id:"r3",name:"Veteran",    color:"#eb459e",position:3,managed:false,hoist:true, members:621, perms:["view_channels","send_messages","read_history","add_reactions","connect","speak","embed_links","attach_files","use_slash_commands"]},
  {id:"r4",name:"Moderator",  color:"#57f287",position:5,managed:false,hoist:true, members:18,  perms:["view_channels","send_messages","read_history","add_reactions","connect","speak","embed_links","attach_files","use_slash_commands","manage_messages","mute_members","deafen_members","move_members","kick_members"]},
  {id:"r5",name:"Admin",      color:"#fee75c",position:7,managed:false,hoist:true, members:4,   perms:["administrator"]},
  {id:"r6",name:"NightWarden",color:"#ed4245",position:6,managed:true, hoist:false,members:1,   perms:["administrator"]},
  {id:"r7",name:"Booster",    color:"#f47fff",position:2,managed:true, hoist:false,members:14,  perms:["view_channels","send_messages","read_history","add_reactions","connect","speak","embed_links","attach_files","use_slash_commands","use_external_emojis"]},
];

const MEMBERS = [
  {id:"m1", name:"shadowbyte",   tag:"4421",status:"online", roles:["Member","Veteran"],   avatar:"SB", joined:"2021-04-02", warns:2, msgs:4210},
  {id:"m2", name:"void_runner",  tag:"7701",status:"idle",   roles:["Member"],             avatar:"VR", joined:"2022-01-15", warns:0, msgs:892},
  {id:"m3", name:"neonpulse",    tag:"1234",status:"online", roles:["Member","Moderator"], avatar:"NP", joined:"2021-09-20", warns:0, msgs:7830},
  {id:"m4", name:"echo_nine",    tag:"9002",status:"offline",roles:["Member","Admin"],     avatar:"E9", joined:"2021-03-13", warns:0, msgs:12400},
  {id:"m5", name:"quantum_wave", tag:"5510",status:"online", roles:["Member"],             avatar:"QW", joined:"2024-01-31", warns:0, msgs:44},
  {id:"m6", name:"pixel_ghost",  tag:"3380",status:"dnd",    roles:["Member","Veteran"],   avatar:"PG", joined:"2022-06-08", warns:1, msgs:3102},
  {id:"m12",name:"NightWarden",  tag:"BOT", status:"online", roles:["NightWarden"],        avatar:"🤖", joined:"2021-03-12", warns:0, msgs:0, isBot:true},
];

const SCRIPTS = [
  {id:"sc1",name:"Auto-Role on Join",  cat:"Automation",desc:"Assigns a default role to every new member on join.",    installs:2841,stars:4.8,installed:true, tags:["roles","onboarding"]},
  {id:"sc2",name:"Welcome Message",    cat:"Engagement", desc:"Sends a rich embed welcome card to a designated channel.",installs:5120,stars:4.9,installed:true, tags:["welcome","embeds"]},
  {id:"sc3",name:"Anti-Raid Lockdown", cat:"Security",   desc:"Detects mass-joins and temporarily locks all channels.",  installs:1230,stars:4.7,installed:false,tags:["security","automod"]},
  {id:"sc4",name:"Ticket System",      cat:"Support",    desc:"Creates private support threads via slash command.",      installs:3890,stars:4.6,installed:true, tags:["tickets","threads"]},
  {id:"sc5",name:"XP & Levelling",     cat:"Engagement", desc:"Tracks message activity and awards XP with level roles.", installs:7210,stars:4.9,installed:false,tags:["xp","levels","roles"]},
  {id:"sc6",name:"Voice Activity Log", cat:"Logging",    desc:"Logs join/leave/move events in voice channels.",          installs:2010,stars:4.3,installed:true, tags:["voice","logging"]},
  {id:"sc7",name:"Reaction Roles",     cat:"Automation", desc:"Assign roles by reacting to a pinned message.",           installs:9320,stars:5.0,installed:false,tags:["roles","reactions"]},
  {id:"sc8",name:"Poll Command",       cat:"Utility",    desc:"Creates formatted polls with emoji reactions.",           installs:3760,stars:4.7,installed:true, tags:["polls","utility"]},
];

const EVENTS = [
  {ts:"00:02",level:"warn", src:"AutoMod",msg:"Triggered filter: spam — user shadowbyte#4421 in #general"},
  {ts:"00:09",level:"info", src:"Bot",    msg:"Command !ban executed successfully (shadowbyte#4421)"},
  {ts:"00:14",level:"info", src:"Gateway",msg:"Shard 0 heartbeat OK — 38ms"},
  {ts:"00:23",level:"error",src:"Bot",    msg:"Command !config failed: missing required permission MANAGE_GUILD"},
  {ts:"00:31",level:"info", src:"Gateway",msg:"Member join: quantum_wave#5510 (4821 total)"},
  {ts:"00:38",level:"warn", src:"AutoMod",msg:"Invite link detected and deleted in #general"},
  {ts:"00:45",level:"info", src:"Bot",    msg:"Scheduled task: daily_cleanup executed (0.4s)"},
  {ts:"00:52",level:"info", src:"Gateway",msg:"Shard 1 heartbeat OK — 41ms"},
];

const ALL_NAV_ITEMS = [
  {id:"integrations", icon:"🔗", label:"Integrations"},
  {id:"collaborators",icon:"👤", label:"Collaborators"},
  {id:"activity",     icon:"📋", label:"Activity"},
  {id:"assets",       icon:"🖼️", label:"Assets"},
  {id:"agent",        icon:"🔌", label:"Agent"},
  {id:"inspector",    icon:"🔍", label:"Inspector"},
  {id:"stats",        icon:"📈", label:"Stats"},
];

// ── CSS ──────────────────────────────────────────────────

const CSS = `
@import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,500;0,600;1,400&family=DM+Sans:ital,wght@0,300;0,400;0,500;0,600;1,400&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body,#root{height:100%;background:var(--bg0)}
body{font-family:var(--sans);color:var(--t0);overflow:hidden}
::-webkit-scrollbar{width:3px;height:3px}
::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:3px}
.df-app{display:flex;height:100vh;overflow:hidden}
.df-rail{width:64px;min-width:64px;background:var(--bg0);border-right:1px solid var(--border);display:flex;flex-direction:column;align-items:center;padding:10px 0;gap:4px;overflow-y:auto;overflow-x:hidden}
.df-rail-logo{width:40px;height:40px;border-radius:12px;background:linear-gradient(135deg,var(--accent),var(--purple));display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:8px;cursor:pointer;flex-shrink:0}
.df-rail-div{width:28px;height:1px;background:var(--border2);margin:4px 0;flex-shrink:0}
.df-srv-btn{width:40px;height:40px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:18px;cursor:pointer;flex-shrink:0;background:var(--bg2);border:1px solid var(--border);transition:all .15s;position:relative}
.df-srv-btn:hover{border-color:var(--border2);background:var(--bg3);border-radius:14px}
.df-srv-btn.active{background:var(--accent3);border-color:rgba(91,108,249,0.4);border-radius:14px}
.df-srv-btn.active::before{content:'';position:absolute;left:-9px;top:50%;transform:translateY(-50%);width:3px;height:20px;background:var(--accent2);border-radius:0 3px 3px 0}
.df-rail-add{width:40px;height:40px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:22px;cursor:pointer;flex-shrink:0;background:transparent;border:1.5px dashed var(--border2);color:var(--green);transition:all .15s;margin-top:4px}
.df-rail-add:hover{border-color:var(--green);background:rgba(35,209,139,.08);transform:scale(1.05)}
.df-sidebar{width:230px;min-width:230px;background:var(--bg1);border-right:1px solid var(--border);display:flex;flex-direction:column;overflow:hidden;user-select:none}
.df-sb-hdr{padding:14px;border-bottom:1px solid var(--border)}
.df-srv-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:10px 12px;display:flex;align-items:center;gap:10px}
.df-srv-card-icon{font-size:22px}
.df-srv-card-name{font-size:14px;font-weight:700;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.df-srv-card-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green)}
.df-sb-scroll{flex:1;overflow-y:auto;padding:8px 8px 0}
.df-nav-label{font-size:10px;font-weight:700;color:var(--t2);letter-spacing:.9px;text-transform:uppercase;padding:8px 8px 4px}
.df-nav-item{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:8px;cursor:pointer;font-size:13px;font-weight:500;color:var(--t1);transition:all .13s;position:relative}
.df-nav-item:hover{background:var(--bg3);color:var(--t0)}
.df-nav-item.active{background:var(--accent3);color:var(--accent2)}
.df-nav-item.active::before{content:'';position:absolute;left:0;top:50%;transform:translateY(-50%);width:3px;height:16px;background:var(--accent2);border-radius:0 3px 3px 0}
.df-nav-icon{font-size:14px;width:18px;text-align:center}
.df-nav-badge{margin-left:auto;font-size:10px;font-family:var(--mono);background:var(--bg4);color:var(--t1);padding:1px 6px;border-radius:10px}
.df-nav-badge.err{background:rgba(240,90,90,.18);color:var(--red)}
.df-nav-badge.new{background:rgba(35,209,139,.18);color:var(--green)}
.df-sb-footer{margin-top:auto;padding:10px 8px;border-top:1px solid var(--border);display:flex;align-items:center;gap:8px;cursor:pointer;transition:background .13s}
.df-sb-footer:hover{background:var(--bg2)}
.df-footer-av{width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--accent),var(--purple));display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;flex-shrink:0}
.df-status-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0;background:var(--green);box-shadow:0 0 5px var(--green)}
.df-main{flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0;height:100vh}
.df-topbar{height:50px;min-height:50px;background:var(--bg1);border-bottom:1px solid var(--border);display:flex;align-items:center;padding:0 24px;gap:12px}
.df-tb-title{font-size:16px;font-weight:800;letter-spacing:-.4px}
.df-tb-sub{font-size:11px;color:var(--t2);font-family:var(--mono)}
.df-tb-pill{font-size:11px;font-family:var(--mono);background:var(--bg3);color:var(--t1);padding:3px 10px;border-radius:20px;border:1px solid var(--border);display:flex;align-items:center;gap:5px}
.df-tb-pill.green{background:rgba(35,209,139,.08);color:var(--green);border-color:rgba(35,209,139,.2)}
.df-content{flex:1;overflow-y:auto;padding:22px 28px}
.df-card{background:var(--bg1);border:1px solid var(--border);border-radius:var(--rl);padding:18px 20px}
.df-card-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.df-card-title{font-size:13px;font-weight:700;color:var(--t0)}
.df-card-sub{font-size:11px;color:var(--t2);font-family:var(--mono)}
.df-g5{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}
.df-g4{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}
.df-g3{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
.df-g2{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}
.df-g2-1{display:grid;grid-template-columns:2fr 1fr;gap:14px}
.df-g3-2{display:grid;grid-template-columns:3fr 2fr;gap:14px}
.df-stat{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px 18px;position:relative;overflow:hidden}
.df-stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.df-stat.blue::before{background:linear-gradient(90deg,var(--accent),transparent)}
.df-stat.cyan::before{background:linear-gradient(90deg,var(--cyan),transparent)}
.df-stat.green::before{background:linear-gradient(90deg,var(--green),transparent)}
.df-stat.purple::before{background:linear-gradient(90deg,var(--purple),transparent)}
.df-stat.yellow::before{background:linear-gradient(90deg,var(--yellow),transparent)}
.df-stat.red::before{background:linear-gradient(90deg,var(--red),transparent)}
.df-stat-icon{font-size:18px;margin-bottom:8px}
.df-stat-val{font-size:24px;font-weight:800;font-family:var(--mono);letter-spacing:-1px}
.df-stat-lbl{font-size:11px;color:var(--t2);margin-top:3px}
.df-stat-delta{font-size:11px;margin-top:5px;font-family:var(--mono)}
.df-up{color:var(--green)}.df-dn{color:var(--red)}
.df-hrow{display:flex;align-items:center;gap:10px;padding:7px 0;border-bottom:1px solid var(--border);font-size:13px}
.df-hrow:last-child{border-bottom:none}
.df-hname{flex:1;color:var(--t1);font-size:12px}
.df-hval{font-family:var(--mono);font-size:12px;color:var(--t0);min-width:50px;text-align:right}
.df-hbar{width:100px;height:3px;background:var(--bg4);border-radius:3px;overflow:hidden;flex-shrink:0}
.df-hfill{height:100%;border-radius:3px;transition:width .5s}
.df-badge{font-size:10px;font-family:var(--mono);font-weight:500;padding:2px 7px;border-radius:20px;display:inline-flex;align-items:center;gap:3px;white-space:nowrap}
.df-bg{background:rgba(35,209,139,.12);color:var(--green)}
.df-br{background:rgba(240,90,90,.12);color:var(--red)}
.df-by{background:rgba(249,200,70,.12);color:var(--yellow)}
.df-bb{background:rgba(91,108,249,.12);color:var(--accent2)}
.df-bp{background:rgba(192,132,252,.12);color:var(--purple)}
.df-bgr{background:var(--bg3);color:var(--t2)}
.df-bc{background:rgba(0,212,255,.1);color:var(--cyan)}
.df-tw{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;font-size:10px;font-weight:700;color:var(--t2);letter-spacing:.8px;text-transform:uppercase;padding:6px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
td{padding:9px 10px;border-bottom:1px solid var(--border);color:var(--t1);vertical-align:middle}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(255,255,255,.015)}
.df-mono{font-family:var(--mono)}
.df-log{display:flex;gap:10px;align-items:flex-start;padding:5px 0;border-bottom:1px solid var(--border);font-family:var(--mono);font-size:12px;line-height:1.5}
.df-log:last-child{border-bottom:none}
.df-log-ts{color:var(--t2);min-width:42px}
.df-log-src{min-width:68px}
.df-log-msg{color:var(--t1);flex:1}
.df-log-info .df-log-src{color:var(--cyan)}
.df-log-warn .df-log-src{color:var(--yellow)}
.df-log-error .df-log-src{color:var(--red)}
.df-tabs{display:flex;gap:2px;margin-bottom:18px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:4px}
.df-tab{flex:1;text-align:center;padding:7px 10px;border-radius:7px;font-size:12px;font-weight:600;cursor:pointer;color:var(--t2);transition:all .13s}
.df-tab:hover{color:var(--t1)}
.df-tab.active{background:var(--bg3);color:var(--t0)}
.df-ch-cat{font-size:10px;font-weight:700;color:var(--t2);letter-spacing:.9px;text-transform:uppercase;padding:8px 8px 4px}
.df-ch-item{display:flex;align-items:center;gap:8px;padding:6px 9px;border-radius:7px;cursor:pointer;font-size:13px;color:var(--t1);transition:all .12s}
.df-ch-item:hover{background:var(--bg3);color:var(--t0)}
.df-ch-item.sel{background:rgba(91,108,249,.15);color:var(--accent2)}
.df-ch-type{font-size:13px;width:16px;text-align:center;color:var(--t2)}
.df-ch-name{flex:1;font-weight:500}
.df-ch-badge{font-size:9px;font-family:var(--mono);background:var(--bg4);color:var(--t2);padding:1px 5px;border-radius:4px}
.df-setting-row{display:flex;align-items:center;justify-content:space-between;padding:11px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r)}
.df-s-label{font-size:13px;font-weight:600}
.df-s-hint{font-size:11px;color:var(--t2);margin-top:2px}
.df-s-input{background:var(--bg3);border:1px solid var(--border);color:var(--t0);font-family:var(--mono);font-size:12px;padding:5px 10px;border-radius:6px;min-width:120px;outline:none;transition:border-color .15s}
.df-s-input:focus{border-color:var(--accent)}
.df-toggle{width:36px;height:20px;border-radius:10px;background:var(--bg4);border:1px solid var(--border2);position:relative;cursor:pointer;transition:background .18s;flex-shrink:0}
.df-toggle.on{background:var(--accent);border-color:var(--accent)}
.df-toggle::after{content:'';position:absolute;width:14px;height:14px;border-radius:50%;background:var(--t2);top:2px;left:2px;transition:all .18s}
.df-toggle.on::after{left:18px;background:#fff}
.df-role-row{display:flex;align-items:center;gap:10px;padding:7px 9px;border-radius:7px;cursor:pointer;font-size:13px;transition:background .12s}
.df-role-row:hover{background:var(--bg3)}
.df-rdot{width:10px;height:10px;border-radius:50%;flex-shrink:0}
.df-m-row{display:flex;align-items:center;gap:12px;padding:8px 10px;border-radius:var(--r);cursor:pointer;transition:background .12s}
.df-m-row:hover{background:var(--bg3)}
.df-m-row.sel{background:var(--accent3)}
.df-m-av{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;flex-shrink:0}
.df-m-name{font-size:13px;font-weight:600}
.df-m-tag{font-size:11px;color:var(--t2);font-family:var(--mono)}
.df-online-dot{width:8px;height:8px;border-radius:50%;border:2px solid var(--bg2);flex-shrink:0}
.df-s-online{background:var(--green)}.df-s-idle{background:var(--yellow)}.df-s-dnd{background:var(--red)}.df-s-offline{background:var(--t2)}
.df-insp-input{width:100%;padding:10px 14px 10px 36px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);color:var(--t0);font-family:var(--mono);font-size:13px;outline:none;transition:border-color .15s}
.df-insp-input:focus{border-color:var(--accent)}
.df-filter-chip{font-size:11px;font-family:var(--mono);padding:4px 10px;border-radius:20px;border:1px solid var(--border);background:var(--bg2);color:var(--t2);cursor:pointer;transition:all .12s}
.df-filter-chip:hover{color:var(--t0);border-color:var(--border2)}
.df-filter-chip.active{background:var(--accent3);color:var(--accent2);border-color:rgba(91,108,249,.3)}
.df-insp-kv{display:flex;gap:10px;padding:5px 0;border-bottom:1px solid var(--border);font-size:12px}
.df-insp-kv:last-child{border-bottom:none}
.df-insp-k{color:var(--t2);min-width:140px;font-family:var(--mono)}
.df-insp-v{color:var(--t0);font-family:var(--mono);word-break:break-all}
.df-perm-grid{display:flex;flex-wrap:wrap;gap:5px}
.df-perm-tag{font-size:10px;font-family:var(--mono);padding:3px 7px;border-radius:5px;background:rgba(91,108,249,.1);color:var(--accent2);border:1px solid rgba(91,108,249,.18)}
.df-script-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--rl);padding:16px;cursor:pointer;transition:all .15s;position:relative}
.df-script-card:hover{border-color:var(--border2);background:var(--bg3)}
.df-script-card.installed{border-color:rgba(35,209,139,.25)}
.df-script-desc{font-size:12px;color:var(--t1);line-height:1.5;margin-bottom:10px}
.df-script-footer{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.df-plan-card{border:1px solid var(--border);border-radius:var(--rl);padding:18px;cursor:pointer;transition:all .15s;position:relative;overflow:hidden}
.df-plan-card:hover{border-color:var(--border2)}
.df-plan-card.active{border-color:var(--accent);background:var(--accent3)}
.df-qa-item{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:var(--r);background:var(--bg2);border:1px solid var(--border);margin-bottom:6px}
.df-qa-check{width:16px;height:16px;border-radius:4px;border:1.5px solid var(--border2);background:var(--bg3);cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0}
.df-qa-check.on{background:var(--accent);border-color:var(--accent)}
.df-flex{display:flex;align-items:center;gap:10px}
.df-gap6{gap:6px}
.df-spacer{flex:1}
.df-mt8{margin-top:8px}.df-mt14{margin-top:14px}.df-mt20{margin-top:20px}
.df-divider{height:1px;background:var(--border);margin:12px 0}
.df-sgap{display:flex;flex-direction:column;gap:14px}
.df-page-title{font-size:22px;font-weight:800;letter-spacing:-.6px;margin-bottom:3px}
.df-page-sub{font-size:12px;color:var(--t2);font-family:var(--mono);margin-bottom:20px}
.df-btn{font-size:12px;font-weight:600;font-family:var(--sans);padding:6px 14px;border-radius:7px;border:1px solid var(--border);background:var(--bg3);color:var(--t1);cursor:pointer;transition:all .15s;display:inline-flex;align-items:center;gap:6px}
.df-btn:hover{color:var(--t0);border-color:var(--border2);background:var(--bg4)}
.df-btn-accent{background:var(--accent);border-color:var(--accent);color:#fff}
.df-btn-accent:hover{background:var(--accent2);border-color:var(--accent2)}
.df-btn-sm{font-size:11px;padding:4px 10px}
.df-btn-lg{font-size:14px;padding:11px 22px}
.df-btn-danger{background:rgba(240,90,90,.12);border-color:rgba(240,90,90,.25);color:var(--red)}
.df-btn-danger:hover{background:rgba(240,90,90,.22)}
.df-btn-success{background:rgba(35,209,139,.12);border-color:rgba(35,209,139,.25);color:var(--green)}
.df-btn-success:hover{background:rgba(35,209,139,.22)}
.df-btn-ghost{background:transparent}.df-btn-ghost:hover{background:var(--bg3)}
.df-btn-disabled{opacity:.5;cursor:not-allowed;pointer-events:none}
@keyframes df-pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.5;transform:scale(1.6)}}
.df-live-dot{width:6px;height:6px;border-radius:50%;background:var(--green);animation:df-pulse 1.8s ease-in-out infinite;flex-shrink:0}
/* ── Toast ── */
@keyframes df-toast-in{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
@keyframes df-toast-out{from{opacity:1;transform:translateY(0)}to{opacity:0;transform:translateY(12px)}}
.df-toast-wrap{position:fixed;bottom:24px;right:24px;display:flex;flex-direction:column;gap:8px;z-index:9999;pointer-events:none}
.df-toast{
  display:flex;align-items:center;gap:10px;
  padding:10px 16px;border-radius:var(--r);
  font-size:12px;font-weight:600;font-family:var(--mono);
  border:1px solid var(--border2);
  background:var(--bg2);color:var(--t0);
  box-shadow:0 4px 20px rgba(0,0,0,.35);
  animation:df-toast-in .22s ease;
  pointer-events:all;min-width:200px;max-width:340px;
}
.df-toast.leaving{animation:df-toast-out .22s ease forwards}
.df-toast.success{border-color:rgba(35,209,139,.35);background:rgba(35,209,139,.08);color:var(--green)}
.df-toast.error{border-color:rgba(240,90,90,.35);background:rgba(240,90,90,.08);color:var(--red)}
.df-toast.info{border-color:var(--border2);color:var(--t0)}
/* ── Control Room scan line ── */
@keyframes df-scan{0%{transform:translateY(-100%)}100%{transform:translateY(100vh)}}
.df-scan-line{position:fixed;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,rgba(0,255,65,.18),transparent);animation:df-scan 8s linear infinite;pointer-events:none;z-index:9998}
/* ── Footer ── */
.df-app-footer{
  height:26px;min-height:26px;
  background:var(--bg0);border-top:1px solid var(--border);
  display:flex;align-items:center;padding:0 20px;gap:16px;
  font-size:10px;font-family:var(--mono);color:var(--t2);
  flex-shrink:0;
}
.df-app-footer .sep{color:var(--border3)}
`;

// ── Helpers ──────────────────────────────────────────────

// ── Toast ────────────────────────────────────────────────
function ToastContainer() {
  const [toasts, setToasts] = useState([]);
  useEffect(() => {
    const handler = (e) => {
      const { text, type='info' } = e.detail || {};
      if (!text) return;
      const id = Date.now() + Math.random();
      setToasts(ts => [...ts, { id, text, type, leaving: false }]);
      setTimeout(() => {
        setToasts(ts => ts.map(t => t.id===id ? {...t, leaving:true} : t));
        setTimeout(() => setToasts(ts => ts.filter(t => t.id!==id)), 240);
      }, 3000);
    };
    window.addEventListener('df:toast', handler);
    return () => window.removeEventListener('df:toast', handler);
  }, []);
  if (!toasts.length) return null;
  return (
    <div className="df-toast-wrap">
      {toasts.map(t => (
        <div key={t.id} className={`df-toast ${t.type} ${t.leaving?'leaving':''}`}>
          <span>{t.type==='success'?'✓':t.type==='error'?'✕':'ℹ'}</span>
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  );
}

function Sparkline({ data, color }) {
  const W=100,H=28,max=Math.max(...data),min=Math.min(...data);
  const xs=data.map((_,i)=>(i/(data.length-1))*W);
  const ys=data.map(v=>H-((v-min)/(max-min+1))*H);
  const pts=xs.map((x,i)=>`${x},${ys[i]}`).join(" ");
  const area=`M${pts.split(" ")[0]} L${pts} L${xs[xs.length-1]},${H} L0,${H} Z`;
  const gid=`sg${color.replace(/[^a-z0-9]/gi,"")}`;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{display:"block"}}>
      <defs><linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={color} stopOpacity=".2"/><stop offset="100%" stopColor={color} stopOpacity="0"/>
      </linearGradient></defs>
      <path d={area} fill={`url(#${gid})`}/>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round"/>
    </svg>
  );
}

function LiveClock() {
  const [t,setT]=useState(new Date());
  useEffect(()=>{const id=setInterval(()=>setT(new Date()),1000);return()=>clearInterval(id)},[]);
  return <span style={{fontFamily:"var(--mono)",fontSize:12,color:"var(--t2)"}}>{t.toLocaleTimeString()}</span>;
}

function Toggle({on,onToggle}){ return <div className={`df-toggle${on?" on":""}`} onClick={onToggle}/>; }

// ── Dashboard ────────────────────────────────────────────

function DashboardPage({server, live, events, bot, onNavigate}) {
  const [driftHover,setDriftHover]=useState(false);
  const memberData=[4210,4305,4410,4500,4610,4700,4760,server.memberCount||0];
  const pingData=[32,35,31,38,41,36,38,bot.ping||38];
  const health=[
    {name:"API Latency",val:(bot.ping||"—")+"ms",pct:Math.min(100,100-(bot.ping||0)/2),c:"var(--green)"},
    {name:"Bot Uptime", val:bot.uptime||"—",      pct:99, c:"var(--cyan)"},
    {name:"Memory",     val:"—",                  pct:50, c:"var(--accent2)"},
    {name:"WS Conn.",   val:live?.bot_in_guild?"in guild":"—",pct:live?.bot_in_guild?100:0,c:"var(--green)"},
    {name:"AutoMod",    val:"active",              pct:100,c:"var(--green)"},
    {name:"Drift",      val:live?.drift_status||"—",pct:live?.drift_status==="sync"?100:live?.drift_status==="minor"?60:20,c:live?.drift_status==="sync"?"var(--green)":live?.drift_status==="minor"?"var(--yellow)":"var(--red)"},
  ];
  return (
    <div>
      <div className="df-page-title">Overview</div>
      <div className="df-page-sub">{server.name} · live environment</div>
      <div className="df-g5">
        {[
          {icon:"👥",val:server.memberCount.toLocaleString(),lbl:"Members",   delta:"click to view",up:true, cls:"blue",   nav:"members"},
          {icon:"🟢",val:server.online,                      lbl:"Online",    delta:"live",up:true, cls:"green"},
          {icon:"💬",val:live?.messages_today??'—',          lbl:"Msgs Today",delta:"live",up:true, cls:"cyan"},
          {icon:"⚡",val:(bot.ping||"—")+"ms",               lbl:"Bot Ping",  delta:"stable",up:true, cls:"yellow"},
          {icon:"🚀",val:`Lv ${server.boostLevel}`,          lbl:"Boost Tier",delta:`${server.boosts} boosts`,up:true,cls:"purple"},
        ].map((s,i)=>(
          <div key={i} className={`df-stat ${s.cls}`} style={{cursor:s.nav?"pointer":undefined}} onClick={()=>s.nav&&onNavigate(s.nav)}>
            <div className="df-stat-icon">{s.icon}</div>
            <div className="df-stat-val">{s.val}</div>
            <div className="df-stat-lbl">{s.lbl}</div>
            <div className={`df-stat-delta ${s.up?"df-up":"df-dn"}`}>{s.up?"▲":"▼"} {s.delta}</div>
          </div>
        ))}
      </div>
      <div className="df-g2-1 df-mt14">
        <div className="df-card">
          <div className="df-card-hdr">
            <div><div className="df-card-title">Activity</div><div className="df-card-sub">last 8 days</div></div>
            <div className="df-flex df-gap6"><div className="df-live-dot"/><span style={{fontSize:11,color:"var(--t2)"}}>live</span></div>
          </div>
          <div style={{height:64,overflow:'hidden'}}><Sparkline data={memberData} color="var(--accent)"/></div>
          <div style={{display:"flex",justifyContent:"space-between",fontSize:10,color:"var(--t2)",fontFamily:"var(--mono)",marginTop:6}}>
            {["7d","6d","5d","4d","3d","2d","1d","now"].map(d=><span key={d}>{d}</span>)}
          </div>
          <div className="df-divider"/>
          <div className="df-g2">
            <div><div style={{fontSize:11,color:"var(--t2)",marginBottom:6}}>Bot Ping (ms)</div><div style={{height:40,overflow:'hidden'}}><Sparkline data={pingData} color="var(--green)"/></div></div>
            <div><div style={{fontSize:11,color:"var(--t2)",marginBottom:6}}>Members</div><div style={{height:40,overflow:'hidden'}}><Sparkline data={memberData} color="var(--accent)"/></div></div>
          </div>
        </div>
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">Health</div><span className="df-badge df-bg">✓ nominal</span></div>
          {health.map((h,i)=>{
            const isDrift=h.name==="Drift";
            return (
              <div key={i} className="df-hrow" style={{position:'relative'}}
                onMouseEnter={isDrift?()=>setDriftHover(true):undefined}
                onMouseLeave={isDrift?()=>setDriftHover(false):undefined}>
                <div className="df-hname">{h.name}</div>
                <div className="df-hbar"><div className="df-hfill" style={{width:`${h.pct}%`,background:h.c}}/></div>
                <div className="df-hval">{h.val}</div>
                {isDrift&&driftHover&&live&&(
                  <div style={{
                    position:'absolute',right:'100%',top:'50%',transform:'translateY(-50%)',
                    marginRight:8,background:'var(--bg3)',border:'1px solid var(--border2)',
                    borderRadius:'var(--r)',padding:'6px 10px',fontSize:10,fontFamily:'var(--mono)',
                    whiteSpace:'nowrap',zIndex:10,color:'var(--t1)',boxShadow:'0 4px 16px rgba(0,0,0,.3)',
                    pointerEvents:'none',
                  }}>
                    <div>{live.live_channels??'?'}/{live.cfg_channels??'?'} channels</div>
                    <div>{live.live_roles??'?'}/{live.cfg_roles??'?'} roles</div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
      <div className="df-g2 df-mt14">
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">Recent Events</div><div className="df-flex df-gap6"><div className="df-live-dot"/><span style={{fontSize:11,color:"var(--t2)"}}>streaming</span></div></div>
          {events.length===0
            ? <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)",padding:"12px 0",textAlign:"center"}}>No events yet — the bot will push activity here.</div>
            : events.slice(0,6).map((e,i)=>{
                const isReal='description' in e;
                const level=e.level||(e.type==='error'?'error':e.type==='warn'?'warn':'info');
                return (
                  <div key={i} className={`df-log df-log-${level}`}>
                    <span className="df-log-ts">{isReal?e.ts?.slice(11,16):e.ts}</span>
                    <span className="df-log-src">{isReal?e.server_name:e.src}</span>
                    <span className="df-log-msg">{isReal?`${e.icon||''} ${e.description}`:e.msg}</span>
                    <span className={`df-badge ${level==="info"?"df-bb":level==="warn"?"df-by":"df-br"}`}>{level}</span>
                  </div>
                );
              })
          }
        </div>
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">Server Info</div></div>
          {[["Channels",live?.live_channels??'—'],["Roles",live?.live_roles??'—'],["Boost",`Level ${server.boostLevel||0}`],["Drift",live?.drift_status||"—"],["Bot",bot.name]].map(([k,v])=>(
            <div key={k} className="df-hrow">
              <span className="df-hname">{k}</span>
              <span style={{fontFamily:"var(--mono)",fontSize:12,color:"var(--t0)"}}>{v}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Server ───────────────────────────────────────────────

function ServerPage({server, onIconUpdate}) {
  const [tab,setTab]=useState("overview");
  const [selCh,setSelCh]=useState(null);
  const [selRole,setSelRole]=useState(null);
  const [t,setT]=useState({community:false});
  const [overviewIcon,setOverviewIcon]=useState(null);
  const [permPopup,setPermPopup]=useState(false);
  const [liveChannels,setLiveChannels]=useState(null);
  const [catIdMap,setCatIdMap]=useState({}); // category name → Discord category ID
  const [automod,setAutomod]=useState({spam:false,invites:false,mentions:false,keywords:false,caps:false});
  const [newRoleForm,setNewRoleForm]=useState(null); // null | {name,color}
  const [liveRoles,setLiveRoles]=useState(null);

  useEffect(()=>{
    if (!server.id) return;
    setLiveChannels(null); setLiveRoles(null); setSelCh(null); setSelRole(null);
    api.liveChannels(server.id).catch(()=>null).then(res=>{
      if (!res) { setLiveChannels(CHANNELS); setSelCh(CHANNELS[0]); return; }
      const idToName={};  // Discord category ID → name
      const nameToId={};  // category name → Discord category ID
      (res.categories||[]).forEach(c=>{idToName[c.id]=c.name; nameToId[c.name]=c.id;});
      setCatIdMap(nameToId);
      const mapped=(res.channels||[]).map(c=>({
        id:c.id, name:c.name, type:c.type===2?'voice':c.type===15?'forum':'text',
        category:idToName[c.parent_id]||'Uncategorized',
        nsfw:c.nsfw||false, slowmode:c.rate_limit_per_user||0,
        topic:c.topic||'', perms:'everyone',
      }));
      setLiveChannels(mapped.length?mapped:CHANNELS);
      setSelCh((mapped.length?mapped:CHANNELS)[0]);
    });
    api.roles(server.id).catch(()=>null).then(res=>{
      if (!res||!res.ok) { setLiveRoles(ROLES); setSelRole(ROLES[1]); return; }
      const livePos={};
      (res.live_all||[]).forEach(r=>{livePos[r.name.toLowerCase()]=r.position;});
      const mapped=[
        ...(res.roles||[]).map((r,i)=>({
          id:'cfg-'+i, name:r.name, color:r.color||'#99aab5',
          position:livePos[r.name.toLowerCase()]??i,
          managed:false, hoist:r.hoist||false, members:'—', perms:r.permissions||[], live:r.live,
        })),
        ...(res.extra_live||[]).map(r=>({
          id:r.id, name:r.name, color:'#99aab5', position:r.position,
          managed:r.managed, hoist:false, members:'—', perms:[], live:true,
        })),
      ];
      setLiveRoles(mapped.length?mapped:ROLES);
      setSelRole((mapped.length?mapped:ROLES)[1]||(mapped.length?mapped:ROLES)[0]);
    });
  },[server.id]);

  const displayChannels=liveChannels??CHANNELS;
  const displayRoles=liveRoles??ROLES;
  const cats=[...new Set(displayChannels.map(c=>c.category))];

  // Controlled channel edit form
  const [chEdit,setChEdit]=useState(null);
  const [crudMsg,setCrudMsg]=useState(null);
  const [newChForm,setNewChForm]=useState(null); // null | {name,type,category}
  useEffect(()=>{
    if(selCh) setChEdit({name:selCh.name,topic:selCh.topic||'',nsfw:selCh.nsfw||false,slowmode:selCh.slowmode||0,private:selCh.private||false});
    else setChEdit(null);
  },[selCh?.id]);

  const msg=(m,ok=true)=>{
    setCrudMsg({text:m,ok});
    setTimeout(()=>setCrudMsg(null),4000);
    window.dispatchEvent(new CustomEvent('df:toast',{detail:{text:m,type:ok?'success':'error'}}));
  };

  const saveCh=async()=>{
    if(!selCh||!chEdit) return;
    try{
      await api.channelOp(server.id,'edit',{channel_id:selCh.id,...chEdit,rate_limit_per_user:Number(chEdit.slowmode),nsfw:chEdit.nsfw||false});
      setLiveChannels(cs=>(cs||[]).map(c=>c.id===selCh.id?{...c,...chEdit}:c));
      msg('Channel saved');
    }catch(e){msg(e.message||'Save failed',false);}
  };

  const deleteCh=async()=>{
    if(!selCh||!window.confirm(`Delete #${selCh.name}?`)) return;
    try{
      await api.channelOp(server.id,'delete',{channel_id:selCh.id});
      setSelCh(null); setChEdit(null);
      refreshChannels();
      msg('Channel deleted');
    }catch(e){msg(e.message||'Delete failed — check that the bot is in the server',false);}
  };

  const refreshChannels=()=>{
    api.liveChannels(server.id).then(res=>{
      if(!res) return;
      const idN={},nI={};
      (res.categories||[]).forEach(c=>{idN[c.id]=c.name;nI[c.name]=c.id;});
      setCatIdMap(nI);
      setLiveChannels((res.channels||[]).map(c=>({id:c.id,name:c.name,type:c.type===2?'voice':c.type===15?'forum':'text',category:idN[c.parent_id]||'Uncategorized',nsfw:c.nsfw||false,slowmode:c.rate_limit_per_user||0,topic:c.topic||'',perms:'everyone'})));
    });
  };

  const createCh=async()=>{
    if(!newChForm?.name.trim()) return;
    const parentId=catIdMap[newChForm.category]||null; // look up by category name
    try{
      await api.channelOp(server.id,'create_channel',{name:newChForm.name.trim(),type:newChForm.type==='voice'?2:newChForm.type==='forum'?15:0,parent_id:parentId});
      refreshChannels();
      setNewChForm(null); msg('Channel created');
    }catch(e){msg(e.message||'Create failed — check that the bot is in the server',false);}
  };

  const createRole=async()=>{
    if(!newRoleForm?.name.trim()) return;
    try{
      await api.roleSave(server.id,{name:newRoleForm.name.trim(),color:newRoleForm.color||'#99aab5',hoist:false,permissions:[]});
      setNewRoleForm(null);
      // Refresh roles
      api.roles(server.id).then(res=>{
        if(!res||!res.ok) return;
        const livePos={};(res.live_all||[]).forEach(r=>{livePos[r.name.toLowerCase()]=r.position;});
        const mapped=[...(res.roles||[]).map((r,i)=>({id:'cfg-'+i,name:r.name,color:r.color||'#99aab5',position:livePos[r.name.toLowerCase()]??i,managed:false,hoist:r.hoist||false,members:'—',perms:r.permissions||[],live:r.live})),...(res.extra_live||[]).map(r=>({id:r.id,name:r.name,color:'#99aab5',position:r.position,managed:r.managed,hoist:false,members:'—',perms:[],live:true}))];
        setLiveRoles(mapped.length?mapped:ROLES);
      });
      msg('Role created');
    }catch(e){msg(e.message||'Create failed',false);}
  };

  const saveRole=async()=>{
    if(!selRole) return;
    try{
      await api.roleSave(server.id,{name:selRole.name,color:selRole.color,hoist:selRole.hoist,permissions:selRole.perms||[]});
      msg('Role saved');
    }catch(e){msg(e.message||'Save failed',false);}
  };

  const deleteRole=async()=>{
    if(!selRole||!window.confirm(`Delete role "${selRole.name}"?`)) return;
    try{
      await api.roleDelete(server.id,selRole.name);
      setLiveRoles(rs=>(rs||[]).filter(r=>r.id!==selRole.id));
      setSelRole(null); msg('Role deleted');
    }catch(e){msg(e.message||'Delete failed',false);}
  };

  return (
    <div>
      <div className="df-page-title">Server Settings</div>
      <div className="df-page-sub">
        {server.name} · live config
        {crudMsg&&<span style={{marginLeft:14,fontSize:11,fontFamily:'var(--mono)',color:crudMsg.ok?'var(--green)':'var(--red)'}}>{crudMsg.text}</span>}
      </div>
      <div className="df-tabs">
        {["overview","channels","roles","moderation"].map(x=>(
          <div key={x} className={`df-tab ${tab===x?"active":""}`} onClick={()=>setTab(x)}>{x[0].toUpperCase()+x.slice(1)}</div>
        ))}
      </div>
      {tab==="channels"&&(
        <div className="df-g3-2">
          <div className="df-card" style={{padding:"14px 12px"}}>
            <div className="df-card-hdr" style={{padding:"0 6px"}}>
              <div className="df-card-title">Channels</div>
              <button className="df-btn df-btn-accent df-btn-sm" onClick={()=>setNewChForm(f=>f?null:{name:'',type:'text',category:cats[0]||''})}>+ New</button>
            </div>
            {newChForm&&(
              <div style={{display:'flex',gap:6,padding:'8px 6px',background:'var(--bg3)',borderRadius:8,marginBottom:8,flexWrap:'wrap'}}>
                <input className="df-s-input" placeholder="channel-name" value={newChForm.name} onChange={e=>setNewChForm(f=>({...f,name:e.target.value}))} style={{flex:1,minWidth:80}}/>
                <select className="df-s-input" value={newChForm.type} onChange={e=>setNewChForm(f=>({...f,type:e.target.value}))}><option value="text">Text</option><option value="voice">Voice</option><option value="forum">Forum</option></select>
                <select className="df-s-input" value={newChForm.category} onChange={e=>setNewChForm(f=>({...f,category:e.target.value}))}>
                  {cats.map(c=><option key={c}>{c}</option>)}
                </select>
                <button className="df-btn df-btn-accent df-btn-sm" onClick={createCh}>Create</button>
                <button className="df-btn df-btn-sm" onClick={()=>setNewChForm(null)}>✕</button>
              </div>
            )}
            {cats.map(cat=>(
              <div key={cat}>
                <div className="df-ch-cat">{cat}</div>
                {displayChannels.filter(c=>c.category===cat).map(c=>(
                  <div key={c.id} className={`df-ch-item ${selCh?.id===c.id?"sel":""}`} onClick={()=>setSelCh(c)}>
                    <span className="df-ch-type">{c.type==="voice"?"🔊":c.type==="forum"?"📋":"#"}</span>
                    <span className="df-ch-name">{c.name}</span>
                    {c.nsfw&&<span style={{fontSize:10,color:"var(--red)",opacity:.75}} title="NSFW">🔞</span>}
                    {c.slowmode>0&&<span className="df-ch-badge">{c.slowmode}s</span>}
                  </div>
                ))}
              </div>
            ))}
          </div>
          {selCh&&chEdit&&(
            <div className="df-card">
              <div className="df-card-hdr">
                <div><div className="df-card-title">{selCh.type==="voice"?"🔊":"#"} {selCh.name}</div><div className="df-card-sub">{selCh.type} · {selCh.category}</div></div>
                <button className="df-btn df-btn-danger df-btn-sm" onClick={deleteCh}>Delete</button>
              </div>
              <div className="df-sgap">
                <div className="df-setting-row"><div className="df-s-label">Name</div><input className="df-s-input" value={chEdit.name} onChange={e=>setChEdit(x=>({...x,name:e.target.value}))}/></div>
                {selCh.type==="text"&&<>
                  <div className="df-setting-row"><div className="df-s-label">Topic</div><input className="df-s-input" value={chEdit.topic} onChange={e=>setChEdit(x=>({...x,topic:e.target.value}))}/></div>
                  <div className="df-setting-row" style={{marginTop:6}}>
                    <div><div className="df-s-label">NSFW</div><div className="df-s-hint">Age-restricted content</div></div>
                    <Toggle on={chEdit.nsfw} onToggle={()=>setChEdit(x=>({...x,nsfw:!x.nsfw}))}/>
                  </div>
                  <div className="df-setting-row" style={{marginTop:6}}>
                    <div><div className="df-s-label">Private</div><div className="df-s-hint">Only accessible by specific roles</div></div>
                    <Toggle on={chEdit.private||false} onToggle={()=>setChEdit(x=>({...x,private:!x.private}))}/>
                  </div>
                  <div className="df-setting-row" style={{marginTop:6}}>
                    <div><div className="df-s-label">Slowmode</div><div className="df-s-hint">Seconds between messages (0–21600)</div></div>
                    <input className="df-s-input" type="number" min="0" max="21600" value={chEdit.slowmode} onChange={e=>setChEdit(x=>({...x,slowmode:Number(e.target.value)}))} style={{width:80,minWidth:80}}/>
                  </div>
                </>}
              </div>
              <div className="df-flex df-mt14">
                <button className="df-btn df-btn-accent df-btn-sm" onClick={saveCh}>Save</button>
                <button className="df-btn df-btn-sm" onClick={()=>setChEdit({name:selCh.name,topic:selCh.topic||'',nsfw:selCh.nsfw||false,slowmode:selCh.slowmode||0,private:selCh.private||false})}>Reset</button>
              </div>
            </div>
          )}
        </div>
      )}
      {tab==="roles"&&(
        <div className="df-g3-2">
          <div className="df-card" style={{padding:"14px 12px"}}>
            <div className="df-card-hdr" style={{padding:"0 6px"}}>
              <div className="df-card-title">Roles</div>
              <button className="df-btn df-btn-accent df-btn-sm" onClick={()=>setNewRoleForm(f=>f?null:{name:'',color:'#5b6cf9'})}>+ New</button>
            </div>
            {newRoleForm&&(
              <div style={{display:'flex',gap:6,padding:'8px 6px',background:'var(--bg3)',borderRadius:8,marginBottom:8,flexWrap:'wrap',alignItems:'center'}}>
                <input className="df-s-input" placeholder="Role name" value={newRoleForm.name} onChange={e=>setNewRoleForm(f=>({...f,name:e.target.value}))} style={{flex:1,minWidth:100}}/>
                <input type="color" value={newRoleForm.color} onChange={e=>setNewRoleForm(f=>({...f,color:e.target.value}))} style={{width:32,height:32,border:'none',borderRadius:6,cursor:'pointer',background:'none',padding:0}}/>
                <button className="df-btn df-btn-accent df-btn-sm" onClick={createRole}>Create</button>
                <button className="df-btn df-btn-sm" onClick={()=>setNewRoleForm(null)}>✕</button>
              </div>
            )}
            {[...displayRoles].sort((a,b)=>b.position-a.position).map(r=>(
              <div key={r.id} className="df-role-row" onClick={()=>setSelRole(r)}>
                <div className="df-rdot" style={{background:r.color}}/>
                <span style={{flex:1,fontWeight:600}}>{r.name}</span>
                {r.managed&&<span className="df-badge df-bp">managed</span>}
                {r.live===false&&<span className="df-badge df-by">not live</span>}
              </div>
            ))}
          </div>
          {selRole&&(
            <div className="df-card" style={{overflowY:'auto',maxHeight:'calc(100vh - 200px)'}}>
              <div className="df-card-hdr">
                <div className="df-flex df-gap6">
                  <input type="color" value={selRole.color} onChange={e=>setSelRole(r=>({...r,color:e.target.value}))} style={{width:24,height:24,border:'none',borderRadius:4,cursor:'pointer',background:'none',padding:0,flexShrink:0}}/>
                  <div><div className="df-card-title">{selRole.name}</div><div className="df-card-sub">pos {selRole.position}{selRole.live===false?' · not deployed':''}</div></div>
                </div>
                {selRole.managed&&<span className="df-badge df-bp">bot-managed</span>}
              </div>
              <div className="df-sgap">
                <div className="df-setting-row"><div className="df-s-label">Name</div><input className="df-s-input" value={selRole.name} onChange={e=>setSelRole(r=>({...r,name:e.target.value}))}/></div>
                <div className="df-setting-row"><div><div className="df-s-label">Hoist in list</div><div className="df-s-hint">Show separately</div></div><Toggle on={selRole.hoist} onToggle={()=>setSelRole(r=>({...r,hoist:!r.hoist}))}/></div>
              </div>
              <div className="df-divider"/>
              <div style={{display:'flex',alignItems:'center',justifyContent:'space-between',marginBottom:10}}>
                <div className="df-card-title">Permissions</div>
                <button className="df-btn df-btn-sm df-btn-accent" onClick={()=>setPermPopup(true)} style={{fontSize:11}}>
                  Edit Permissions
                </button>
              </div>
              <div className="df-perm-grid">
                {(selRole.perms||[]).length===0&&<span style={{fontSize:11,color:'var(--t2)'}}>No permissions set — click Edit to configure</span>}
                {(selRole.perms||[]).includes('administrator')
                  ?<span className="df-perm-tag" style={{color:'var(--red)'}}>ADMINISTRATOR</span>
                  :(selRole.perms||[]).map(p=><span key={p} className="df-perm-tag">{p}</span>)}
              </div>
              <div className="df-flex df-mt14">
                <button className="df-btn df-btn-accent df-btn-sm" onClick={saveRole}>Save</button>
                {!selRole.managed&&<button className="df-btn df-btn-danger df-btn-sm" onClick={deleteRole}>Delete</button>}
              </div>
            </div>
          )}
        </div>
      )}
      {/* Permissions popup */}
      {permPopup&&selRole&&(
        <div style={{position:'fixed',inset:0,background:'rgba(0,0,0,.65)',zIndex:1000,display:'flex',alignItems:'center',justifyContent:'center',padding:24}} onClick={()=>setPermPopup(false)}>
          <div className="df-card" style={{maxWidth:480,width:'100%',maxHeight:'80vh',overflowY:'auto'}} onClick={e=>e.stopPropagation()}>
            <div className="df-card-hdr" style={{marginBottom:14}}>
              <div>
                <div className="df-card-title">Permissions — {selRole.name}</div>
                <div className="df-card-sub">Toggle individual permissions for this role</div>
              </div>
              <button className="df-btn df-btn-sm" onClick={()=>setPermPopup(false)}>✕</button>
            </div>
            {[
              ['administrator',      'Administrator',      'Full control — overrides all other permissions'],
              ['manage_guild',       'Manage Server',      'Change server settings'],
              ['manage_channels',    'Manage Channels',    'Create, edit, delete channels'],
              ['manage_roles',       'Manage Roles',       'Create, edit, delete roles below own'],
              ['manage_messages',    'Manage Messages',    'Delete / pin messages'],
              ['kick_members',       'Kick Members',       'Remove members from server'],
              ['ban_members',        'Ban Members',        'Ban and unban members'],
              ['mute_members',       'Mute Members',       'Mute in voice channels'],
              ['deafen_members',     'Deafen Members',     'Deafen in voice channels'],
              ['move_members',       'Move Members',       'Move between voice channels'],
              ['view_channels',      'View Channels',      'See channels and read messages'],
              ['send_messages',      'Send Messages',      'Post in text channels'],
              ['read_history',       'Read History',       'Read past messages'],
              ['add_reactions',      'Add Reactions',      'React to messages'],
              ['embed_links',        'Embed Links',        'Inline link previews'],
              ['attach_files',       'Attach Files',       'Upload files and images'],
              ['mention_everyone',   'Mention @everyone',  'Ping @everyone / @here'],
              ['use_external_emojis','External Emojis',    'Use emojis from other servers'],
              ['use_slash_commands', 'Slash Commands',     'Use / bot commands'],
              ['connect',            'Connect',            'Join voice channels'],
              ['speak',              'Speak',              'Speak in voice channels'],
              ['stream',             'Stream',             'Share screen / video'],
            ].map(([perm,label,hint])=>{
              const perms=selRole.perms||[];
              const hasAdmin=perms.includes('administrator');
              const on=perms.includes(perm);
              return (
                <div key={perm} className="df-setting-row" style={{marginBottom:4,opacity:(hasAdmin&&perm!=='administrator')?0.45:1}}>
                  <div><div className="df-s-label" style={{fontSize:12}}>{label}</div><div className="df-s-hint">{hint}</div></div>
                  <Toggle on={on} onToggle={()=>{
                    if(hasAdmin&&perm!=='administrator') return;
                    setSelRole(r=>{
                      const p=r.perms||[];
                      return {...r,perms:on?p.filter(x=>x!==perm):[...p,perm]};
                    });
                  }}/>
                </div>
              );
            })}
            <div className="df-flex df-mt14">
              <button className="df-btn df-btn-accent df-btn-sm" onClick={()=>{saveRole();setPermPopup(false);}}>Save & Close</button>
              <button className="df-btn df-btn-sm" onClick={()=>setPermPopup(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {tab==="overview"&&(
        <div className="df-g2">
          <div className="df-card"><div className="df-card-hdr"><div className="df-card-title">General</div></div>
            <div className="df-sgap">
              <div className="df-setting-row"><div className="df-s-label">Server Name</div><input className="df-s-input" defaultValue={server.name}/></div>
              <div className="df-setting-row"><div><div className="df-s-label">Community Mode</div><div className="df-s-hint">Enables community features</div></div><Toggle on={t.community} onToggle={()=>setT(x=>({...x,community:!x.community}))}/></div>
            </div>
          </div>
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">Server Icon</div></div>
            <div style={{display:'flex',alignItems:'center',gap:14,marginBottom:12}}>
              <div style={{width:56,height:56,borderRadius:14,background:`hsl(${(server.name?.charCodeAt(0)||0)*47%360},55%,38%)`,display:'flex',alignItems:'center',justifyContent:'center',fontSize:20,fontWeight:700,color:'#fff',flexShrink:0,overflow:'hidden',border:'1px solid var(--border2)'}}>
                {overviewIcon
                  ? <img src={overviewIcon} alt="" style={{width:'100%',height:'100%',objectFit:'cover'}}/>
                  : (server.name||'?').split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase()}
              </div>
              <div>
                <div style={{fontSize:12,color:'var(--t1)',marginBottom:6}}>Upload a new icon — pushed to Discord immediately.</div>
                <label style={{cursor:'pointer'}}>
                  <span className="df-btn df-btn-sm">Choose Image</span>
                  <input type="file" accept="image/*" style={{display:'none'}} onChange={async e=>{
                    const f=e.target.files?.[0]; if(!f) return;
                    const reader=new FileReader();
                    reader.onload=async ev=>{
                      const data=ev.target.result;
                      setOverviewIcon(data);
                      onIconUpdate&&onIconUpdate(data);
                      try{
                        await api.serverIcon(server.id, data);
                        window.dispatchEvent(new CustomEvent('df:toast',{detail:{text:'Server icon updated',type:'success'}}));
                      }catch(ex){
                        window.dispatchEvent(new CustomEvent('df:toast',{detail:{text:ex.message||'Icon upload failed',type:'error'}}));
                      }
                    };
                    reader.readAsDataURL(f);
                  }}/>
                </label>
              </div>
            </div>
          </div>
          <div className="df-card"><div className="df-card-hdr"><div className="df-card-title">System Channels</div></div>
            <div className="df-sgap">
              {["System Channel","Rules Channel","Updates Channel"].map((lbl,i)=>(
                <div key={i} className="df-setting-row"><div className="df-s-label">{lbl}</div>
                  <select className="df-s-input">{displayChannels.filter(c=>c.type==="text").map(c=><option key={c.id}>#{c.name}</option>)}</select>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
      {tab==="moderation"&&(
        <div className="df-g2">
          <div className="df-card"><div className="df-card-hdr"><div className="df-card-title">AutoMod Rules</div><span style={{fontSize:11,color:"var(--t2)"}}>local config only</span></div>
            <div className="df-sgap">
              {[
                {key:"spam",     lbl:"Spam Filter",    hint:"Block repeated messages"},
                {key:"invites",  lbl:"Invite Links",   hint:"Delete Discord invite links"},
                {key:"mentions", lbl:"Mention Spam",   hint:"Flag mass mentions"},
                {key:"keywords", lbl:"Keyword Filter", hint:"Custom blocked words"},
                {key:"caps",     lbl:"Caps Lock Filter",hint:"Block ALL CAPS"},
              ].map(s=>(
                <div key={s.key} className="df-setting-row">
                  <div><div className="df-s-label">{s.lbl}</div><div className="df-s-hint">{s.hint}</div></div>
                  <Toggle on={automod[s.key]} onToggle={()=>setAutomod(a=>({...a,[s.key]:!a[s.key]}))}/>
                </div>
              ))}
            </div>
          </div>
          <div className="df-card"><div className="df-card-hdr"><div className="df-card-title">Verification</div></div>
            <div className="df-sgap">
              <div className="df-setting-row"><div><div className="df-s-label">Level</div><div className="df-s-hint">Required to send messages</div></div>
                <select className="df-s-input"><option>None</option><option>Low</option><option>Medium</option><option>High</option><option>Highest</option></select>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Bot ──────────────────────────────────────────────────

function BotPage({bot, server, onNav}) {
  const [tab,setTab]=useState("overview");
  const [busy,setBusy]=useState(false);
  const [logs,setLogs]=useState([]);
  const [logsUpdated,setLogsUpdated]=useState(null);
  const [liveBot,setLiveBot]=useState(null);

  // Poll bot status every 30s
  useEffect(()=>{
    if (!server?.id||!bot.id) return;
    const poll=()=>api.bots().catch(()=>null).then(res=>{
      if (!res?.bots) return;
      const b=res.bots.find(x=>x.bot_id===bot.id)||res.bots[0];
      if (b) setLiveBot(b);
    });
    poll();
    const iv=setInterval(poll,30000);
    return ()=>clearInterval(iv);
  },[server?.id, bot.id]);

  const db = liveBot ? {
    ...bot,
    status: liveBot.status ?? bot.status,
    ping:   liveBot.ping   ?? bot.ping,
    uptime: liveBot.uptime ?? bot.uptime,
  } : bot;

  useEffect(()=>{
    if (tab!=="logs"||!server?.id||!bot.id) return;
    const load=()=>api.botLogs(server.id,bot.id).catch(()=>null).then(res=>{
      if(!res) return;
      setLogs(res.lines||[]);
      setLogsUpdated(res.updated_at||null);
    });
    load();
    const iv=setInterval(load,10000);
    return ()=>clearInterval(iv);
  },[tab,server?.id,bot.id]);

  const doAction=async(action)=>{
    if(!server?.id||!bot.id||busy) return;
    setBusy(true);
    // Optimistically update local status so UI doesn't wait for the 30s poll
    if(action==='stop')  setLiveBot(b=>b?{...b,status:'offline'}:{status:'offline'});
    if(action==='start') setLiveBot(b=>b?{...b,status:'starting'}:{status:'starting'});
    try{
      const fn=action==='start'?api.botStart:action==='stop'?api.botStop:api.botRestart;
      const res=await fn(server.id,bot.id);
      window.dispatchEvent(new CustomEvent('df:toast',{detail:{text:res.message||res.error||'Done',type:'info'}}));
    }catch{ window.dispatchEvent(new CustomEvent('df:toast',{detail:{text:'Request failed',type:'error'}})); }
    setBusy(false);
  };

  const isLocal = db.botType==='local'||!db.botType;
  const online  = db.status==='online';
  const statusColor = online?'var(--green)':db.status==='error'?'var(--red)':'var(--t2)';

  return (
    <div>
      {/* Header strip */}
      <div style={{display:'flex',alignItems:'center',gap:14,marginBottom:20}}>
        {db.avatarUrl
          ? <img src={db.avatarUrl} alt={db.name} style={{width:52,height:52,borderRadius:14,objectFit:'cover',flexShrink:0,border:'1px solid var(--border2)'}}/>
          : <div style={{width:52,height:52,borderRadius:14,background:'linear-gradient(135deg,var(--accent),var(--purple))',display:'flex',alignItems:'center',justifyContent:'center',fontSize:24,flexShrink:0}}>🤖</div>
        }
        <div style={{flex:1}}>
          <div style={{fontSize:20,fontWeight:800,letterSpacing:'-.4px'}}>{db.name||'Bot'}</div>
          <div style={{fontSize:12,color:'var(--t2)',fontFamily:'var(--mono)',marginTop:2}}>
            {db.id||'—'} · {server?.name||'—'}
          </div>
        </div>
        <span className="df-badge" style={{
          background:online?'rgba(35,209,139,.12)':'rgba(90,90,90,.18)',
          color:statusColor,fontSize:13,padding:'5px 12px',
        }}>● {db.status||'unknown'}</span>
        {onNav && <button className="df-btn df-btn-sm" onClick={()=>onNav('agent')} title="Open Agent page">🔌 Agent</button>}
      </div>

      {/* Stat strip */}
      <div style={{display:'grid',gridTemplateColumns:'repeat(4,1fr)',gap:10,marginBottom:18}}>
        {[
          {icon:'⚡',val:db.ping>0?db.ping+'ms':'—',lbl:'Ping',     col:'var(--cyan)'},
          {icon:'⏱', val:db.uptime||'—',            lbl:'Uptime',   col:'var(--purple)'},
          {icon:'🖥️', val:isLocal?'Local':'Cloud',   lbl:'Mode',     col:'var(--accent)'},
          {icon:'🔌', val:isLocal?'heartbeat':'managed', lbl:'Method',col:'var(--yellow)'},
        ].map((s,i)=>(
          <div key={i} style={{
            background:'var(--bg2)',border:'1px solid var(--border)',
            borderRadius:'var(--r)',padding:'12px 14px',
          }}>
            <div style={{fontSize:11,color:'var(--t2)',marginBottom:4}}>{s.icon} {s.lbl}</div>
            <div style={{fontSize:16,fontWeight:700,fontFamily:'var(--mono)',color:s.col}}>{s.val}</div>
          </div>
        ))}
      </div>

      <div className="df-tabs">
        {["controls","info","update","logs"].map(t=>(
          <div key={t} className={`df-tab ${tab===t?"active":""}`} onClick={()=>setTab(t)}>
            {t[0].toUpperCase()+t.slice(1)}
          </div>
        ))}
      </div>

      {tab==="controls"&&(
        <div className="df-g2">
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">Bot Controls</div></div>
            {isLocal?(
              <div>
                <div className="df-card" style={{background:'var(--bg3)',border:'1px solid var(--border)',marginBottom:14,padding:'12px 14px'}}>
                  <div style={{fontSize:12,color:'var(--t1)',lineHeight:1.7}}>
                    This bot runs locally on your machine.<br/>
                    Start it via the bot_manager package — the dashboard shows live status reported every 30 seconds via heartbeat.
                  </div>
                </div>
                <div className="df-flex" style={{gap:8,flexWrap:'wrap'}}>
                  <a href={`/api/bots/download-local/${server?.id}/${db.id}`} className="df-btn df-btn-accent df-btn-sm">
                    Download Full Package
                  </a>
                  <button className="df-btn df-btn-sm" onClick={()=>doAction('restart')} disabled={busy||!online}>
                    Send Restart Signal
                  </button>
                </div>
              </div>
            ):(
              <div>
                <div style={{marginBottom:12,fontSize:12,color:'var(--t1)'}}>Cloud-managed bot. Control it directly from here.</div>
                <div className="df-flex" style={{gap:8}}>
                  <button className="df-btn df-btn-success df-btn-sm" onClick={()=>doAction('start')}   disabled={busy||online}>Start</button>
                  <button className="df-btn df-btn-danger df-btn-sm"  onClick={()=>doAction('stop')}    disabled={busy||!online}>Stop</button>
                  <button className="df-btn df-btn-sm"                onClick={()=>doAction('restart')} disabled={busy}>Restart</button>
                </div>
              </div>
            )}
          </div>
          <div className="df-card">
            <div className="df-card-hdr">
              <div className="df-card-title">Status</div>
              <div className="df-flex df-gap6"><div className="df-live-dot"/><span style={{fontSize:11,color:'var(--t2)'}}>auto-refresh 30s</span></div>
            </div>
            {[
              ['Status',     <span style={{color:statusColor,fontWeight:700}}>{db.status||'unknown'}</span>],
              ['Ping',       db.ping>0?db.ping+'ms':'—'],
              ['Uptime',     db.uptime||'—'],
              ['Last seen',  liveBot?.local_last_seen?liveBot.local_last_seen.slice(11,19)+' UTC':'—'],
            ].map(([k,v])=>(
              <div key={k} className="df-hrow">
                <span className="df-hname">{k}</span>
                <span style={{fontFamily:'var(--mono)',fontSize:12,color:'var(--t0)'}}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab==="info"&&(
        <div className="df-card">
          <div className="df-card-hdr"><div className="df-card-title">Bot Info</div></div>
          {[
            ['Bot ID',    db.id||'—'],
            ['Name',      db.name||'—'],
            ['Type',      isLocal?'Local (self-hosted)':'Cloud (managed)'],
            ['Server',    server?.name||'—'],
            ['Guild ID',  server?.guild_id||'—'],
            ['Bot Type',  db.botType||'local'],
          ].map(([k,v])=>(
            <div key={k} className="df-hrow">
              <span className="df-hname">{k}</span>
              <span style={{fontFamily:'var(--mono)',fontSize:12,color:'var(--t0)'}}>{v}</span>
            </div>
          ))}
        </div>
      )}

      {tab==="update"&&(
        <div className="df-g2">
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">Update Bot Files</div></div>
            <div style={{fontSize:12,color:'var(--t1)',lineHeight:1.7,marginBottom:14}}>
              Already have a bot_manager package downloaded? Download just the updated <code style={{fontFamily:'var(--mono)',background:'var(--bg3)',padding:'1px 5px',borderRadius:4}}>bot.py</code> and replace the file in your existing folder — no need to re-download the full package or reconfigure.
            </div>
            <div style={{background:'var(--bg3)',border:'1px solid var(--border)',borderRadius:'var(--r)',padding:'10px 14px',fontSize:11,fontFamily:'var(--mono)',color:'var(--t2)',marginBottom:14}}>
              bot_manager_v2/<br/>
              ├── bot_manager.py<br/>
              ├── <span style={{color:'var(--accent)'}}>bot.py ← replace this file</span><br/>
              ├── config_*.json<br/>
              └── Launch.vbs
            </div>
            <a href="/api/bots/download-botpy" className="df-btn df-btn-accent df-btn-sm" style={{textDecoration:'none',display:'inline-flex',alignItems:'center',gap:6}}>
              Download bot.py
            </a>
          </div>
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">What's updated</div></div>
            <div style={{display:'flex',flexDirection:'column',gap:8}}>
              {[
                '✓ Ping & uptime in heartbeat payload',
                '✓ Forum channel support (type 15)',
                '✓ Improved logging format',
                '✓ Startup time tracking',
                '✓ Bot role auto-assignment fix',
              ].map((l,i)=>(
                <div key={i} style={{fontSize:12,color:'var(--t1)',display:'flex',alignItems:'center',gap:8}}>
                  <span style={{color:'var(--green)',flexShrink:0}}>{l.slice(0,1)}</span>
                  <span>{l.slice(2)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {tab==="logs"&&(
        <div className="df-card">
          <div className="df-card-hdr">
            <div className="df-card-title">Bot Logs</div>
            <div className="df-flex df-gap6">
              <div className="df-live-dot"/>
              <span style={{fontSize:11,color:'var(--t2)'}}>
                auto-refresh 10s{logsUpdated&&` · ${logsUpdated.slice(11,19)} UTC`}
              </span>
            </div>
          </div>
          {logs.length===0
            ? <div style={{fontSize:12,color:'var(--t2)',fontFamily:'var(--mono)',padding:'16px 0',textAlign:'center'}}>
                No logs yet — start the bot to see output here.
              </div>
            : logs.slice(-100).map((line,i)=>{
                const txt=typeof line==='string'?line:JSON.stringify(line);
                const level=/error|fail|exception/i.test(txt)?'error':/warn/i.test(txt)?'warn':'info';
                return (
                  <div key={i} className={`df-log df-log-${level}`}>
                    <span className="df-log-msg" style={{color:'var(--t1)',wordBreak:'break-all',fontFamily:'var(--mono)',fontSize:11}}>{txt}</span>
                  </div>
                );
              })
          }
        </div>
      )}
    </div>
  );
}

// ── Members ──────────────────────────────────────────────

function MembersPage({server}) {
  const [members,setMembers]=useState([]);
  const [loadingM,setLoadingM]=useState(true);
  const [roleNames,setRoleNames]=useState([]);
  const [sel,setSel]=useState(null);
  const [search,setSearch]=useState("");
  const [filter,setFilter]=useState("all");
  const [actionMsg,setActionMsg]=useState(null);

  useEffect(()=>{
    if (!server?.id) return;
    setLoadingM(true);
    api.members(server.id).catch(()=>null).then(res=>{
      setLoadingM(false);
      if (!res) return;
      const raw=res.members||[];
      // Normalize: bot may push varying field names
      const norm=raw.map((m,i)=>({
        id:    m.user_id||m.id||String(i),
        name:  m.username||m.display_name||m.name||'Unknown',
        tag:   m.discriminator||m.tag||'0000',
        status:m.status||'offline',
        roles: m.roles||[],
        avatar:(m.username||m.name||'?')[0].toUpperCase(),
        joined:m.joined_at||m.joined||'—',
        warns: m.warnings||m.warns||0,
        msgs:  m.message_count||m.msgs||0,
        isBot: m.is_bot||m.bot||false,
      }));
      setMembers(norm);
      setSel(norm[0]||null);
      if (res.role_names) setRoleNames(res.role_names);
    });
  },[server?.id]);

  const doAction=(type)=>{
    if (!sel||!server?.id) return;
    api.memberAction(server.id, type, sel.id).then(()=>{
      setActionMsg(`${type} queued for ${sel.name}`);
      setTimeout(()=>setActionMsg(null),3000);
    }).catch(()=>setActionMsg('Action failed'));
  };

  const filtered=members.filter(m=>{
    const q=search.toLowerCase();
    return(m.name.toLowerCase().includes(q)||m.tag.includes(q))&&(filter==="all"||(filter==="online"&&m.status==="online")||(filter==="staff"&&m.roles.some(r=>["Admin","Moderator"].includes(r))));
  });
  const roleColor=_r=>"var(--accent)";
  const avBg=["#5b6cf9","#23d18b","#f472b6","#f9c846","#00d4ff","#c084fc","#f05a5a"];
  return (
    <div>
      <div className="df-page-title">Members</div>
      <div className="df-page-sub">{members.filter(m=>!m.isBot).length} humans · {members.filter(m=>m.isBot).length} bots</div>
      <div className="df-g3-2">
        <div>
          <div className="df-flex" style={{marginBottom:12,gap:8}}>
            <div style={{flex:1,position:"relative"}}>
              <span style={{position:"absolute",left:10,top:"50%",transform:"translateY(-50%)",fontSize:13,color:"var(--t2)"}}>🔍</span>
              <input className="df-s-input" style={{width:"100%",paddingLeft:30}} placeholder="Search members…" value={search} onChange={e=>setSearch(e.target.value)}/>
            </div>
            {["all","online","staff"].map(f=><div key={f} className={`df-filter-chip ${filter===f?"active":""}`} onClick={()=>setFilter(f)}>{f}</div>)}
          </div>
          <div className="df-card" style={{padding:"10px 8px",maxHeight:"calc(100vh - 260px)",overflowY:"auto"}}>
            {loadingM&&<div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)",padding:12}}>Loading members…</div>}
            {!loadingM&&members.length===0&&(
              <div style={{textAlign:"center",padding:"28px 16px",color:"var(--t2)"}}>
                <div style={{fontSize:28,marginBottom:8}}>👥</div>
                <div style={{fontSize:12,fontWeight:600}}>No members synced yet</div>
                <div style={{fontSize:11,marginTop:4}}>The bot will push member data once it joins the server.</div>
              </div>
            )}
            {filtered.map((m,i)=>(
              <div key={m.id} className={`df-m-row ${sel?.id===m.id?"sel":""}`} onClick={()=>setSel(m)}>
                <div className="df-m-av" style={{background:m.isBot?"var(--bg3)":avBg[i%avBg.length],fontSize:m.isBot?20:12}}>{m.avatar}</div>
                <div style={{flex:1,minWidth:0}}>
                  <div className="df-flex df-gap6"><span className="df-m-name">{m.name}</span>{m.isBot&&<span className="df-badge df-bc">BOT</span>}</div>
                  <div className="df-m-tag">#{m.tag}</div>
                </div>
                <div className={`df-online-dot df-s-${m.status}`}/>
              </div>
            ))}
          </div>
        </div>
        {sel&&(
          <div>
            <div className="df-card" style={{marginBottom:14}}>
              <div className="df-flex" style={{marginBottom:14,gap:12}}>
                <div className="df-m-av" style={{width:52,height:52,fontSize:sel.isBot?26:18,background:sel.isBot?"var(--bg3)":avBg[members.indexOf(sel)%avBg.length]}}>{sel.avatar}</div>
                <div>
                  <div style={{fontSize:18,fontWeight:800}}>{sel.name}<span style={{color:"var(--t2)",fontFamily:"var(--mono)",fontSize:14}}>#{sel.tag}</span></div>
                  <div className="df-flex df-gap6" style={{marginTop:4}}>
                    <span className={`df-badge ${sel.status==="online"?"df-bg":sel.status==="idle"?"df-by":sel.status==="dnd"?"df-br":"df-bgr"}`}>● {sel.status}</span>
                    {sel.isBot&&<span className="df-badge df-bc">BOT</span>}
                  </div>
                </div>
              </div>
              <div className="df-divider"/>
              {[["Joined",sel.joined],["Messages",sel.msgs.toLocaleString()],["Warnings",sel.warns]].map(([k,v])=>(
                <div key={k} className="df-hrow"><span className="df-hname">{k}</span><span style={{fontFamily:"var(--mono)",fontSize:12,color:k==="Warnings"&&v>0?"var(--yellow)":"var(--t0)"}}>{v}</span></div>
              ))}
            </div>
            <div className="df-card" style={{marginBottom:14}}>
              <div className="df-card-title" style={{marginBottom:10}}>Roles</div>
              <div className="df-perm-grid">
                {sel.roles.map(r=>(
                  <span key={r} style={{fontSize:11,fontFamily:"var(--mono)",padding:"3px 8px",borderRadius:5,background:`${roleColor(r)}18`,color:roleColor(r),border:`1px solid ${roleColor(r)}30`}}>{r}</span>
                ))}
              </div>
            </div>
            {!sel.isBot&&(
              <div className="df-card">
                <div className="df-card-title" style={{marginBottom:12}}>Actions</div>
                {actionMsg&&<div style={{fontSize:11,fontFamily:"var(--mono)",color:"var(--green)",marginBottom:8}}>{actionMsg}</div>}
                <div style={{display:"flex",flexDirection:"column",gap:6}}>
                  <button className="df-btn df-btn-sm" style={{textAlign:"left"}} onClick={()=>doAction('warn')}>⚠️ Warn member</button>
                  <button className="df-btn df-btn-sm" style={{textAlign:"left"}} onClick={()=>doAction('kick')}>🚪 Kick from server</button>
                  <button className="df-btn df-btn-danger df-btn-sm" style={{textAlign:"left"}} onClick={()=>doAction('ban')}>🚨 Ban member</button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Scripts ──────────────────────────────────────────────

function ScriptsPage({server}) {
  const [sel,setSel]=useState(null);
  const [search,setSearch]=useState("");
  const [cat,setCat]=useState("all");
  const [scripts,setScripts]=useState(SCRIPTS);
  const [actionMsg,setActionMsg]=useState(null);
  const [updates,setUpdates]=useState(null);   // null | [] from check-scripts
  const [checkBusy,setCheckBusy]=useState(false);

  const checkUpdates=async()=>{
    if(!server?.id) return;
    setCheckBusy(true); setUpdates(null);
    try {
      const r=await api.checkScripts(server.id).catch(()=>null);
      setUpdates(r?.updates||r?.scripts||[]);
    } catch{}
    setCheckBusy(false);
  };

  const updateScript=async(scriptName)=>{
    try {
      await api.scriptUpdate({server_id:server.id, script:scriptName});
      setActionMsg(`Updated: ${scriptName}`);
      setTimeout(()=>setActionMsg(null),3000);
      setUpdates(u=>(u||[]).filter(x=>x.name!==scriptName));
    } catch(e){setActionMsg(e.message||'Update failed');}
  };

  // Fetch available scripts + installed cogs for this server
  useEffect(()=>{
    api.availableScripts().catch(()=>null).then(async res=>{
      if (!res?.scripts?.length) return;
      // Get installed cog names for this server (best-effort)
      let installedNames=new Set();
      if (server?.id) {
        const inst=await api.installedCogs(server.id).catch(()=>null);
        if (inst?.cogs) installedNames=new Set(inst.cogs.map(c=>c.name.toLowerCase()));
      }
      const mapped=res.scripts.map(s=>({
        id:         s.name,
        path:       s.folder_path||s.path||s.name,
        githubUrl:  s.github_url||`https://github.com/beasty03/discord-server-bot-scripts/tree/main/${s.folder_path||s.path||s.name}`,
        name:       s.name.replace(/_/g,' ').replace(/-/g,' ').replace(/\b\w/g,c=>c.toUpperCase()),
        cat:        s.category||'Utility',
        desc:       s.description||'—',
        installs:   0,
        stars:      s.verified?5.0:4.0,
        installed:  installedNames.has(s.name.toLowerCase()),
        tags:       s.features||[],
        author:     s.author||'',
        version:    s.version||'',
      }));
      setScripts(mapped);
    });
  },[server?.id]);

  const cats=["all",...new Set(scripts.map(s=>s.cat))];
  const filtered=scripts.filter(s=>{
    const q=search.toLowerCase();
    return(s.name.toLowerCase().includes(q)||s.desc.toLowerCase().includes(q)||s.tags.some(t=>String(t).toLowerCase().includes(q)))&&(cat==="all"||s.cat===cat);
  });

  const toggle=async(id)=>{
    const s=scripts.find(x=>x.id===id);
    if (!s||!server?.id) return;
    try {
      if (s.installed) {
        await api.removeCog(server.id, s.id);
      } else {
        await api.installCog(server.id, s.path||s.id);
      }
      setScripts(ss=>ss.map(x=>x.id===id?{...x,installed:!x.installed}:x));
      setActionMsg(`${s.installed?'Removed':'Installed'}: ${s.name}`);
      setTimeout(()=>setActionMsg(null),3000);
    } catch(e) {
      setActionMsg('Action failed');
    }
  };

  const catColor={Automation:"df-bb",Engagement:"df-bg",Security:"df-br",Support:"df-bp",Utility:"df-bc",Logging:"df-bgr",Moderation:"df-by"};
  return (
    <div>
      <div className="df-page-title">Script Library</div>
      <div className="df-page-sub">{scripts.filter(s=>s.installed).length} installed · {scripts.length} available{actionMsg&&<span style={{marginLeft:14,color:"var(--green)",fontFamily:"var(--mono)",fontSize:11}}>{actionMsg}</span>}</div>

      {/* Update checker strip */}
      <div style={{display:"flex",alignItems:"center",gap:10,padding:"10px 14px",background:"var(--bg2)",border:"1px solid var(--border)",borderRadius:"var(--r)",marginBottom:14,flexWrap:"wrap"}}>
        <button className="df-btn df-btn-sm" onClick={checkUpdates} disabled={checkBusy||!server?.id}>
          {checkBusy?"Checking…":"Check for Updates"}
        </button>
        {updates===null && <span style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>Click to scan installed cogs for available updates</span>}
        {updates!==null && updates.length===0 && <span style={{fontSize:11,color:"var(--green)",fontFamily:"var(--mono)"}}>✓ All cogs are up to date</span>}
        {(updates||[]).map(u=>(
          <div key={u.name} className="df-flex df-gap6" style={{background:"var(--bg3)",borderRadius:6,padding:"4px 10px",gap:8}}>
            <span style={{fontSize:12,fontFamily:"var(--mono)",color:"var(--t0)"}}>{u.name}</span>
            <span style={{fontSize:11,color:"var(--yellow)"}}>{u.installed_version||"?"} → {u.latest_version||"latest"}</span>
            <button className="df-btn df-btn-accent df-btn-sm" style={{padding:"2px 8px"}} onClick={()=>updateScript(u.name)}>Update</button>
          </div>
        ))}
      </div>

      <div className="df-flex" style={{gap:8,marginBottom:14}}>
        <div style={{flex:1,position:"relative"}}>
          <span style={{position:"absolute",left:10,top:"50%",transform:"translateY(-50%)",fontSize:13,color:"var(--t2)"}}>🔍</span>
          <input className="df-s-input" style={{width:"100%",paddingLeft:30}} placeholder="Search scripts…" value={search} onChange={e=>setSearch(e.target.value)}/>
        </div>
        {cats.map(c=><div key={c} className={`df-filter-chip ${cat===c?"active":""}`} onClick={()=>setCat(c)} style={{whiteSpace:"nowrap"}}>{c}</div>)}
      </div>
      {/* Script detail overlay modal */}
      {sel&&(
        <div style={{position:"fixed",inset:0,background:"rgba(0,0,0,.7)",zIndex:999,display:"flex",alignItems:"center",justifyContent:"center",padding:24}} onClick={()=>setSel(null)}>
          <div className="df-card" style={{maxWidth:480,width:"100%",position:"relative"}} onClick={e=>e.stopPropagation()}>
            <div className="df-card-hdr">
              <div>
                <div className="df-card-title" style={{fontSize:16}}>{sel.name}</div>
                <div className="df-card-sub">{sel.cat}{sel.author?` · by ${sel.author}`:''}{sel.version?` · v${sel.version}`:''}</div>
              </div>
              <button className="df-btn df-btn-sm" onClick={()=>setSel(null)}>✕</button>
            </div>
            <div style={{fontSize:13,color:"var(--t1)",lineHeight:1.7,marginBottom:14}}>{sel.desc||"No description available."}</div>
            <div className="df-flex df-gap6" style={{flexWrap:"wrap",marginBottom:16}}>
              <span className={`df-badge ${catColor[sel.cat]||"df-bgr"}`}>{sel.cat}</span>
              {sel.stars>=5&&<span className="df-badge df-by">★ Verified</span>}
              {(sel.tags||[]).map(t=><span key={t} className="df-badge df-bgr">{t}</span>)}
            </div>
            <div className="df-flex" style={{gap:8}}>
              <button className={`df-btn df-btn-sm ${sel.installed?"df-btn-danger":"df-btn-accent"}`} onClick={()=>{toggle(sel.id);setSel(null);}}>
                {sel.installed?"Remove from bot":"Install to bot"}
              </button>
              {sel.githubUrl&&(
                <a href={sel.githubUrl} target="_blank" rel="noreferrer" className="df-btn df-btn-sm" style={{textDecoration:"none"}}>
                  View on GitHub ↗
                </a>
              )}
            </div>
          </div>
        </div>
      )}

      <div style={{display:"grid",gridTemplateColumns:"repeat(auto-fill,minmax(280px,1fr))",gap:12}}>
        {filtered.map(s=>(
          <div key={s.id} className={`df-script-card ${s.installed?"installed":""}`} onClick={()=>setSel(s)}>
            <div className="df-flex" style={{marginBottom:8,gap:6}}>
              <span className="df-card-title" style={{flex:1}}>{s.name}</span>
              <span className={`df-badge ${catColor[s.cat]||"df-bgr"}`}>{s.cat}</span>
              {s.installed&&<span className="df-badge df-bg">✓</span>}
            </div>
            <div className="df-script-desc">{s.desc}</div>
            <div className="df-script-footer">
              {s.stars>=5&&<span style={{fontSize:11,color:"var(--yellow)"}}>★ Verified</span>}
              {s.version&&<span className="df-badge df-bgr">v{s.version}</span>}
              {(s.tags||[]).slice(0,2).map(t=><span key={t} className="df-badge df-bgr">{t}</span>)}
              <button className={`df-btn df-btn-sm ${s.installed?"df-btn-danger":"df-btn-success"}`} style={{marginLeft:"auto"}} onClick={e=>{e.stopPropagation();toggle(s.id);}}>
                {s.installed?"Remove":"Install"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Account ──────────────────────────────────────────────

function UserPage({quickAccess,setQuickAccess,profile,setProfile,theme,applyTheme,avatarUrl,onAvatarChange}) {
  const [tab,setTab]=useState("profile");
  const [revokeMsg,setRevokeMsg]=useState(null);
  const [uploadMsg,setUploadMsg]=useState(null);
  const [unlinkMsg,setUnlinkMsg]=useState(null);
  const [discordAvatarMsg,setDiscordAvatarMsg]=useState(null);
  const [themeSearch,setThemeSearch]=useState('');
  const [dragIdx,setDragIdx]=useState(null);
  const [overIdx,setOverIdx]=useState(null);

  const uploadAvatar=async(e)=>{
    const file=e.target.files?.[0];
    if(!file) return;
    const fd=new FormData();
    fd.append('avatar',file);
    try{
      const res=await fetch('/api/account/avatar',{method:'POST',credentials:'include',body:fd});
      const data=await res.json();
      if(data.ok||data.url){
        onAvatarChange&&onAvatarChange(data.url||'');
        setUploadMsg('Avatar updated');
      } else setUploadMsg(data.error||'Upload failed');
    }catch{setUploadMsg('Upload failed');}
    setTimeout(()=>setUploadMsg(null),3000);
  };

  const useDiscordAvatar=async()=>{
    try{
      const data=await api.setAvatarSource('discord');
      if(data?.ok&&data.url){
        onAvatarChange&&onAvatarChange(data.url);
        setDiscordAvatarMsg('Now using Discord avatar');
      } else setDiscordAvatarMsg(data?.error||'Failed');
    }catch{ setDiscordAvatarMsg('Failed'); }
    setTimeout(()=>setDiscordAvatarMsg(null),3000);
  };
  const initial = profile?.username?.[0]?.toUpperCase() || '?';

  const revokeOthers = () => {
    api.revokeOtherSessions().then(()=>{
      setRevokeMsg('Other sessions revoked.');
      setTimeout(()=>setRevokeMsg(null),3000);
    }).catch(()=>setRevokeMsg('Failed to revoke sessions.'));
  };

  return (
    <div>
      <div className="df-page-title">Account</div>
      <div className="df-page-sub">Profile and preferences</div>
      <div className="df-tabs">
        {["profile","appearance","quick access"].map(t=>(
          <div key={t} className={`df-tab ${tab===t?"active":""}`} onClick={()=>setTab(t)}>{t[0].toUpperCase()+t.slice(1)}</div>
        ))}
      </div>
      {tab==="profile"&&(
        <div className="df-g2">
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">Your Profile</div></div>
            <div className="df-flex" style={{gap:14,marginBottom:18}}>
              <label style={{cursor:"pointer",position:"relative",flexShrink:0}} title="Click to change avatar">
                {avatarUrl
                  ? <img src={avatarUrl} alt="avatar" style={{width:64,height:64,borderRadius:"50%",objectFit:"cover"}}/>
                  : <div style={{width:64,height:64,borderRadius:"50%",background:"linear-gradient(135deg,var(--accent),var(--purple))",display:"flex",alignItems:"center",justifyContent:"center",fontSize:24,fontWeight:800}}>{initial}</div>
                }
                <div style={{position:"absolute",bottom:0,right:0,width:20,height:20,background:"var(--accent)",borderRadius:"50%",display:"flex",alignItems:"center",justifyContent:"center",fontSize:10}}>✏️</div>
                <input type="file" accept="image/*" style={{display:"none"}} onChange={uploadAvatar}/>
              </label>
              <div>
                {uploadMsg&&<div style={{fontSize:11,color:"var(--green)",fontFamily:"var(--mono)",marginBottom:4}}>{uploadMsg}</div>}
                {discordAvatarMsg&&<div style={{fontSize:11,color:"var(--cyan)",fontFamily:"var(--mono)",marginBottom:4}}>{discordAvatarMsg}</div>}
                <div style={{fontSize:18,fontWeight:800}}>{profile?.username||'…'}</div>
                <div style={{fontSize:12,color:"var(--t2)",fontFamily:"var(--mono)"}}>{profile?.email||'…'}</div>
                <div className="df-flex df-gap6" style={{marginTop:6,flexWrap:'wrap'}}>
                  {profile?.discord_linked&&<span className="df-badge df-bc">Discord linked</span>}
                </div>
                {profile?.discord_linked&&profile?.discord_avatar_url&&(
                  <button className="df-btn df-btn-sm" style={{marginTop:8,fontSize:10}} onClick={useDiscordAvatar}>
                    Use Discord avatar
                  </button>
                )}
              </div>
            </div>
            <div className="df-sgap">
              <div className="df-setting-row"><div className="df-s-label">Username</div><span style={{fontFamily:"var(--mono)",fontSize:13,color:"var(--t0)"}}>{profile?.username||'…'}</span></div>
              <div className="df-setting-row"><div className="df-s-label">Email</div><span style={{fontFamily:"var(--mono)",fontSize:13,color:"var(--t0)"}}>{profile?.email||'…'}</span></div>
              <div className="df-setting-row"><div className="df-s-label">Servers</div><span style={{fontFamily:"var(--mono)",fontSize:13,color:"var(--t0)"}}>{profile?.server_count??'—'}</span></div>
            </div>
          </div>
          <div className="df-card">
            <div className="df-card-hdr"><div className="df-card-title">Security</div></div>
            <div className="df-sgap">
              <div className="df-setting-row"><div><div className="df-s-label">Session Timeout</div><div className="df-s-hint">Currently: {profile?.session_timeout_minutes??1} min</div></div></div>
              {profile?.discord_linked&&(
                <div className="df-setting-row">
                  <div><div className="df-s-label">Discord</div><div className="df-s-hint">Linked as {profile.discord_username||'unknown'}</div></div>
                  <div className="df-flex df-gap6">
                    <span className="df-badge df-bc">linked</span>
                    <button className="df-btn df-btn-sm df-btn-danger" style={{fontSize:10}} onClick={async()=>{
                      try{
                        await api.unlinkDiscord();
                        setUnlinkMsg('Discord unlinked.');
                        setProfile(p=>p?{...p,discord_linked:false,discord_username:''}:p);
                      }catch{ setUnlinkMsg('Failed to unlink.'); }
                      setTimeout(()=>setUnlinkMsg(null),3000);
                    }}>Unlink</button>
                  </div>
                </div>
              )}
            </div>
            {unlinkMsg&&<div style={{fontSize:11,fontFamily:"var(--mono)",color:"var(--green)",margin:"8px 0"}}>{unlinkMsg}</div>}
            {revokeMsg&&<div style={{fontSize:11,fontFamily:"var(--mono)",color:"var(--green)",margin:"8px 0"}}>{revokeMsg}</div>}
            <div className="df-flex df-mt14"><button className="df-btn df-btn-danger df-btn-sm" onClick={revokeOthers}>Revoke Other Sessions</button></div>
          </div>
        </div>
      )}
      {tab==="appearance"&&(()=>{
        const q=themeSearch.toLowerCase();
        const allThemes = getThemeList().filter(t=>!q||t.name.toLowerCase().includes(q)||t.desc?.toLowerCase().includes(q));
        const ThemeCard = ({t})=>{
          const id=t.id;
          const active=theme===id;
          return (
            <div key={id}
              onClick={()=>applyTheme(id)}
              style={{
                border:`2px solid ${active?"var(--accent)":"var(--border2)"}`,
                borderRadius:"var(--rl)",padding:"18px 16px",
                cursor:"pointer",
                background:active?"var(--accent3)":"var(--bg2)",
                transition:"all .15s",
                position:"relative",
              }}>
              <div style={{display:"flex",gap:6,marginBottom:12}}>
                {(t.preview||[]).map((c,i)=>(
                  <div key={i} style={{width:i===2?28:22,height:22,borderRadius:i===2?6:4,background:c,border:"1px solid rgba(128,128,128,0.2)",flexShrink:0}}/>
                ))}
              </div>
              <div style={{fontSize:14,fontWeight:700,color:active?"var(--accent)":"var(--t0)",marginBottom:3}}>{t.name}</div>
              <div style={{fontSize:11,color:"var(--t2)"}}>{t.desc}</div>
              {active&&<div style={{marginTop:10,fontSize:10,fontFamily:"var(--mono)",color:"var(--accent)"}}>● active</div>}
            </div>
          );
        };
        return (
          <div>
            <div style={{position:'relative',marginBottom:14}}>
              <span style={{position:'absolute',left:11,top:'50%',transform:'translateY(-50%)',fontSize:13,color:'var(--t2)',pointerEvents:'none'}}>🔍</span>
              <input
                className="df-s-input"
                style={{width:'100%',paddingLeft:32,fontSize:13}}
                placeholder="Search themes…"
                value={themeSearch}
                onChange={e=>setThemeSearch(e.target.value)}
              />
            </div>
            <div className="df-card">
              <div className="df-card-hdr">
                <div><div className="df-card-title">Themes</div><div className="df-card-sub">All themes included</div></div>
                <span style={{fontSize:11,color:"var(--t2)"}}>Takes effect immediately</span>
              </div>
              {allThemes.length===0
                ? <div style={{fontSize:12,color:'var(--t2)',padding:'8px 0'}}>No themes match.</div>
                : <div style={{display:"grid",gridTemplateColumns:"repeat(3,1fr)",gap:14}}>{allThemes.map(t=><ThemeCard key={t.id} t={t}/>)}</div>
              }
            </div>
          </div>
        );
      })()}
      {tab==="quick access"&&(()=>{
        const enabled=quickAccess.map(id=>ALL_NAV_ITEMS.find(n=>n.id===id)).filter(Boolean);
        const available=ALL_NAV_ITEMS.filter(n=>!quickAccess.includes(n.id));
        const drop=(toIdx)=>{
          if(dragIdx===null||dragIdx===toIdx){setDragIdx(null);setOverIdx(null);return;}
          const next=[...quickAccess];
          const [removed]=next.splice(dragIdx,1);
          next.splice(toIdx,0,removed);
          setQuickAccess(next);
          setDragIdx(null);setOverIdx(null);
        };
        return(
          <div className="df-g2">
            <div className="df-card">
              <div className="df-card-hdr"><div className="df-card-title">Quick Access Order</div><span style={{fontSize:11,color:"var(--t2)"}}>Drag to reorder</span></div>
              {enabled.length===0&&<div style={{fontSize:12,color:"var(--t2)",padding:"8px 0"}}>No items enabled — add some from the list below.</div>}
              {enabled.map((item,idx)=>(
                <div key={item.id}
                  draggable
                  onDragStart={()=>setDragIdx(idx)}
                  onDragOver={e=>{e.preventDefault();setOverIdx(idx);}}
                  onDrop={()=>drop(idx)}
                  onDragEnd={()=>{setDragIdx(null);setOverIdx(null);}}
                  style={{
                    display:'flex',alignItems:'center',gap:10,padding:'8px 10px',
                    borderRadius:'var(--r)',marginBottom:4,cursor:'grab',
                    background:overIdx===idx?'var(--accent3)':'var(--bg2)',
                    border:`1px solid ${overIdx===idx?'var(--accent)':'var(--border)'}`,
                    opacity:dragIdx===idx?0.45:1,transition:'all .1s',
                  }}>
                  <span style={{color:'var(--t2)',fontSize:12,cursor:'grab'}}>⠿</span>
                  <span style={{fontSize:15}}>{item.icon}</span>
                  <span style={{flex:1,fontSize:13,fontWeight:500}}>{item.label}</span>
                  <button onClick={()=>setQuickAccess(qa=>qa.filter(x=>x!==item.id))}
                    style={{background:'transparent',border:'none',color:'var(--t2)',cursor:'pointer',fontSize:13,padding:'0 2px'}} title="Remove">✕</button>
                </div>
              ))}
              {available.length>0&&<>
                <div style={{fontSize:10,fontWeight:700,color:'var(--t2)',letterSpacing:'.9px',textTransform:'uppercase',padding:'10px 0 6px'}}>Add more</div>
                {available.map(item=>(
                  <div key={item.id} className="df-qa-item" style={{cursor:'pointer'}} onClick={()=>setQuickAccess(qa=>[...qa,item.id])}>
                    <div className="df-qa-check"><span style={{fontSize:10,color:'var(--t2)'}}>+</span></div>
                    <span style={{fontSize:14}}>{item.icon}</span>
                    <span style={{fontSize:13,fontWeight:500,color:'var(--t2)'}}>{item.label}</span>
                  </div>
                ))}
              </>}
            </div>
            <div className="df-card">
              <div className="df-card-hdr"><div className="df-card-title">Sidebar Preview</div></div>
              <div style={{fontSize:10,fontWeight:700,color:'var(--t2)',letterSpacing:'.9px',textTransform:'uppercase',padding:'4px 8px 8px'}}>Quick Access</div>
              {quickAccess.length===0&&<div style={{fontSize:12,color:'var(--t2)',padding:8}}>No items selected</div>}
              {quickAccess.map(id=>{
                const item=ALL_NAV_ITEMS.find(n=>n.id===id);
                if(!item) return null;
                return<div key={id} className="df-nav-item" style={{pointerEvents:'none'}}><span className="df-nav-icon">{item.icon}</span>{item.label}</div>;
              })}
            </div>
          </div>
        );
      })()}
    </div>
  );
}

// ── Icon helper ──────────────────────────────────────────
// Servers in DiscordForge don't store an emoji icon — derive one from name.
const ICON_POOL = ["🖥️","💻","🎮","🌐","🔧","🏰","📡","⚡","🛡️","🌍","🎯","🔥"];
function serverIcon(name, idx) {
  if (!name) return ICON_POOL[idx % ICON_POOL.length];
  const seed = name.charCodeAt(0) + name.length;
  return ICON_POOL[seed % ICON_POOL.length];
}

// ── Root App ─────────────────────────────────────────────

export default function App() {
  const [page,setPage]=useState("dashboard");
  const [serverId,setServerId]=useState(null);
  const [theme,setTheme]=useState(()=>localStorage.getItem('df_theme')||'forge');
  const [servers,setServers]=useState([]);
  const [liveMap,setLiveMap]=useState({});
  const [bot,setBot]=useState(BOT_DEFAULT);
  const [botList,setBotList]=useState([]);
  const [events,setEvents]=useState([]);
  const [profile,setProfile]=useState(null);
  const [avatarUrl,setAvatarUrl]=useState('');
  const [loading,setLoading]=useState(true);
  const [wizardOpen,setWizardOpen]=useState(false);
  const [quickAccess,setQuickAccess]=useState(()=>{
    try{ const s=localStorage.getItem('df_qa'); return s?JSON.parse(s):["activity","integrations","collaborators"]; }
    catch{ return ["activity","integrations","collaborators"]; }
  });
  // Auth state — read ?auth= URL param to start on the right view
  const [authView,setAuthView]=useState(()=>{
    const p = new URLSearchParams(window.location.search).get('auth');
    return (p==='register'||p==='forgot') ? p : 'login';
  });
  const [isLoggedOut,setIsLoggedOut]=useState(false);
  // Increment to re-run the data load useEffect (e.g. after login)
  const [loadKey,setLoadKey]=useState(0);
  // Invite token from URL (e.g. /app/invite/<token>)
  const [inviteToken]=useState(()=>{
    const m = window.location.pathname.match(/\/app\/invite\/([^/]+)/);
    return m ? m[1] : null;
  });

  // Listen for session expiry from any apiFetch call
  useEffect(()=>{
    const handler=()=>{ setIsLoggedOut(true); setLoading(false); };
    window.addEventListener('df:auth-expired', handler);
    return ()=>window.removeEventListener('df:auth-expired', handler);
  },[]);

  // Load all app data — re-runs on loadKey change (login, server create, etc.)
  useEffect(()=>{
    setLoading(true);
    (async()=>{
      try {
        // liveStatus is intentionally excluded here — it makes live Discord API
        // calls that can block for 10+ seconds on Windows/gevent (SSL timing).
        // It loads separately below so it never delays the login screen.
        const [srvRes, evRes, botsRes, profRes] = await Promise.all([
          api.servers(),
          api.events(),
          api.bots(),
          api.profile(),
        ]);
        if (!srvRes) return; // redirected to login

        // Normalize servers
        const normalized = (srvRes.servers || []).map((s, i) => ({
          id:          s.server_id,
          name:        s.server_name,
          icon:        serverIcon(s.server_name, i),
          iconUrl:     null,
          memberCount: 0,
          online:      0,
          region:      "—",
          boostLevel:  0,
          boosts:      0,
          createdAt:   "—",
          guild_id:    s.guild_id,
        }));
        setServers(normalized);
        const firstId = normalized.length ? normalized[0].id : null;
        if (firstId) setServerId(firstId);

        if (evRes) setEvents(evRes);
        if (profRes) {
          setProfile(profRes);
          setCSRF(profRes.csrf_token);
          if (profRes.avatar_url) setAvatarUrl(profRes.avatar_url);
        } else { setIsLoggedOut(true); setLoading(false); return; }

        // Pick the first bot for the active server
        if (botsRes) {
          setBotList(botsRes.bots || []);
          const firstBot = (botsRes.bots || []).find(b => b.server_id === firstId)
                        || (botsRes.bots || [])[0];
          if (firstBot) {
            setBot(b => ({
              ...b,
              name:      firstBot.bot_name,
              id:        firstBot.bot_id,
              status:    firstBot.status,
              botType:   firstBot.bot_type,
              serverId:  firstBot.server_id,
              ping:      firstBot.ping   ?? b.ping,
              uptime:    firstBot.uptime ?? b.uptime,
              avatarUrl: firstBot.avatar_url || '',
            }));
          }
        }

        // Load live Discord status in the background — won't block the page.
        // On Windows + gevent this can take up to 10s due to SSL timing issues.
        api.liveStatus().then(liveRes => {
          if (!liveRes) return;
          const map = {};
          for (const entry of liveRes) map[entry.server_id] = entry;
          setLiveMap(map);
          setServers(ss => ss.map(s => {
            const live = map[s.id];
            if (!live) return s;
            return {
              ...s,
              memberCount: live.member_count   ?? s.memberCount,
              online:      live.online_count   ?? s.online,
              boostLevel:  live.boost_tier     ?? s.boostLevel,
              boosts:      live.boost_count    ?? s.boosts,
              iconUrl:     live.server_icon_url || s.iconUrl || null,
            };
          }));
        }).catch(()=>{});

      } catch(e) {
        console.error('Failed to load data:', e);
      } finally {
        setLoading(false);
      }
    })();
  }, [loadKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const server = servers.find(s=>s.id===serverId) || servers[0] || {id:"",name:"Loading…",icon:"⏳",memberCount:0,online:0,region:"—",boostLevel:0,boosts:0,createdAt:"—"};
  const live = liveMap[server.id] || null;

  // Keep bot in sync with active server whenever serverId or botList changes
  useEffect(()=>{
    if (!botList.length) return;
    const match = botList.find(b=>b.server_id===server.id) || botList[0];
    if (match) setBot(b=>({...b, name:match.bot_name, id:match.bot_id, status:match.status, botType:match.bot_type, serverId:match.server_id, ping:match.ping??b.ping, uptime:match.uptime??b.uptime, avatarUrl:match.avatar_url||b.avatarUrl||''}));
  }, [server.id, botList]);

  const PAGE_TITLES={
    dashboard:"Dashboard", server:"Server Settings", bot:"Bot Management",
    inspector:"Inspector", members:"Members", scripts:"Script Library", user:"Account",
    integrations:"Integrations", collaborators:"Collaborators",
    settings:"Settings", activity:"Activity Log",
    assets:"Assets", agent:"Agent", stats:"Stats",
  };
  const navItems=[
    {id:"dashboard", icon:"📊",label:"Dashboard"},
    {id:"server",    icon:"🏰",label:"Server"},
    {id:"bot",       icon:"🤖",label:"Bot"},
    {id:"members",   icon:"👥",label:"Members"},
    {id:"scripts",   icon:"📦",label:"Scripts"},
    {id:"settings",  icon:"⚙️",label:"Settings"},
  ];
  const qaItems=quickAccess.map(id=>ALL_NAV_ITEMS.find(n=>n.id===id)).filter(Boolean);

  const handleCreated=(form)=>{
    setWizardOpen(false);
    Promise.all([api.servers(), api.bots()]).then(([res, botsRes])=>{
      if (!res) return;
      const normalized = (res.servers||[]).map((s,i)=>({
        id:s.server_id, name:s.server_name, icon:serverIcon(s.server_name,i),
        iconUrl:null, memberCount:0, online:0, region:"—", boostLevel:0, boosts:0, createdAt:"—", guild_id:s.guild_id,
      }));
      setServers(normalized);
      const created = normalized.find(s=>s.id===form.server_id) || normalized[normalized.length-1];
      if (created) setServerId(created.id);
      if (botsRes) {
        setBotList(botsRes.bots || []);
        const newBot = (botsRes.bots||[]).find(b=>b.server_id===form.server_id);
        if (newBot) setBot(b=>({...b, name:newBot.bot_name, id:newBot.bot_id, status:newBot.status, serverId:newBot.server_id, ping:newBot.ping??b.ping, uptime:newBot.uptime??b.uptime, avatarUrl:newBot.avatar_url||''}));
      }
    });
    setPage("dashboard");
  };

  // Invite flow — show before auth check so logged-in users can accept
  if (inviteToken && !loading) {
    return (
      <>
        <style>{getRootCSS(theme)+CSS}</style>
        <InvitePage token={inviteToken} onDone={()=>{ window.history.replaceState({},'','/app/'); setIsLoggedOut(false); setLoadKey(k=>k+1); }}/>
      </>
    );
  }

  // Auth walls — show login/register/forgot when not authenticated
  if (isLoggedOut) {
    const onLogin=()=>{ setIsLoggedOut(false); setLoadKey(k=>k+1); };
    return (
      <>
        <style>{getRootCSS(theme)+CSS}</style>
        {authView==="login"     && <LoginPage          onLogin={onLogin} goRegister={()=>setAuthView("register")} goForgot={()=>setAuthView("forgot")}/>}
        {authView==="register"  && <RegisterPage       onDone={()=>setAuthView("login")} goLogin={()=>setAuthView("login")}/>}
        {authView==="forgot"    && <ForgotPasswordPage onDone={()=>setAuthView("login")} goLogin={()=>setAuthView("login")}/>}
      </>
    );
  }

  const applyTheme = (id) => {
    setTheme(id);
    localStorage.setItem('df_theme', id);
  };
  const updateQuickAccess = (fn) => {
    setQuickAccess(prev => {
      const next = typeof fn === 'function' ? fn(prev) : fn;
      try { localStorage.setItem('df_qa', JSON.stringify(next)); } catch{}
      return next;
    });
  };

  const Overlay = getOverlay(theme);
  return (
    <>
      <style>{getRootCSS(theme)+CSS}</style>
      <ToastContainer/>
      {Overlay&&<Overlay/>}
      <div className="df-app" style={Overlay?{position:'relative',zIndex:1}:undefined}>
        <div className="df-rail">
          <div className="df-rail-logo" onClick={()=>setPage("dashboard")} title="DiscordForge">
            <img src="/uploads/DiscordForge.jpg" alt="DF" style={{width:32,height:32,borderRadius:8,objectFit:"cover"}} onError={e=>{e.target.style.display='none';e.target.nextSibling.style.display='flex';}} />
            <span style={{display:"none",fontSize:13,fontWeight:800,color:"#fff",letterSpacing:-0.5}}>DF</span>
          </div>
          <div className="df-rail-div"/>
          {servers.map(s=>{
            const initials=(s.name||"?").split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase();
            const hue=(s.name.charCodeAt(0)*47)%360;
            const isActive=serverId===s.id;
            return (
              <div key={s.id} className={`df-srv-btn ${isActive?"active":""}`} title={s.name} onClick={()=>{setServerId(s.id);setPage("dashboard");}}>
                {s.iconUrl
                  ? <img src={s.iconUrl} alt={s.name} style={{width:36,height:36,borderRadius:isActive?14:12,objectFit:'cover',transition:'border-radius .15s',flexShrink:0}}/>
                  : <div style={{width:36,height:36,borderRadius:isActive?14:12,background:`hsl(${hue},55%,38%)`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:13,fontWeight:700,color:"#fff",transition:"border-radius .15s",flexShrink:0}}>{initials}</div>
                }
              </div>
            );
          })}
          <div className="df-rail-add" title="Create Server" onClick={()=>setWizardOpen(true)}>+</div>
        </div>

        <nav className="df-sidebar">
          <div className="df-sb-hdr">
            <div className="df-srv-card">
              <span className="df-srv-card-icon">{server.icon}</span>
              <div style={{flex:1,minWidth:0}}>
                <div className="df-srv-card-name">{server.name}</div>
                <div style={{fontSize:10,color:"var(--t2)",fontFamily:"var(--mono)"}}>{server.online} online</div>
              </div>
              <div className="df-srv-card-dot"/>
            </div>
          </div>
          <div className="df-sb-scroll">
            <div className="df-nav-label">Navigation</div>
            {navItems.map(n=>(
              <div key={n.id} className={`df-nav-item ${page===n.id?"active":""}`} onClick={()=>setPage(n.id)}>
                <span className="df-nav-icon">{n.icon}</span>
                {n.label}
                {n.badge&&<span className={`df-nav-badge ${n.badgeCls||""}`}>{n.badge}</span>}
              </div>
            ))}
            {qaItems.length>0&&<>
              <div className="df-nav-label" style={{marginTop:8}}>Quick Access</div>
              {qaItems.map(n=>(
                <div key={n.id} className={`df-nav-item ${page===n.id?"active":""}`} onClick={()=>setPage(n.id)}><span className="df-nav-icon">{n.icon}</span>{n.label}</div>
              ))}
            </>}
          </div>
          <div className="df-sb-footer" onClick={()=>setPage("user")}>
            <div className="df-footer-av" style={{overflow:'hidden',padding:avatarUrl?0:undefined}}>
              {avatarUrl
                ? <img src={avatarUrl} alt="" style={{width:'100%',height:'100%',objectFit:'cover',borderRadius:'50%'}}/>
                : (profile?.username?.[0]?.toUpperCase()||'?')
              }
            </div>
            <div style={{flex:1}}>
              <div style={{fontSize:12,fontWeight:700}}>{profile?.username||'…'}</div>
              <div style={{fontSize:10,color:"var(--t2)"}}>{profile?.server_count??'—'} server{profile?.server_count!==1?'s':''} · {profile?.plan||'free'}</div>
            </div>
            <div className="df-status-dot"/>
          </div>
        </nav>

        <div className="df-main">
          <div className="df-topbar">
            <div className="df-tb-title">{PAGE_TITLES[page]||page}</div>
            <div style={{flex:1}}/>
            {bot.status==='online'
              ? <div className="df-tb-pill green"><div style={{width:6,height:6,borderRadius:"50%",background:"var(--green)"}}/>⏱ {bot.uptime||'online'}</div>
              : <div className="df-tb-pill" style={{color:"var(--t2)"}}><div style={{width:6,height:6,borderRadius:"50%",background:"var(--t2)"}}/>Offline</div>
            }
            <div className="df-tb-pill">{server.icon} {server.name}</div>
          </div>
          <div className="df-content">
            {loading && <div style={{padding:40,textAlign:"center",color:"var(--t2)",fontFamily:"var(--mono)"}}>Loading…</div>}
            {!loading && page==="dashboard" &&<DashboardPage server={server} live={live} events={events} bot={bot} onNavigate={setPage}/>}
            {!loading && page==="stats"     &&<DashboardPage server={server} live={live} events={events} bot={bot} onNavigate={setPage}/>}
            {!loading && page==="server"    &&<ServerPage    server={server} onIconUpdate={iconUrl=>setServers(ss=>ss.map(s=>s.id===server.id?{...s,iconUrl}:s))}/>}
            {!loading && page==="bot"       &&<BotPage       bot={bot} server={server} onNav={setPage}/>}
            {!loading && page==="members"   &&<MembersPage   server={server}/>}
            {!loading && page==="scripts"   &&<ScriptsPage   server={server}/>}
            {!loading && page==="inspector"    &&<InspectorHub    serverList={servers}/>}
            {!loading && page==="integrations" &&<IntegrationsPage  server={server}/>}
            {!loading && page==="collaborators"&&<CollaboratorsPage server={server}/>}
            {!loading && page==="settings"     &&<SettingsPage      server={server} onServerDeleted={()=>{ api.servers().then(r=>{ if(r){ const n=(r.servers||[]).map((s,i)=>({id:s.server_id,name:s.server_name,icon:serverIcon(s.server_name,i),iconUrl:null,memberCount:0,online:0,region:"—",boostLevel:0,boosts:0,createdAt:"—",guild_id:s.guild_id})); setServers(n); setServerId(n[0]?.id||null); } }); setPage("dashboard"); }}/>}
            {!loading && page==="activity"     &&<ActivityPage      server={server}/>}
            {!loading && page==="assets"       &&<AssetsPage        server={server}/>}
            {!loading && page==="agent"        &&<AgentPage/>}
            {!loading && page==="user"         &&<UserPage quickAccess={quickAccess} setQuickAccess={updateQuickAccess} profile={profile} setProfile={setProfile} theme={theme} applyTheme={applyTheme} avatarUrl={avatarUrl} onAvatarChange={url=>{setAvatarUrl(url);}}/>}
          </div>
          <div className="df-app-footer">
            <span>DiscordForge</span>
            <span className="sep">·</span>
            <span>{server.name}</span>
            <span className="sep">·</span>
            <span style={{color:"var(--green)"}}>● connected</span>
            <span style={{flex:1}}/>
            <span>{new Date().getFullYear()}</span>
          </div>
        </div>

        <CreateServerModal open={wizardOpen} onClose={()=>setWizardOpen(false)} onCreated={handleCreated}/>
      </div>
    </>
  );
}
