import { useState, useEffect } from "react";

// ── Permission tier → Discord permission names ────────────
const PERM_TIERS = {
  basic:         ['view_channels','send_messages','read_message_history','add_reactions','connect','speak'],
  standard:      ['view_channels','send_messages','read_message_history','add_reactions','connect','speak','embed_links','attach_files','use_application_commands'],
  'standard+':   ['view_channels','send_messages','read_message_history','add_reactions','connect','speak','embed_links','attach_files','use_application_commands','use_external_emojis','change_nickname'],
  moderation:    ['view_channels','send_messages','read_message_history','add_reactions','connect','speak','embed_links','attach_files','use_application_commands','manage_messages','mute_members','deafen_members','move_members','kick_members'],
  administrator: ['administrator'],
};

// ── Wizard form → Flask /setup FormData ──────────────────
function buildSetupFormData(form) {
  // Channels: group by cat → categoriesData, carry nsfw/slowmode/private/forum
  const privateCategories = new Set(form.privateCategories || []);
  const catMap = {};
  for (const ch of (form.channels || [])) {
    if (!catMap[ch.cat]) catMap[ch.cat] = {
      name: ch.cat, private: privateCategories.has(ch.cat), roles: [],
      textChannels: [], voiceChannels: [], forumChannels: []
    };
    if (ch.type === 'voice')       catMap[ch.cat].voiceChannels.push({ name: ch.name });
    else if (ch.type === 'forum')  catMap[ch.cat].forumChannels.push({ name: ch.name });
    else catMap[ch.cat].textChannels.push({ name: ch.name, nsfw: !!ch.nsfw, slowmode: ch.slowmode||0, private: !!ch.private });
  }

  const welcomeTemplate = form.welcomeTemplate || form.template === 'community' ? 'yes' : 'no';
  const communityMode   = form.communityMode   || form.template === 'community' ? 'yes' : 'no';

  // Roles: skip @everyone, map tier to permissions
  const customRoles = (form.roles || [])
    .filter(r => r.name !== '@everyone')
    .map(r => ({
      name:        r.name,
      color:       r.color || '#99aab5',
      hoist:       r.hoist || false,
      permissions: PERM_TIERS[r.perms] || [],
    }));

  const fd = new FormData();
  fd.append('server_name',      form.name);
  fd.append('guild_id',         form.guildId || '');
  fd.append('maintBotToken',    form.botToken || '');
  fd.append('maintBotName',     form.botName  || 'My Bot');
  fd.append('maintBotClientId', form.botClientId || '');
  fd.append('welcome_template', welcomeTemplate);
  fd.append('community_server', communityMode);
  fd.append('customRolesData',   JSON.stringify(customRoles));
  fd.append('categoriesData',    JSON.stringify(Object.values(catMap)));
  fd.append('moderatorUsersData','[]');
  fd.append('assetsData',        JSON.stringify({emoji:[],stickers:[],soundboard:[]}));
  fd.append('webhooksData',      '[]');
  fd.append('communitySettingsData', JSON.stringify({verification_level:'medium',content_filter:'all_members',default_notifications:'only_mentions',system_channel:''}));
  return fd;
}

const REGIONS = [
  { id:"eu-west", name:"EU West",  flag:"🇪🇺", ping:"18ms" },
  { id:"eu-east", name:"EU East",  flag:"🇪🇺", ping:"31ms" },
  { id:"us-east", name:"US East",  flag:"🇺🇸", ping:"42ms" },
  { id:"us-west", name:"US West",  flag:"🇺🇸", ping:"68ms" },
  { id:"asia",    name:"Asia",     flag:"🌏", ping:"142ms" },
  { id:"brazil",  name:"Brazil",   flag:"🇧🇷", ping:"118ms" },
];

const TEMPLATES = [
  { id:"blank",     icon:"📄", name:"Blank Server",       desc:"Start from scratch with no presets",                                      channels:0, roles:1,  scripts:0, color:"#5b6cf9",
    presets:{ channels:[{name:"general",type:"text",cat:"General"}], roles:["@everyone"], scripts:[] } },
  { id:"gaming",    icon:"🎮", name:"Gaming Community",   desc:"Voice channels, LFG, tournaments, game-specific text channels",           channels:9, roles:5,  scripts:3, color:"#23d18b",
    presets:{ channels:[
      {name:"welcome",type:"text",cat:"Info"},{name:"rules",type:"text",cat:"Info"},{name:"announcements",type:"text",cat:"Info"},
      {name:"general",type:"text",cat:"Community"},{name:"lfg",type:"text",cat:"Community"},{name:"clips",type:"text",cat:"Community"},
      {name:"Gaming Lobby",type:"voice",cat:"Voice"},{name:"Squad 1",type:"voice",cat:"Voice"},{name:"Squad 2",type:"voice",cat:"Voice"},
    ], roles:["@everyone","Member","Veteran","Moderator","Admin"], scripts:["Auto-Role on Join","Welcome Message","Voice Activity Log"] } },
  { id:"community", icon:"💬", name:"Community Hub",      desc:"Discussion-focused with announcements, threads and events",              channels:7, roles:4,  scripts:4, color:"#f472b6",
    presets:{ channels:[
      {name:"rules",type:"text",cat:"Info"},{name:"announcements",type:"text",cat:"Info"},
      {name:"general",type:"text",cat:"Community"},{name:"off-topic",type:"text",cat:"Community"},{name:"introductions",type:"text",cat:"Community"},
      {name:"Hangout",type:"voice",cat:"Voice"},{name:"Events",type:"voice",cat:"Voice"},
    ], roles:["@everyone","Member","Active","Moderator"], scripts:["Welcome Message","Reaction Roles","Poll Command","XP & Levelling"] } },
  { id:"dev",       icon:"💻", name:"Dev Team",            desc:"Code reviews, standups, CI alerts, project channels",                    channels:8, roles:6,  scripts:3, color:"#00d4ff",
    presets:{ channels:[
      {name:"general",type:"text",cat:"General"},{name:"announcements",type:"text",cat:"General"},
      {name:"frontend",type:"text",cat:"Engineering"},{name:"backend",type:"text",cat:"Engineering"},{name:"devops",type:"text",cat:"Engineering"},
      {name:"ci-alerts",type:"text",cat:"Automation"},
      {name:"Standup",type:"voice",cat:"Meetings"},{name:"Pair Programming",type:"voice",cat:"Meetings"},
    ], roles:["@everyone","Junior","Mid","Senior","Lead","Admin"], scripts:["Auto-Role on Join","Ticket System","Voice Activity Log"] } },
  { id:"creator",   icon:"🎨", name:"Creator Hub",         desc:"Fan engagement, content channels, exclusive perks",                     channels:8, roles:5,  scripts:4, color:"#c084fc",
    presets:{ channels:[
      {name:"welcome",type:"text",cat:"Info"},{name:"announcements",type:"text",cat:"Info"},
      {name:"general",type:"text",cat:"Community"},{name:"fan-art",type:"text",cat:"Content"},{name:"behind-the-scenes",type:"text",cat:"Content"},
      {name:"supporter-only",type:"text",cat:"Exclusive"},
      {name:"Stream Chat",type:"voice",cat:"Live"},{name:"Hangout",type:"voice",cat:"Live"},
    ], roles:["@everyone","Fan","Supporter","Moderator","Creator"], scripts:["Welcome Message","XP & Levelling","Reaction Roles","Poll Command"] } },
  { id:"clone",     icon:"📋", name:"Clone Existing",      desc:"Duplicate settings from one of your existing servers",                  channels:"~", roles:"~", scripts:"~", color:"#f9c846", presets:null },
];

