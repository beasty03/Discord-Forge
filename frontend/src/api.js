// Thin fetch wrapper — all routes proxied to Flask at :5000 in dev.
// Cookies (session) sent automatically; CSRF token auto-injected on mutating calls.

let _csrf = '';
export function setCSRF(token) { _csrf = token || ''; }

const MUTATING = new Set(['POST','PUT','PATCH','DELETE']);

async function apiFetch(path, opts = {}) {
  const headers = { ...(opts.headers || {}) };
  if (MUTATING.has((opts.method || 'GET').toUpperCase()) && _csrf) {
    headers['X-CSRF-Token'] = _csrf;
  }
  const res = await fetch(path, { credentials: 'include', ...opts, headers });
  if (res.status === 401 || res.redirected) {
    window.dispatchEvent(new CustomEvent('df:auth-expired'));
    return null;
  }
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export const api = {
  // Server list + live data
  servers:      () => apiFetch('/api/servers/list'),
  liveStatus:   (sid) => apiFetch('/api/dashboard/live-status' + (sid ? `?server_id=${sid}` : '')),
  events:       () => apiFetch('/api/dashboard/events'),
  bots:         () => apiFetch('/api/bots/list'),
  liveChannels: (sid) => apiFetch(`/api/server/${sid}/live-channels`),
  roles:        (sid) => apiFetch(`/api/func-test/roles/${sid}`),
  members:      (sid) => apiFetch(`/api/members/${sid}`),
  serverHealth: ()    => apiFetch('/api/dashboard/server-health'),

  // Scripts / cogs
  availableScripts: ()    => apiFetch('/api/bots/available-scripts'),
  installedCogs:    (sid) => apiFetch(`/api/bots/installed-cogs/${sid}`),
  checkScripts:     (sid) => apiFetch(`/api/bots/check-scripts/${sid}`),
  scriptVersions:   (sid) => apiFetch('/api/scripts/check-updates', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid})}),
  scriptUpdate:     (body)=> apiFetch('/api/scripts/update', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}),

  // Account
  profile:             () => apiFetch('/api/account/profile'),
  publicConfig:        () => apiFetch('/api/config'),
  revokeOtherSessions: () => apiFetch('/api/account/revoke-other-sessions', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}),
  unlinkDiscord:       () => apiFetch('/api/account/unlink-discord',        {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}),

  // Auth (no session required)
  login:          (username, password) =>
    apiFetch('/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username, password})}),
  register:       (username, email, password, confirm_password, captcha='') =>
    apiFetch('/api/auth/register', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username, email, password, confirm_password, 'h-captcha-response':captcha})}),
  forgotPassword: (username, email) =>
    apiFetch('/api/auth/forgot-password', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username, email})}),
  logout:         () => apiFetch('/api/auth/logout', {method:'POST'}),

  // Bot token validation
  validateBotToken: (token, guildId='') =>
    apiFetch('/api/validate-bot-token', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({token, guild_id: guildId})}),

  // Invites
  fetchInvite:  (token) => apiFetch(`/api/invite/${token}`),
  acceptInvite: (token) => apiFetch(`/api/invite/${token}/accept`, {method:'POST'}),

  // Mutating actions
  installCog:   (sid, cogPath) =>
    apiFetch('/api/bots/import-cogs', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid, cogs:[cogPath]})}),
  removeCog:    (sid, cogName) =>
    apiFetch('/api/bots/remove-script', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid, script_id:cogName})}),
  memberAction: (sid, type, userId, reason='') =>
    apiFetch(`/api/members/${sid}/action`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({type, user_id:userId, reason})}),

  // Bot lifecycle
  botStart:   (sid, bid) => apiFetch('/api/bots/start',   {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid, bot_id:bid})}),
  botStop:    (sid, bid) => apiFetch('/api/bots/stop',    {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid, bot_id:bid})}),
  botRestart: (sid, bid) => apiFetch('/api/bots/restart', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid, bot_id:bid})}),
  botLogs:    (sid, bid) => apiFetch(`/api/local-bot/logs/${sid}/${bid}`),

  // Channel + role CRUD
  channelOp: (sid, op, payload) =>
    apiFetch(`/api/server/${sid}/live-channels/op`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({op, ...payload})}),
  roleSave:   (sid, role) =>
    apiFetch(`/api/roles/${sid}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(role)}),
  roleDelete: (sid, name) =>
    apiFetch(`/api/roles/${sid}/${encodeURIComponent(name)}`, {method:'DELETE'}),

  // Server lifecycle
  deleteServer: (sid) =>
    apiFetch(`/api/server/${sid}/delete`, {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'}),
  renameEnv: (sid, env_name) =>
    apiFetch(`/api/environment/${sid}/rename`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({env_name})}),

  // Integrations (webhooks)
  integrations:      (sid)            => apiFetch(`/api/integrations/${sid}`),
  integrationCreate: (sid, body)      => apiFetch(`/api/integrations/${sid}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}),
  integrationDelete: (sid, wid)       => apiFetch(`/api/integrations/${sid}/${wid}`, {method:'DELETE'}),
  integrationPatch:  (sid, wid, body) => apiFetch(`/api/integrations/${sid}/${wid}`, {method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}),
  integrationTest:   (sid, wid)       => apiFetch(`/api/integrations/${sid}/${wid}/test`, {method:'POST'}),
  integrationLog:    (sid, wid)       => apiFetch(`/api/integrations/${sid}/${wid}/log`),

  // Collaborators
  collaborators:      (sid)                       => apiFetch(`/api/collaborators/${sid}`),
  collaboratorUpdate: (sid, username, permissions) =>
    apiFetch(`/api/collaborators/${sid}/update`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username, permissions})}),
  collaboratorRemove: (sid, username) =>
    apiFetch(`/api/collaborators/${sid}/remove`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({username})}),
  inviteCreate: (sid, permissions) =>
    apiFetch('/api/invites/create', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({server_id:sid, permissions})}),

  // Server settings + activity
  serverSettings: (sid, body) =>
    apiFetch(`/api/settings/${sid}`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}),
  serverIcon: (sid, icon_data) =>
    apiFetch(`/api/settings/${sid}/icon`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({icon_data})}),
  envEvents: (sid) => apiFetch(`/api/environment/${sid}/events`),

  // Assets
  assets:     (sid)       => apiFetch(`/api/server/${sid}/assets`),
  assetsLive: (sid)       => apiFetch(`/api/server/${sid}/assets/live`),
  assetsPush: (sid)       => apiFetch(`/api/server/${sid}/assets/push`, {method:'POST'}),
  assetsPost: (sid, body) => apiFetch(`/api/server/${sid}/assets`, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}),

  // Avatar source
  setAvatarSource: (source) => apiFetch('/api/account/avatar/source', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({source})}),

  // Agent
  agentToken:       ()    => apiFetch('/api/agent/token'),
  agentRegenToken:  ()    => apiFetch('/api/agent/token/regenerate', {method:'POST'}),
  agentStatus:      ()    => apiFetch('/api/agent/status'),
};