const ICON_OPTIONS = ["🎮","💻","🌸","💰","📚","🎨","🎵","🏆","👾","💡","💪","🌍","🎯","🔥","⚡","🛡️","🎯","🎲","🏅","🤖"];

const SCRIPT_LIBRARY = [
  { id:"sc1", name:"Auto-Role on Join",  cat:"Automation", desc:"Assigns a default role to every new member",        installs:2841 },
  { id:"sc2", name:"Welcome Message",    cat:"Engagement",  desc:"Rich embed welcome card on join",                  installs:5120 },
  { id:"sc3", name:"Anti-Raid Lockdown", cat:"Security",    desc:"Detects mass-joins and locks channels",            installs:1230 },
  { id:"sc4", name:"Ticket System",      cat:"Support",     desc:"Private support threads via slash command",        installs:3890 },
  { id:"sc5", name:"XP & Levelling",     cat:"Engagement",  desc:"Tracks message activity, awards level roles",     installs:7210 },
  { id:"sc6", name:"Reaction Roles",     cat:"Automation",  desc:"Assign roles by reacting to messages",            installs:9320 },
  { id:"sc7", name:"Voice Activity Log", cat:"Logging",     desc:"Logs voice join/leave events",                    installs:2010 },
  { id:"sc8", name:"Poll Command",       cat:"Utility",     desc:"Formatted polls with emoji reactions",            installs:3760 },
];

const ROLE_PRESETS = {
  gaming:    [{name:"@everyone",color:"#888",perms:"basic"},{name:"Member",color:"#5865f2",perms:"standard"},{name:"Veteran",color:"#eb459e",perms:"standard+"},{name:"Moderator",color:"#57f287",perms:"moderation"},{name:"Admin",color:"#fee75c",perms:"administrator"}],
  community: [{name:"@everyone",color:"#888",perms:"basic"},{name:"Member",color:"#5865f2",perms:"standard"},{name:"Active",color:"#eb459e",perms:"standard+"},{name:"Moderator",color:"#57f287",perms:"moderation"}],
  dev:       [{name:"@everyone",color:"#888",perms:"basic"},{name:"Junior",color:"#5b6cf9",perms:"standard"},{name:"Mid",color:"#00d4ff",perms:"standard+"},{name:"Senior",color:"#23d18b",perms:"standard+"},{name:"Lead",color:"#f9c846",perms:"moderation"},{name:"Admin",color:"#f05a5a",perms:"administrator"}],
  creator:   [{name:"@everyone",color:"#888",perms:"basic"},{name:"Fan",color:"#5865f2",perms:"standard"},{name:"Supporter",color:"#f47fff",perms:"standard+"},{name:"Moderator",color:"#57f287",perms:"moderation"},{name:"Creator",color:"#fee75c",perms:"administrator"}],
  blank:     [{name:"@everyone",color:"#888",perms:"basic"}],
  clone:     [{name:"@everyone",color:"#888",perms:"basic"}],
};

const WIZARD_CSS = `
@keyframes fadeIn{from{opacity:0}to{opacity:1}}
@keyframes slideUp{from{opacity:0;transform:translateY(20px)}to{opacity:1;transform:translateY(0)}}
@keyframes successPulse{0%,100%{transform:scale(1)}50%{transform:scale(1.06)}}
@keyframes spin{to{transform:rotate(360deg)}}

.modal-overlay{position:fixed;inset:0;background:rgba(3,5,9,0.78);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);display:flex;align-items:center;justify-content:center;z-index:1000;animation:fadeIn .2s ease-out}
.modal{width:min(1100px,calc(100vw - 80px));height:min(720px,calc(100vh - 80px));background:var(--bg1);border:1px solid var(--border2);border-radius:18px;box-shadow:0 30px 80px rgba(0,0,0,.6),0 0 0 1px var(--border);display:flex;flex-direction:column;overflow:hidden;animation:slideUp .25s ease-out}
.modal-hdr{padding:20px 28px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:14px}
.modal-h-icon{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,var(--green),var(--cyan));display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.modal-h-title{font-size:18px;font-weight:800;letter-spacing:-.4px}
.modal-h-sub{font-size:12px;color:var(--t2);font-family:var(--mono);margin-top:2px}
.modal-h-close{margin-left:auto;width:32px;height:32px;border-radius:8px;background:transparent;border:1px solid var(--border);color:var(--t2);cursor:pointer;display:flex;align-items:center;justify-content:center;transition:all .15s;font-size:16px}
.modal-h-close:hover{color:var(--t0);border-color:var(--border2);background:var(--bg3)}

.stepper{display:flex;padding:0 28px;background:var(--bg0);border-bottom:1px solid var(--border);overflow-x:auto}
.wiz-step{display:flex;align-items:center;gap:10px;padding:14px 0;margin-right:32px;cursor:pointer;flex-shrink:0;position:relative;font-size:13px}
.wiz-step::after{content:'';position:absolute;bottom:-1px;left:0;right:32px;height:2px;background:transparent;transition:background .15s}
.wiz-step:last-child::after{right:0}
.step-num{width:24px;height:24px;border-radius:50%;background:var(--bg3);border:1px solid var(--border2);display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;font-family:var(--mono);color:var(--t2);transition:all .2s;flex-shrink:0}
.step-lbl{font-weight:600;color:var(--t2);transition:color .15s;white-space:nowrap}
.wiz-step.done .step-num{background:var(--green);border-color:var(--green);color:#04130b}
.wiz-step.done .step-lbl{color:var(--t1)}
.wiz-step.done::after{background:rgba(35,209,139,.4)}
.wiz-step.current .step-num{background:var(--accent);border-color:var(--accent);color:#fff;box-shadow:0 0 0 4px rgba(91,108,249,.18)}
.wiz-step.current .step-lbl{color:var(--t0)}
.wiz-step.current::after{background:var(--accent)}

.modal-body{flex:1;overflow-y:auto;padding:28px 32px;display:flex;gap:24px;min-height:0}
.modal-body.no-preview{display:block}
.body-main{flex:1;min-width:0}
.body-preview{width:280px;min-width:280px;flex-shrink:0;background:var(--bg2);border:1px solid var(--border);border-radius:var(--rl);padding:18px;overflow-y:auto;align-self:flex-start;max-height:100%;position:sticky;top:0}

.modal-ftr{padding:16px 28px;border-top:1px solid var(--border);display:flex;align-items:center;gap:12px;background:var(--bg0)}
.ftr-progress{font-size:11px;color:var(--t2);font-family:var(--mono)}

.step-title{font-size:20px;font-weight:800;letter-spacing:-.5px;margin-bottom:4px}
.step-sub{font-size:13px;color:var(--t1);margin-bottom:22px}
.section-label{font-size:11px;font-weight:700;color:var(--t2);letter-spacing:.9px;text-transform:uppercase;margin-bottom:10px}

.wiz-input{background:var(--bg2);border:1px solid var(--border2);color:var(--t0);font-family:var(--sans);font-size:14px;padding:10px 14px;border-radius:var(--r);width:100%;outline:none;transition:border-color .15s}
.wiz-input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(91,108,249,.15)}
.input-hint{font-size:11px;color:var(--t2);margin-top:6px;font-family:var(--mono)}
.input-err{color:var(--red)}

.icon-grid{display:grid;grid-template-columns:repeat(10,1fr);gap:6px}
.icon-pick{aspect-ratio:1;background:var(--bg2);border:1px solid var(--border);border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;cursor:pointer;transition:all .12s}
.icon-pick:hover{background:var(--bg3);border-color:var(--border2);transform:scale(1.08)}
.icon-pick.sel{background:var(--accent3);border-color:var(--accent);box-shadow:0 0 0 2px var(--accent),0 0 14px rgba(91,108,249,.3)}

.tpl-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.tpl-card{background:var(--bg2);border:1.5px solid var(--border);border-radius:var(--rl);padding:18px;cursor:pointer;transition:all .15s;position:relative;overflow:hidden}
.tpl-card:hover{background:var(--bg3);border-color:var(--border2);transform:translateY(-2px)}
.tpl-card.sel{border-color:var(--accent);background:linear-gradient(135deg,var(--accent3),var(--bg2))}
.tpl-card.sel::after{content:'✓';position:absolute;top:10px;right:12px;width:22px;height:22px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;color:#fff}
.tpl-icon{font-size:30px;margin-bottom:10px}
.tpl-name{font-size:15px;font-weight:700;margin-bottom:4px}
.tpl-desc{font-size:12px;color:var(--t1);line-height:1.5;margin-bottom:12px;min-height:36px}
.tpl-meta{display:flex;gap:14px;font-size:11px;color:var(--t2);font-family:var(--mono)}
.tpl-meta span strong{color:var(--t1);font-weight:600}

.ch-section{margin-bottom:14px}
.ch-cat-row{display:flex;align-items:center;gap:6px;font-size:10px;font-weight:700;color:var(--t2);letter-spacing:.9px;text-transform:uppercase;padding:6px 4px;margin-bottom:4px}
.wiz-ch-item{display:flex;align-items:center;gap:8px;padding:8px 12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;margin-bottom:4px;font-size:13px}
.ch-item-type{color:var(--t2);font-size:14px;width:18px;text-align:center}
.ch-item-name{flex:1}
.ch-item-name input{background:transparent;border:none;color:var(--t0);font-family:var(--sans);font-size:13px;font-weight:500;outline:none;width:100%}
.ch-item-name input:focus{color:var(--accent2)}
.ch-item-del{background:transparent;border:none;color:var(--t2);cursor:pointer;font-size:14px;padding:2px 6px;border-radius:4px;transition:all .12s}
.ch-item-del:hover{color:var(--red);background:rgba(240,90,90,.1)}
.ch-add-row{display:flex;gap:6px;margin-top:6px}
.ch-add-btn{flex:1;background:transparent;border:1px dashed var(--border2);border-radius:8px;padding:7px 10px;font-size:12px;color:var(--t2);cursor:pointer;display:flex;align-items:center;justify-content:center;gap:5px;transition:all .12s}
.ch-add-btn:hover{color:var(--green);border-color:var(--green);background:rgba(35,209,139,.04)}

.role-item{display:flex;align-items:center;gap:10px;padding:10px 12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;margin-bottom:5px}
.role-dot{width:12px;height:12px;border-radius:50%;flex-shrink:0;box-shadow:0 0 6px currentColor}
.role-handle{color:var(--t2);font-family:var(--mono);font-size:11px;cursor:grab}
.role-perm-sel{background:var(--bg3);border:1px solid var(--border);color:var(--t1);cursor:pointer;padding:3px 8px;border-radius:4px;font-family:var(--mono);font-size:10px}

.script-list{display:flex;flex-direction:column;gap:8px}
.script-item{display:flex;align-items:center;gap:12px;padding:12px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);cursor:pointer;transition:all .12s}
.script-item:hover{background:var(--bg3);border-color:var(--border2)}
.script-item.sel{border-color:var(--green);background:linear-gradient(90deg,rgba(35,209,139,.08),var(--bg2))}
.script-cb{width:18px;height:18px;border-radius:4px;border:1.5px solid var(--border2);background:var(--bg3);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:all .15s;font-size:11px;color:#fff}
.script-item.sel .script-cb{background:var(--green);border-color:var(--green)}
.script-body{flex:1;min-width:0}
.script-name{font-size:13px;font-weight:600}
.script-desc-sm{font-size:11px;color:var(--t1);margin-top:2px}
.script-meta-sm{display:flex;gap:8px;font-size:10px;color:var(--t2);font-family:var(--mono);margin-top:4px}
.script-cat-badge{font-size:9px;font-weight:600;font-family:var(--mono);padding:2px 6px;border-radius:10px;background:var(--bg3);color:var(--t1);text-transform:uppercase;letter-spacing:.5px}

.review-section{padding:14px 0;border-bottom:1px solid var(--border)}
.review-section:last-child{border-bottom:none;padding-bottom:0}
.review-h{font-size:11px;font-weight:700;color:var(--t2);letter-spacing:.9px;text-transform:uppercase;margin-bottom:8px}
.review-row{display:flex;justify-content:space-between;align-items:center;font-size:13px;padding:4px 0}
.review-row span:first-child{color:var(--t2);font-size:12px}
.review-row span:last-child{font-weight:600;color:var(--t0)}
.review-list{font-size:12px;color:var(--t1);line-height:1.7}

.preview-label{font-size:10px;font-weight:700;color:var(--t2);letter-spacing:.9px;text-transform:uppercase;margin-bottom:10px}
.preview-mockup{background:var(--bg0);border:1px solid var(--border);border-radius:10px;overflow:hidden}
.pm-header{padding:12px;background:linear-gradient(135deg,var(--bg2),var(--bg1));border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px}
.pm-icon{font-size:24px}
.pm-name{font-size:13px;font-weight:700;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pm-dot{width:7px;height:7px;border-radius:50%;background:var(--green);box-shadow:0 0 5px var(--green);flex-shrink:0}
.pm-body{padding:10px 12px;max-height:300px;overflow-y:auto}
.pm-cat{font-size:9px;font-weight:700;color:var(--t2);letter-spacing:.8px;text-transform:uppercase;padding:6px 2px 3px}
.pm-ch{display:flex;align-items:center;gap:6px;padding:4px 6px;font-size:11px;color:var(--t1);border-radius:4px}
.pm-ch:hover{background:var(--bg2)}
.pm-ch-type{color:var(--t2);font-size:12px;width:14px;text-align:center}
.pm-roles{margin-top:10px;display:flex;flex-wrap:wrap;gap:4px}
.pm-role{font-size:10px;font-family:var(--mono);padding:2px 7px;border-radius:10px;border:1px solid currentColor}

.success-wrap{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:50px 20px;text-align:center}
.success-ring{width:96px;height:96px;border-radius:50%;background:radial-gradient(circle,rgba(35,209,139,.25),rgba(35,209,139,.05) 70%);border:2px solid var(--green);display:flex;align-items:center;justify-content:center;font-size:42px;margin-bottom:24px;animation:successPulse 2s ease-in-out infinite;box-shadow:0 0 40px rgba(35,209,139,.3)}
.success-h1{font-size:26px;font-weight:800;letter-spacing:-.6px;margin-bottom:6px}
.success-p{font-size:14px;color:var(--t1);max-width:420px;margin-bottom:24px;line-height:1.6}
.success-meta{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:16px 22px;margin-bottom:24px;display:flex;gap:28px;font-size:12px}
.success-meta-item{display:flex;flex-direction:column;align-items:center;gap:4px}
.success-meta-val{font-size:20px;font-weight:800;color:var(--green);font-family:var(--mono)}
.success-meta-lbl{font-size:10px;color:var(--t2);text-transform:uppercase;letter-spacing:.7px}
.success-actions{display:flex;gap:10px}

.create-log{background:var(--bg0);border:1px solid var(--border);border-radius:var(--r);padding:14px;font-family:var(--mono);font-size:11px;line-height:1.8;max-height:200px;overflow-y:auto;margin-top:14px}
.log-l{display:flex;gap:8px}
.log-l-ts{color:var(--t2)}
.log-l-ok{color:var(--green)}
.log-l-info{color:var(--cyan)}

.wiz-spinner{width:32px;height:32px;border:3px solid rgba(255,255,255,.2);border-top-color:#fff;border-radius:50%;animation:spin .8s linear infinite}

.wiz-region-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}
.wiz-region-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:12px 14px;cursor:pointer;transition:all .12s;display:flex;align-items:center;gap:10px}
.wiz-region-card:hover{background:var(--bg3);border-color:var(--border2)}
.wiz-region-card.sel{background:var(--accent3);border-color:var(--accent)}
`;

// ── Step Components ──────────────────────────────────────

function StepDiscord({ form, setForm, error }) {
  const [validating, setValidating] = useState(false);
  const [tokenStatus, setTokenStatus] = useState(null); // null | {ok, bot_name, invite_url, in_guild} | {error}

  // Auto-validate when both fields look complete (debounced 900ms)
  useEffect(() => {
    const guildOk = /^\d{17,20}$/.test((form.guildId||'').trim());
    const tokenOk = (form.botToken||'').trim().length > 20;
    if (!guildOk || !tokenOk) { setTokenStatus(null); return; }

    setValidating(true);
    const tid = setTimeout(async () => {
      try {
        const res = await fetch('/api/validate-bot-token', {
          method: 'POST', credentials: 'include',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({token: form.botToken.trim(), guild_id: form.guildId.trim()}),
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          setTokenStatus(data);
          // Pre-fill bot name and client ID if not already set
          setForm(f => ({
            ...f,
            botName:     f.botName || data.bot_name || '',
            botClientId: data.client_id || f.botClientId || '',
          }));
        } else {
          setTokenStatus({error: data.error || 'Invalid token'});
        }
      } catch {
        setTokenStatus({error: 'Could not reach server'});
      } finally {
        setValidating(false);
      }
    }, 900);
    return () => clearTimeout(tid);
  }, [form.botToken, form.guildId]);

  const statusEl = validating
    ? <span style={{fontSize:11,fontFamily:"var(--mono)",color:"var(--t2)"}}>Validating…</span>
    : tokenStatus?.ok
      ? <span style={{fontSize:11,fontFamily:"var(--mono)",color:"var(--green)"}}>
          ✓ {tokenStatus.bot_name}
          {tokenStatus.in_guild === true  && ' · in server'}
          {tokenStatus.in_guild === false && <> · not in server — <a href={tokenStatus.invite_url} target="_blank" rel="noreferrer" style={{color:"var(--accent2)"}}>invite bot</a></>}
        </span>
      : tokenStatus?.error
        ? <span style={{fontSize:11,fontFamily:"var(--mono)",color:"var(--red)"}}>✗ {tokenStatus.error}</span>
        : null;

  return (
    <div>
      <div className="step-title">Connect Discord</div>
      <div className="step-sub">Provide your Discord server ID and bot token. The bot must already be invited to the server.</div>
      <div style={{marginBottom:20}}>
        <div className="section-label">Discord Server ID (Guild ID)</div>
        <input className="wiz-input" value={form.guildId||""} onChange={e=>setForm({...form,guildId:e.target.value.trim()})} placeholder="e.g. 1234567890123456789"/>
        <div className="input-hint">Right-click your server in Discord → Copy Server ID (Enable Developer Mode first)</div>
      </div>
      <div style={{marginBottom:8}}>
        <div className="section-label">Bot Token</div>
        <input className="wiz-input" type="password" value={form.botToken||""} onChange={e=>setForm({...form,botToken:e.target.value.trim()})} placeholder="Bot token from discord.com/developers"/>
        <div className="input-hint">The bot must be invited to the server with Administrator permission</div>
      </div>
      <div style={{display:"flex",alignItems:"center",gap:8,marginBottom:16}}>
        {statusEl}
        {!validating&&!tokenStatus&&form.botToken&&form.guildId&&(
          <span style={{fontSize:11,color:"var(--t2)",fontFamily:"var(--mono)"}}>validating automatically…</span>
        )}
      </div>
      <div style={{marginBottom:20}}>
        <div className="section-label">Bot Name <span style={{color:"var(--t2)",fontWeight:400}}>(auto-filled on valid token)</span></div>
        <input className="wiz-input" value={form.botName||""} onChange={e=>setForm({...form,botName:e.target.value})} placeholder="e.g. MyBot"/>
      </div>
      {error && <div style={{fontSize:12,color:"var(--red)",marginTop:8,fontFamily:"var(--mono)"}}>{error}</div>}
    </div>
  );
}

function StepBasics({ form, setForm, error }) {
  return (
    <div>
      <div className="step-title">Let's name your server</div>
      <div className="step-sub">Start with the basics — you can change everything later.</div>
      <div style={{marginBottom:22}}>
        <div className="section-label">Server Name</div>
        <input className="wiz-input" value={form.name} onChange={e=>setForm({...form,name:e.target.value})} placeholder="e.g. Midnight Gaming, My Dev Team…" maxLength={50}/>
        <div className={`input-hint ${error?"input-err":""}`}>{error || `${form.name.length}/50 characters`}</div>
      </div>
      <div style={{marginBottom:22}}>
        <div className="section-label">Pick an Icon</div>
        <div className="icon-grid">
          {ICON_OPTIONS.map(ic=>(
            <div key={ic} className={`icon-pick${form.icon===ic?" sel":""}`} onClick={()=>setForm({...form,icon:ic})}>{ic}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

function StepTemplate({ form, setForm }) {
  return (
    <div>
      <div className="step-title">Choose a starting point</div>
      <div className="step-sub">Templates pre-configure channels, roles and scripts. Customize everything in the next steps.</div>
      <div className="tpl-grid">
        {TEMPLATES.map(t=>(
          <div key={t.id} className={`tpl-card${form.template===t.id?" sel":""}`} onClick={()=>setForm({...form,template:t.id})}>
            <div className="tpl-icon" style={{color:t.color}}>{t.icon}</div>
            <div className="tpl-name">{t.name}</div>
            <div className="tpl-desc">{t.desc}</div>
            <div className="tpl-meta">
              <span><strong>{t.channels}</strong> channels</span>
              <span><strong>{t.roles}</strong> roles</span>
              <span><strong>{t.scripts}</strong> scripts</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StepChannels({ form, setForm }) {
  const channels = form.channels || [];
  const categories = [...new Set(channels.map(c=>c.cat))];
  const addCh = (type, cat) => setForm({...form, channels:[...channels,{name:type==="voice"?"New Voice":type==="forum"?"new-forum":"new-channel",type,cat,id:Date.now(),private:false,nsfw:false,slowmode:0}]});
  const updateCh = (id, patch) => setForm({...form, channels:channels.map(c=>c.id===id?{...c,...(typeof patch==="string"?{name:patch}:patch)}:c)});
  const removeCh = (id) => setForm({...form, channels:channels.filter(c=>c.id!==id)});
  const [newCat, setNewCat] = useState("");
  const [showCatInput, setShowCatInput] = useState(false);

  return (
    <div>
      <div className="step-title">Configure channels</div>
      <div className="step-sub">Add, rename or remove channels. Categories are created automatically.</div>
      {categories.length===0 && (
        <div style={{textAlign:"center",padding:"40px 20px",color:"var(--t2)",border:"1px dashed var(--border2)",borderRadius:"var(--r)",marginBottom:14}}>
          <div style={{fontSize:28,marginBottom:8}}>📂</div>
          <div style={{fontSize:13}}>No channels yet — add some below</div>
        </div>
      )}
      {categories.map(cat=>(
        <div key={cat} className="ch-section">
          <div className="ch-cat-row" style={{display:"flex",alignItems:"center",gap:8}}>
            <span>▾ {cat}</span>
            <label style={{display:"flex",alignItems:"center",gap:4,fontSize:11,color:"var(--t2)",cursor:"pointer",marginLeft:"auto"}}>
              <input type="checkbox"
                checked={!!(form.privateCategories||[]).includes(cat)}
                onChange={e=>{const pc=form.privateCategories||[];setForm({...form,privateCategories:e.target.checked?[...pc,cat]:pc.filter(x=>x!==cat)});}}
              />
              Private
            </label>
          </div>
          {channels.filter(c=>c.cat===cat).map(c=>(
            <div key={c.id} className="wiz-ch-item" style={{flexWrap:"wrap",gap:4}}>
              <span className="ch-item-type">{c.type==="voice"?"🔊":c.type==="forum"?"💬":"#"}</span>
              <div className="ch-item-name" style={{flex:1,minWidth:80}}><input value={c.name} onChange={e=>updateCh(c.id,e.target.value)}/></div>
              {c.type==="text"&&<>
                <label style={{display:"flex",alignItems:"center",gap:3,fontSize:10,color:"var(--t2)",cursor:"pointer"}}>
                  <input type="checkbox" checked={!!c.nsfw} onChange={e=>updateCh(c.id,{nsfw:e.target.checked})}/>NSFW
                </label>
                <label style={{display:"flex",alignItems:"center",gap:3,fontSize:10,color:"var(--t2)",cursor:"pointer"}}>
                  <input type="checkbox" checked={!!c.private} onChange={e=>updateCh(c.id,{private:e.target.checked})}/>Private
                </label>
                <input type="number" min="0" max="21600" placeholder="slow" title="Slowmode seconds"
                  value={c.slowmode||0} onChange={e=>updateCh(c.id,{slowmode:Number(e.target.value)})}
                  style={{width:44,fontSize:11,background:"var(--bg3)",border:"1px solid var(--border)",borderRadius:4,color:"var(--t0)",padding:"2px 4px"}}
                />
              </>}
              <button className="ch-item-del" onClick={()=>removeCh(c.id)}>✕</button>
            </div>
          ))}
        </div>
      ))}
      <div className="ch-add-row">
        <button className="ch-add-btn" onClick={()=>addCh("text", categories[0]||"General")}>+ Text</button>
        <button className="ch-add-btn" onClick={()=>addCh("voice", categories.find(c=>c.toLowerCase().includes("voice"))||categories[0]||"Voice")}>+ Voice</button>
        <button className="ch-add-btn" onClick={()=>addCh("forum", categories[0]||"General")}>+ Forum</button>
        {showCatInput ? (
          <input
            className="wiz-input" style={{flex:1,padding:"7px 10px",fontSize:12}}
            autoFocus placeholder="Category name…"
            value={newCat} onChange={e=>setNewCat(e.target.value)}
            onKeyDown={e=>{if(e.key==="Enter"&&newCat.trim()){addCh("text",newCat.trim());setNewCat("");setShowCatInput(false);}if(e.key==="Escape")setShowCatInput(false);}}
            onBlur={()=>{if(!newCat.trim())setShowCatInput(false);}}
          />
        ) : (
          <button className="ch-add-btn" onClick={()=>setShowCatInput(true)}>+ Category</button>
        )}
      </div>
    </div>
  );
}

function StepRoles({ form, setForm }) {
  const roles = form.roles || [];
  const updateRole = (i, patch) => { const n=[...roles]; n[i]={...n[i],...patch}; setForm({...form,roles:n}); };
  const removeRole = (i) => { if(roles[i].name==="@everyone") return; setForm({...form,roles:roles.filter((_,j)=>j!==i)}); };
  const addRole = () => {
    const colors=["#5b6cf9","#23d18b","#f472b6","#f9c846","#c084fc","#00d4ff","#f05a5a"];
    setForm({...form,roles:[...roles,{name:"New Role",color:colors[roles.length%colors.length],perms:"standard"}]});
  };
  return (
    <div>
      <div className="step-title">Set up roles</div>
      <div className="step-sub">Roles control permissions. Higher roles have more authority.</div>
      <div style={{marginBottom:14}}>
        {roles.map((r,i)=>(
          <div key={i} className="role-item">
            <span className="role-handle">⠿</span>
            <div className="role-dot" style={{background:r.color,color:r.color}}/>
            <input style={{background:"transparent",border:"none",color:"var(--t0)",fontFamily:"var(--sans)",fontSize:13,fontWeight:600,outline:"none",flex:1}}
              value={r.name} onChange={e=>updateRole(i,{name:e.target.value})} disabled={r.name==="@everyone"}/>
            <select className="role-perm-sel" value={r.perms} onChange={e=>updateRole(i,{perms:e.target.value})}>
              <option value="basic">basic</option>
              <option value="standard">standard</option>
              <option value="standard+">standard+</option>
              <option value="moderation">moderation</option>
              <option value="administrator">administrator</option>
            </select>
            {r.name!=="@everyone" && <button className="ch-item-del" onClick={()=>removeRole(i)}>✕</button>}
          </div>
        ))}
      </div>
      <button className="ch-add-btn" style={{width:"100%"}} onClick={addRole}>+ Add Role</button>
    </div>
  );
}

function StepScripts({ form, setForm }) {
  const selected = form.scripts || [];
  const toggle = id => setForm({...form, scripts:selected.includes(id)?selected.filter(x=>x!==id):[...selected,id]});
  return (
    <div>
      <div className="step-title">Install starter scripts</div>
      <div className="step-sub">Pre-install bot scripts from the library. Add more anytime from Scripts.</div>
      <div className="script-list">
        {SCRIPT_LIBRARY.map(s=>(
          <div key={s.id} className={`script-item${selected.includes(s.id)?" sel":""}`} onClick={()=>toggle(s.id)}>
            <div className="script-cb">{selected.includes(s.id)&&"✓"}</div>
            <div className="script-body">
              <div className="script-name">{s.name}</div>
              <div className="script-desc-sm">{s.desc}</div>
              <div className="script-meta-sm">
                <span className="script-cat-badge">{s.cat}</span>
                <span>↓ {s.installs.toLocaleString()} installs</span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function StepReview({ form }) {
  const tpl = TEMPLATES.find(t=>t.id===form.template);
  return (
    <div>
      <div className="step-title">Ready to launch</div>
      <div className="step-sub">Review your configuration. You can edit anything later from Server Settings.</div>
      <div className="review-section">
        <div className="review-h">Basics</div>
        <div className="review-row"><span>Server Name</span><span>{form.icon} {form.name}</span></div>
        <div className="review-row"><span>Template</span><span style={{color:tpl?.color}}>{tpl?.icon} {tpl?.name}</span></div>
      </div>
      <div className="review-section">
        <div className="review-h">Channels ({(form.channels||[]).length})</div>
        <div className="review-list">
          {(form.channels||[]).map((c,i)=>(
            <div key={i} style={{display:"flex",gap:6}}>
              <span style={{color:"var(--t2)"}}>{c.type==="voice"?"🔊":"#"}</span>
              <span>{c.name}</span>
              <span style={{color:"var(--t2)",fontFamily:"var(--mono)",fontSize:10}}>· {c.cat}</span>
            </div>
          ))}
        </div>
      </div>
      <div className="review-section">
        <div className="review-h">Roles ({(form.roles||[]).length})</div>
        <div style={{display:"flex",flexWrap:"wrap",gap:6}}>
          {(form.roles||[]).map((r,i)=><span key={i} className="pm-role" style={{color:r.color}}>{r.name}</span>)}
        </div>
      </div>
      <div className="review-section">
        <div className="review-h">Scripts ({(form.scripts||[]).length})</div>
        <div className="review-list">
          {(form.scripts||[]).length===0 && <div style={{color:"var(--t2)"}}>None — install scripts later from Scripts</div>}
          {(form.scripts||[]).map(id=>{ const s=SCRIPT_LIBRARY.find(x=>x.id===id); return s?<div key={id}>✓ {s.name}</div>:null; })}
        </div>
      </div>
    </div>
  );
}

function StepSuccess({ form, onClose, onGoToServer, logs }) {
  return (
    <div className="success-wrap">
      <div className="success-ring">{form.icon}</div>
      <div className="success-h1">{form.name} is live! 🎉</div>
      <div className="success-p">Your server has been provisioned and is ready.</div>
      <div className="success-meta">
        {[[(form.channels||[]).length,"Channels"],[(form.roles||[]).length,"Roles"],[(form.scripts||[]).length,"Scripts"]].map(([v,l])=>(
          <div key={l} className="success-meta-item">
            <div className="success-meta-val">{v}</div>
            <div className="success-meta-lbl">{l}</div>
          </div>
        ))}
      </div>
      <div className="success-actions">
        <button className="df-btn df-btn-accent df-btn-lg" onClick={onGoToServer}>Open Server →</button>
        <button className="df-btn df-btn-lg" onClick={onClose}>Close</button>
      </div>
      {logs.length>0 && (
        <div className="create-log" style={{width:480,textAlign:"left",marginTop:24}}>
          {logs.map((l,i)=><div key={i} className="log-l"><span className="log-l-ts">[{l.ts}]</span><span className={l.type==="ok"?"log-l-ok":"log-l-info"}>{l.msg}</span></div>)}
        </div>
      )}
    </div>
  );
}

function PreviewPane({ form }) {
  const channels = form.channels || [];
  const roles = form.roles || [];
  const categories = [...new Set(channels.map(c=>c.cat))];
  return (
    <div>
      <div className="preview-label">Live Preview</div>
      <div className="preview-mockup">
        <div className="pm-header">
          <div className="pm-icon">{form.icon}</div>
          <div style={{flex:1,minWidth:0}}>
            <div className="pm-name">{form.name||"Untitled Server"}</div>
          </div>
          <div className="pm-dot"/>
        </div>
        <div className="pm-body">
          {categories.length===0 && <div style={{padding:"20px 8px",textAlign:"center",fontSize:11,color:"var(--t2)"}}>No channels yet</div>}
          {categories.map(cat=>(
            <div key={cat}>
              <div className="pm-cat">{cat}</div>
              {channels.filter(c=>c.cat===cat).map((c,i)=>(
                <div key={i} className="pm-ch"><span className="pm-ch-type">{c.type==="voice"?"🔊":"#"}</span><span>{c.name}</span></div>
              ))}
            </div>
          ))}
          {roles.length>0 && <>
            <div className="pm-cat" style={{marginTop:10}}>Roles</div>
            <div className="pm-roles">{roles.map((r,i)=><span key={i} className="pm-role" style={{color:r.color}}>{r.name}</span>)}</div>
          </>}
        </div>
      </div>
    </div>
  );
}

// ── Choose screen ────────────────────────────────────────

function StepChoose({ onNew, onImport }) {
  return (
    <div style={{display:"flex",flexDirection:"column",alignItems:"center",justifyContent:"center",height:"100%",gap:20,padding:"40px 32px"}}>
      <div style={{fontSize:22,fontWeight:800,letterSpacing:"-.5px",marginBottom:4}}>How do you want to start?</div>
      <div style={{fontSize:13,color:"var(--t2)",marginBottom:20}}>Create a brand-new server or import the structure of an existing one.</div>
      <div style={{display:"flex",gap:16,width:"100%",maxWidth:560}}>
        <div onClick={onNew} style={{flex:1,background:"var(--bg2)",border:"1.5px solid var(--border)",borderRadius:"var(--rl)",padding:"28px 22px",cursor:"pointer",transition:"all .15s",textAlign:"center"}}
          onMouseEnter={e=>{ e.currentTarget.style.borderColor="var(--accent)"; e.currentTarget.style.background="var(--accent3)"; }}
          onMouseLeave={e=>{ e.currentTarget.style.borderColor="var(--border)"; e.currentTarget.style.background="var(--bg2)"; }}>
          <div style={{fontSize:36,marginBottom:12}}>✨</div>
          <div style={{fontSize:16,fontWeight:700,marginBottom:6}}>New Server</div>
          <div style={{fontSize:12,color:"var(--t2)",lineHeight:1.5}}>Build from scratch with a template. Pick channels, roles and scripts in the wizard.</div>
        </div>
        <div onClick={onImport} style={{flex:1,background:"var(--bg2)",border:"1.5px solid var(--border)",borderRadius:"var(--rl)",padding:"28px 22px",cursor:"pointer",transition:"all .15s",textAlign:"center"}}
          onMouseEnter={e=>{ e.currentTarget.style.borderColor="var(--green)"; e.currentTarget.style.background="rgba(35,209,139,.06)"; }}
          onMouseLeave={e=>{ e.currentTarget.style.borderColor="var(--border)"; e.currentTarget.style.background="var(--bg2)"; }}>
          <div style={{fontSize:36,marginBottom:12}}>📥</div>
          <div style={{fontSize:16,fontWeight:700,marginBottom:6}}>Import Existing</div>
          <div style={{fontSize:12,color:"var(--t2)",lineHeight:1.5}}>Read the structure of a Discord server you already have and pre-fill the wizard.</div>
        </div>
      </div>
    </div>
  );
}

function ImportForm({ onBack, onImported }) {
  const [guildId,   setGuildId]   = useState("");
  const [botToken,  setBotToken]  = useState("");
  const [loading,   setLoading]   = useState(false);
  const [err,       setErr]       = useState("");

  const run = async () => {
    if (!guildId.trim() || !botToken.trim()) { setErr("Both fields are required."); return; }
    setLoading(true); setErr("");
    try {
      const res  = await fetch('/api/discord/import-guild', {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({guild_id: guildId.trim(), bot_token: botToken.trim()}),
      });
      const data = await res.json();
      if (!res.ok) { setErr(data.error || `Error ${res.status}`); setLoading(false); return; }

      // Map API response → wizard form
      const channels = [];
      for (const cat of data.categories || []) {
        for (const ch of cat.textChannels  || []) channels.push({name:ch.name, type:"text",  cat:cat.name, id:`i${channels.length}`});
        for (const ch of cat.voiceChannels || []) channels.push({name:ch.name, type:"voice", cat:cat.name, id:`i${channels.length}`});
        for (const ch of cat.forumChannels || []) channels.push({name:ch.name, type:"forum", cat:cat.name, id:`i${channels.length}`});
      }
      const roles = (data.custom_roles || []).map(r => ({name:r.name, color:r.color||"#99aab5", perms:"standard", hoist:!!r.hoist}));
      if (!roles.find(r=>r.name==="@everyone")) roles.unshift({name:"@everyone",color:"#888",perms:"basic"});

      onImported({
        name:     data.server_name || "",
        icon:     "📥",
        guildId:  guildId.trim(),
        botToken: botToken.trim(),
        botName:  "",
        botClientId: "",
        template: "blank",
        channels,
        roles,
        scripts:  [],
      });
    } catch(e) {
      setErr(e.message || "Network error");
    }
    setLoading(false);
  };

  return (
    <div style={{maxWidth:480,margin:"0 auto",padding:"20px 0"}}>
      <div className="step-title">Import from Discord</div>
      <div className="step-sub">Provide your server ID and a bot token. The bot must already be in the server.</div>
      <div style={{marginBottom:18}}>
        <div className="section-label">Discord Server ID (Guild ID)</div>
        <input className="wiz-input" value={guildId} onChange={e=>setGuildId(e.target.value.trim())} placeholder="e.g. 1234567890123456789"/>
        <div className="input-hint">Right-click your server in Discord → Copy Server ID</div>
      </div>
      <div style={{marginBottom:20}}>
        <div className="section-label">Bot Token</div>
        <input className="wiz-input" type="password" value={botToken} onChange={e=>setBotToken(e.target.value.trim())} placeholder="Bot token from discord.com/developers"/>
      </div>
      {err && <div style={{fontSize:12,color:"var(--red)",fontFamily:"var(--mono)",marginBottom:12}}>{err}</div>}
      <div style={{display:"flex",gap:10}}>
        <button className="df-btn" onClick={onBack}>← Back</button>
        <button className="df-btn df-btn-success" onClick={run} disabled={loading}>
          {loading ? "Importing…" : "Import Structure →"}
        </button>
      </div>
    </div>
  );
}

// ── Main Modal ───────────────────────────────────────────

export default function CreateServerModal({ open, onClose, onCreated }) {
  const [mode, setMode] = useState(null); // null=choose, 'new', 'import'
  const [step, setStep] = useState(0);
  const [form, setForm] = useState({ name:"", icon:"🎮", guildId:"", botToken:"", botName:"", botClientId:"", template:"gaming", channels:[], roles:[], scripts:[] });
  const [error, setError] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [logs, setLogs] = useState([]);
  const [createError, setCreateError] = useState("");

  const STEPS = [
    {id:"basics",   label:"Basics"},
    {id:"discord",  label:"Discord"},
    {id:"template", label:"Template"},
    {id:"channels", label:"Channels"},
    {id:"roles",    label:"Roles"},
    {id:"scripts",  label:"Scripts"},
    {id:"review",   label:"Review"},
  ];
  const isSuccess = step === STEPS.length;

  useEffect(()=>{
    if(open){ setMode(null); setStep(0); setError(""); setCreateError(""); setIsCreating(false); setLogs([]); setForm({name:"",icon:"🎮",guildId:"",botToken:"",botName:"",template:"gaming",channels:[],roles:[],scripts:[]}); }
  },[open]);

  // Pre-load channels/roles when template changes (template is step index 2)
  useEffect(()=>{
    if(step===2 && form.template){
      const tpl=TEMPLATES.find(t=>t.id===form.template);
      if(tpl?.presets){
        const scriptIds=SCRIPT_LIBRARY.filter(s=>tpl.presets.scripts.includes(s.name)).map(s=>s.id);
        setForm(f=>({...f, channels:tpl.presets.channels.map((c,i)=>({...c,id:`c${i}`})), roles:ROLE_PRESETS[f.template]||[], scripts:scriptIds}));
      }
    }
  },[form.template]); // eslint-disable-line

  if(!open) return null;

  const validate = () => {
    setError("");
    if(step===0){
      if(!form.name.trim()){ setError("Please enter a server name"); return false; }
      if(form.name.length<2){ setError("Name must be at least 2 characters"); return false; }
    }
    if(step===1){
      if(!form.guildId.trim()){ setError("Please enter your Discord Server ID"); return false; }
      if(!/^\d{17,20}$/.test(form.guildId.trim())){ setError("Server ID should be a 17-20 digit number"); return false; }
      if(!form.botToken.trim()){ setError("Please enter your bot token"); return false; }
    }
    return true;
  };

  const next = () => {
    if(!validate()) return;
    if(step===STEPS.length-1){ startCreation(); } else { setStep(s=>s+1); }
  };

  const startCreation = async () => {
    setIsCreating(true);
    setCreateError("");
    setLogs([{ts:"00:00.00",type:"info",msg:"▸ Submitting configuration…"}]);

    try {
      // Phase 1: register the server
      const fd = buildSetupFormData(form);
      const setupRes = await fetch('/setup', {
        method: 'POST',
        credentials: 'include',
        body: fd,
      });
      const setupData = await setupRes.json();

      if (!setupRes.ok) {
        setCreateError(setupData.error || `Setup failed (${setupRes.status})`);
        setIsCreating(false);
        return;
      }

      const server_id = setupData.server_id;
      setLogs(l=>[...l,{ts:"00:00.12",type:"ok",msg:`✓ Server registered (${server_id})`}]);

      // If bot is not yet in the guild, show invite URL and stop
      if(!setupData.in_guild && setupData.invite_url){
        setLogs(l=>[...l,
          {ts:"",type:"info",msg:"⚠️ Bot is not in the server yet."},
          {ts:"",type:"info",msg:`▸ Invite it first: ${setupData.invite_url}`},
          {ts:"",type:"info",msg:"Then re-open the wizard and click Create Server again."},
        ]);
        setCreateError("Bot not in server — use the invite URL above, then try again.");
        setIsCreating(false);
        return;
      }

      // Phase 2: kick off Setup_server.py
      const runRes = await fetch('/api/setup/run', {
        method: 'POST',
        credentials: 'include',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({server_id}),
      });
      const runData = await runRes.json();
      if(!runRes.ok){
        setCreateError(runData.error || 'Failed to start setup bot');
        setIsCreating(false);
        return;
      }
      setLogs(l=>[...l,{ts:"00:00.34",type:"info",msg:"▸ Running Setup_server.py…"}]);

      // Phase 3: poll status + log
      let done = false;
      let lastLen = 0;
      while(!done){
        await new Promise(r=>setTimeout(r,1200));
        const [statusRes, logRes] = await Promise.all([
          fetch(`/api/setup/status/${server_id}`, {credentials:'include'}),
          fetch(`/api/setup/log/${server_id}`,    {credentials:'include'}),
        ]);
        if(statusRes.ok){
          const s = await statusRes.json();
          if(s.setup_completed) done = true;
          if(s.setup_error){ setCreateError(s.setup_error); setIsCreating(false); return; }
        }
        if(logRes.ok){
          const lines = await logRes.json();
          if(lines.length > lastLen){
            const newLines = lines.slice(lastLen).map(l=>({ts:"",type:l.includes('✅')||l.includes('Created')||l.includes('done')?"ok":"info",msg:l}));
            setLogs(prev=>[...prev,...newLines]);
            lastLen = lines.length;
          }
        }
      }
      setLogs(l=>[...l,{ts:"",type:"ok",msg:"✅ Server is live!"}]);
      setStep(STEPS.length);
      setIsCreating(false);
      // Pre-notify App to reload server list (nav to new server happens when user clicks "Open Server")
      if(onCreated) onCreated({...form, server_id});

    } catch(e) {
      setCreateError(e.message || 'Unexpected error');
      setIsCreating(false);
    }
  };

  // Steps 0,2,5 have no preview pane (basics, template, scripts)
  const hidePreview = step===0||step===1||step===2||step===5;
  const inWizard    = mode === 'new';

  return (
    <>
      <style>{WIZARD_CSS}</style>
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal" onClick={e=>e.stopPropagation()}>
          <div className="modal-hdr">
            <div className="modal-h-icon">{mode==='import'?"📥":"✨"}</div>
            <div>
              <div className="modal-h-title">
                {mode===null?"Add a Server":mode==='import'?"Import Server":"Create New Server"}
              </div>
              {inWizard && <div className="modal-h-sub">Step {Math.min(step+1,STEPS.length)} of {STEPS.length}</div>}
            </div>
            <button className="modal-h-close" onClick={onClose}>✕</button>
          </div>

          {inWizard && !isSuccess && (
            <div className="stepper">
              {STEPS.map((s,i)=>(
                <div key={s.id} className={`wiz-step${step===i?" current":i<step?" done":""}`} onClick={()=>i<step&&setStep(i)}>
                  <div className="step-num">{i<step?"✓":i+1}</div>
                  <div className="step-lbl">{s.label}</div>
                </div>
              ))}
            </div>
          )}

          <div className={`modal-body${hidePreview||isSuccess||isCreating||!inWizard?" no-preview":""}`}>
            <div className="body-main">
              {mode === null ? (
                <StepChoose onNew={()=>setMode('new')} onImport={()=>setMode('import')}/>
              ) : mode === 'import' ? (
                <ImportForm
                  onBack={()=>setMode(null)}
                  onImported={(prefilled)=>{
                    setForm(prefilled);
                    setMode('new');
                    setStep(0);
                  }}
                />
              ) : isCreating ? (
                <div className="success-wrap" style={{padding:"30px 20px"}}>
                  <div className="success-ring" style={{animation:"none",background:"var(--bg2)"}}><div className="wiz-spinner"/></div>
                  <div className="success-h1" style={{fontSize:20}}>Creating {form.name}…</div>
                  <div className="success-p">{createError || "Setting up your server. This will only take a moment."}</div>
                  <div className="create-log" style={{width:480,textAlign:"left"}}>
                    {logs.map((l,i)=><div key={i} className="log-l"><span className="log-l-ts">[{l.ts}]</span><span className={l.type==="ok"?"log-l-ok":"log-l-info"}>{l.msg}</span></div>)}
                  </div>
                </div>
              ) : isSuccess ? (
                <StepSuccess form={form} onClose={onClose} logs={logs} onGoToServer={()=>{if(onCreated)onCreated({...form});onClose();}}/>
              ) : (
                <>
                  {step===0 && <StepBasics    form={form} setForm={setForm} error={error}/>}
                  {step===1 && <StepDiscord   form={form} setForm={setForm} error={error}/>}
                  {step===2 && <StepTemplate  form={form} setForm={setForm}/>}
                  {step===3 && <StepChannels  form={form} setForm={setForm}/>}
                  {step===4 && <StepRoles     form={form} setForm={setForm}/>}
                  {step===5 && <StepScripts   form={form} setForm={setForm}/>}
                  {step===6 && <StepReview    form={form}/>}
                </>
              )}
            </div>
            {inWizard && !hidePreview && !isCreating && !isSuccess && (
              <div className="body-preview"><PreviewPane form={form}/></div>
            )}
          </div>

          {inWizard && !isCreating && !isSuccess && (
            <div className="modal-ftr">
              <button className="df-btn df-btn-ghost" onClick={onClose}>Cancel</button>
              <span className="ftr-progress">{Math.round(((step+1)/STEPS.length)*100)}% complete</span>
              <div style={{flex:1}}/>
              {step===0
                ? <button className="df-btn" onClick={()=>{setMode(null);setError("");}}>← Back</button>
                : <button className="df-btn" onClick={()=>{setStep(s=>s-1);setError("");}}>← Back</button>
              }
              <button className={`df-btn ${step===STEPS.length-1?"df-btn-success":"df-btn-accent"}`} onClick={next}>
                {step===STEPS.length-1?"Create Server 🚀":"Continue →"}
              </button>
            </div>
          )}
          {mode === null && (
            <div className="modal-ftr">
              <button className="df-btn df-btn-ghost" onClick={onClose}>Cancel</button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
