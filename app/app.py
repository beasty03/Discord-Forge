from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, send_file, session, flash, abort
import os
import sys
import json
import copy
import subprocess
import threading
import shutil
import stat
import io
import zipfile
import smtplib
import email.mime.text
import email.mime.multipart
import time
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename as _secure_filename
from functools import wraps
from datetime import datetime, timezone
import secrets
import uuid
import re
import requests
from flask_socketio import SocketIO, emit, disconnect as _sio_disconnect

# Auto-load .env file if it exists next to app.py
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
if os.path.exists(_env_path):
    with open(_env_path, 'r', encoding='utf-8') as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _, _v = _line.partition('=')
                # Use setitem so .env always wins over empty env vars
                _key = _k.strip()
                _val = _v.strip().strip('"').strip("'")
                if _val:  # only set if non-empty
                    os.environ[_key] = _val

app = Flask(__name__, template_folder='pages')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# ── WebSocket (Flask-SocketIO + gevent) ───────────────────────────────────────
# async_mode='gevent' handles hundreds of concurrent agent connections using
# coroutines instead of threads — keeps RAM flat as user count grows.
socketio = SocketIO(app, async_mode='gevent', cors_allowed_origins='*', logger=False, engineio_logger=False)

# Connected agents registry: sid -> {username, version, bots, connected_at, last_seen}
_agents: dict = {}
_agents_lock   = threading.Lock()

# Pending server invite tokens: { token: { server_id, permissions, created_by, expires } }
# Stored in a flat JSON file so they survive Flask restarts.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT    = os.path.dirname(_APP_DIR)   # SERVER_CREATION_REPO/

INVITES_FILE = os.path.join(_ROOT, 'data', 'server_invites.json')

def load_invites():
    return load_json(INVITES_FILE, {})

def save_invites(data):
    save_json(INVITES_FILE, data)

# Force UTF-8 in all child processes (fixes emoji crash on Windows cp1252)
def _utf8_env():
    env = os.environ.copy()
    env['PYTHONIOENCODING'] = 'utf-8'
    return env

def _find_bot_by_id(config, bot_id):
    """Return the bot config entry whose 'id' matches bot_id, or None."""
    return next((b for b in config.get('discord_bots', []) if b.get('id') == bot_id), None)

# Use a stable secret key so sessions survive across restarts.
# Reads from .env (SECRET_KEY=...) or generates one and saves it to .secret_key file.
_secret_key = os.environ.get('SECRET_KEY', '')
if not _secret_key:
    _sk_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.secret_key')
    if os.path.exists(_sk_file):
        with open(_sk_file, 'r') as _f:
            _secret_key = _f.read().strip()
    else:
        _secret_key = secrets.token_hex(32)
        with open(_sk_file, 'w') as _f:
            _f.write(_secret_key)
app.secret_key = _secret_key
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE']   = os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
app.config['PERMANENT_SESSION_LIFETIME'] = 600    # 10 min — enough for OAuth flow
app.config['MAX_CONTENT_LENGTH']   = 64 * 1024 * 1024  # 64 MB — allows large asset uploads
app.config['MAX_FORM_MEMORY_SIZE'] = 64 * 1024 * 1024  # 64 MB — covers large assetsData fields
# Belt-and-suspenders for older Werkzeug versions that don't read the config key
try:
    from flask import Request as _FlaskRequest
    _FlaskRequest.max_form_memory_size = 64 * 1024 * 1024
except Exception:
    pass

@app.errorhandler(413)
def request_too_large(e):
    return jsonify({'error': 'Request too large (max 64 MB). If uploading assets, try reducing image or audio file sizes.'}), 413

# ── Rate limiting ─────────────────────────────────────────────────────────────
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
limiter = Limiter(get_remote_address, app=app, default_limits=[], storage_uri='memory://')

# Flask-Limiter 4.x has a known issue with short windows ("per minute") on some
# WSGI servers. Use a simple sliding-window counter as the authoritative limiter.
_rl_lock = threading.Lock()
_rl_counters: dict = {}  # key -> {'n': int, 'reset_at': float}

def _rl_check(key: str, max_req: int, window_s: float) -> bool:
    """Fixed-window rate check. Returns True (allow) or False (block).
    Window is anchored to the first request in each period, not the clock,
    so sequential slow requests don't cause entries to silently expire.
    """
    import time as _t
    now = _t.monotonic()
    with _rl_lock:
        state = _rl_counters.get(key)
        if state is None or now >= state['reset_at']:
            _rl_counters[key] = {'n': 1, 'reset_at': now + window_s}
            return True
        if state['n'] >= max_req:
            return False
        state['n'] += 1
        return True

# ── Session revocation ────────────────────────────────────────────────────────
# Revoked session IDs persisted across restarts in a JSON file.
_REVOKED_FILE = os.path.join(_APP_DIR, '.revoked_sessions.json')
_revoked_lock = threading.Lock()

def _load_revoked():
    try:
        with open(_REVOKED_FILE, 'r') as _f:
            return set(json.load(_f))
    except (OSError, json.JSONDecodeError):
        return set()

def _save_revoked(s):
    tmp = _REVOKED_FILE + '.tmp'
    with open(tmp, 'w') as _f:
        json.dump(list(s), _f)
    os.replace(tmp, _REVOKED_FILE)

_revoked_sessions: set = _load_revoked()

def revoke_session(sid: str):
    with _revoked_lock:
        _revoked_sessions.add(sid)
        _save_revoked(_revoked_sessions)

def is_session_revoked(sid: str) -> bool:
    with _revoked_lock:
        return sid in _revoked_sessions

# ── CSRF protection ───────────────────────────────────────────────────────────
def _csrf_token() -> str:
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_hex(32)
    return session['_csrf']

def csrf_protect(f):
    """Decorator: verify CSRF token on state-mutating POST/PUT/DELETE requests."""
    @wraps(f)
    def _inner(*args, **kwargs):
        if request.method in ('POST', 'PUT', 'DELETE', 'PATCH'):
            token = (request.form.get('_csrf_token')
                     or request.headers.get('X-CSRF-Token')
                     or (request.get_json(silent=True) or {}).get('_csrf_token'))
            if not token or token != session.get('_csrf'):
                return jsonify({'error': 'CSRF token missing or invalid'}), 403
        return f(*args, **kwargs)
    return _inner

# Make _csrf_token() available in every Jinja2 template
app.jinja_env.globals['csrf_token'] = _csrf_token

# Inject a unique session ID and check revocation on every request
@app.before_request
def _check_session_revoked():
    # Skip session creation for static assets to avoid unnecessary Set-Cookie headers
    if request.path.startswith('/app/assets/') or request.path in ('/app/favicon.svg', '/app/icons.svg'):
        return None
    if 'sid' not in session:
        session['sid'] = secrets.token_hex(16)
    if session.get('user_id') and is_session_revoked(session.get('sid', '')):
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Session revoked. Please log in again.', 'login_required': True}), 401
        # HTML/SPA routes: clear session and continue serving the page.
        # React detects 401 from API calls and shows login — no redirect needed,
        # which avoids the /login→/app/→/login loop with stale cookies + gevent.

# ── Per-server lock: prevents two concurrent setup/update runs on the same server
_setup_locks: dict = {}
_setup_locks_mutex = threading.Lock()

def _get_setup_lock(server_id: str) -> threading.Lock:
    with _setup_locks_mutex:
        if server_id not in _setup_locks:
            _setup_locks[server_id] = threading.Lock()
        return _setup_locks[server_id]

# ============================================
# CONFIG
# ============================================

DATA_DIR       = os.path.join(_ROOT, 'data')
USERS_DATA_DIR = os.path.join(DATA_DIR, 'users')
BOTS_DATA_DIR  = os.path.join(DATA_DIR, 'bots')
CONFIG_FILE    = os.path.join(DATA_DIR, 'servers_config.json')
USERS_FILE     = os.path.join(DATA_DIR, 'users.json')
UPLOADS_DIR    = os.path.join(DATA_DIR, 'uploads')
AVATARS_DIR    = os.path.join(UPLOADS_DIR, 'avatars')

SETUP_TEMPLATE_DIR = os.path.join(_ROOT, 'discord-server-setup-template')
GITHUB_BOT_SCRIPTS_USER = "beasty03"
GITHUB_BOT_SCRIPTS_REPO = "discord-server-bot-scripts"
GITHUB_BOT_SCRIPTS_BRANCH = "main"
GITHUB_FEEDBACK_REPO  = os.getenv('GITHUB_FEEDBACK_REPO', 'auto-discord-server-deployment')

ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'beastyboy03')

# ── OAuth2 Config ────────────────────────────────────────────────────────────
# Discord OAuth2 — create app at https://discord.com/developers/applications
# Set redirect URI to: http://your-host:5000/auth/discord/callback
DISCORD_CLIENT_ID          = os.environ.get('DISCORD_CLIENT_ID', '')
DISCORD_CLIENT_SECRET      = os.environ.get('DISCORD_CLIENT_SECRET', '')
DISCORD_REDIRECT_URI       = os.environ.get('DISCORD_REDIRECT_URI', 'http://localhost:5000/auth/discord/callback')
DISCORD_REDIRECT_URI_LOCAL = os.environ.get('DISCORD_REDIRECT_URI_LOCAL', 'http://127.0.0.1:5000/auth/discord/callback')

# hCaptcha — https://dashboard.hcaptcha.com
HCAPTCHA_SITE_KEY   = os.environ.get('HCAPTCHA_SITE_KEY', '')
HCAPTCHA_SECRET_KEY = os.environ.get('HCAPTCHA_SECRET_KEY', '')

def _verify_hcaptcha(token):
    if not HCAPTCHA_SECRET_KEY:
        return True  # skip if not configured
    resp = requests.post('https://hcaptcha.com/siteverify', data={
        'secret':   HCAPTCHA_SECRET_KEY,
        'response': token,
    }, timeout=5)
    return resp.json().get('success', False)

DISCORD_API = "https://discord.com/api/v10"

# Create necessary directories on startup
for d in [UPLOADS_DIR, USERS_DATA_DIR, BOTS_DATA_DIR]:
    os.makedirs(d, exist_ok=True)


def count_user_servers(username):
    return sum(1 for s in load_servers().values() if s.get('owner') == username)


def count_user_bots(username):
    users = load_users()
    servers_data = load_servers()
    total = 0
    for server_id in users.get(username, {}).get('servers', []):
        server = servers_data.get(server_id)
        if server:
            config = load_server_config(server.get('config_path'))
            if config:
                total += len(config.get('discord_bots', []))
    return total


# ============================================
# HELPERS: FILESYSTEM
# ============================================

def rmtree_force(path):
    """shutil.rmtree that handles read-only files (common in git repos on Windows)."""
    def _handle_readonly(func, p, _):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onexc=_handle_readonly)


# ============================================
# HELPERS: DATA
# ============================================

def load_json(path, default):
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return default

def save_json(path, data):
    """Atomic write: write to a temp file then rename to avoid corruption on crash."""
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    os.replace(tmp, path)

def load_users():
    return load_json(USERS_FILE, {})

def save_users(data):
    save_json(USERS_FILE, data)

def load_servers():
    return load_json(CONFIG_FILE, {})

def save_servers(data):
    save_json(CONFIG_FILE, data)

# ── Bot token encryption (Fernet / AES-128-CBC) ──────────────────────────────
# Tokens are stored with an "enc:" prefix so plaintext legacy values are still
# readable and will be transparently re-encrypted on the next save.
def _fernet():
    from cryptography.fernet import Fernet
    key = os.environ.get('TOKEN_ENCRYPTION_KEY', '')
    if not key:
        raise RuntimeError('TOKEN_ENCRYPTION_KEY not set in .env — cannot encrypt/decrypt bot tokens')
    return Fernet(key.encode())

def _encrypt_token(raw):
    if not raw or str(raw).startswith('enc:'):
        return raw
    return 'enc:' + _fernet().encrypt(raw.encode()).decode()

def _decrypt_token(stored):
    if not stored:
        return stored
    s = str(stored)
    if s.startswith('enc:'):
        return _fernet().decrypt(s[4:].encode()).decode()
    return stored  # legacy plaintext — will be encrypted on next save

def _apply_to_tokens(config, fn):
    """Apply fn to every Discord bot token field in a server config dict (mutates a copy)."""
    if not isinstance(config, dict):
        return config
    if config.get('bot_token'):
        config['bot_token'] = fn(config['bot_token'])
    for bot in config.get('discord_bots', []):
        if bot.get('token'):
            bot['token'] = fn(bot['token'])
    return config

# discord.py 2.x renamed several permission flags; the cloned setup script passes
# these names directly to discord.Permissions(**...) and will crash on old names.
_PERM_ALIASES = {
    'use_slash_commands': 'use_application_commands',
}

# Discord REST permission bit values (for live role creation/update via REST API)
_PERM_BITS = {
    'kick_members':         1 << 1,
    'ban_members':          1 << 2,
    'manage_channels':      1 << 4,
    'add_reactions':        1 << 6,
    'view_audit_log':       1 << 7,
    'read_messages':        1 << 10,   # VIEW_CHANNEL
    'send_messages':        1 << 11,
    'manage_messages':      1 << 13,
    'embed_links':          1 << 14,
    'attach_files':         1 << 15,
    'mention_everyone':     1 << 17,
    'use_external_emojis':  1 << 18,
    'connect':              1 << 20,
    'speak':                1 << 21,
    'mute_members':         1 << 22,
    'deafen_members':       1 << 23,
    'move_members':         1 << 24,
    'change_nickname':      1 << 26,
    'manage_nicknames':     1 << 27,
    'manage_roles':         1 << 28,
}

def _perms_to_int(perm_list):
    return str(sum(_PERM_BITS.get(p, 0) for p in (perm_list or [])))

def _color_to_int(color_str):
    if color_str and str(color_str).startswith('#'):
        try:
            return int(str(color_str)[1:], 16)
        except ValueError:
            pass
    return 0

def _bot_token_for_server(cfg):
    maint = [b for b in cfg.get('discord_bots', []) if b.get('maintenance') and b.get('token')]
    return (maint[0].get('token') if maint else None) or cfg.get('bot_token')

def _discord_apply_roles_diff(guild_id, bot_token, old_custom_roles, new_custom_roles):
    """Diff old vs new custom_roles lists and create/update/delete roles in Discord."""
    headers = {'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'}
    def _rname(r):
        return (r['name'] if isinstance(r, dict) else str(r)).strip()

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{guild_id}/roles", headers=headers, timeout=10)
        if not resp.ok:
            return
        discord_by_name = {r['name']: r for r in resp.json() if r['name'] != '@everyone'}
    except Exception:
        return

    old_names = {_rname(r) for r in old_custom_roles}
    new_by_name = {_rname(r): r for r in new_custom_roles}

    # Create or update
    for r in new_custom_roles:
        name = _rname(r)
        perms = r.get('permissions', []) if isinstance(r, dict) else []
        color = r.get('color', '#99aab5') if isinstance(r, dict) else '#99aab5'
        hoist = bool(r.get('hoist', False)) if isinstance(r, dict) else False
        body  = {'name': name, 'permissions': _perms_to_int(perms),
                 'color': _color_to_int(color), 'hoist': hoist}
        try:
            if name not in discord_by_name:
                requests.post(f"{DISCORD_API}/guilds/{guild_id}/roles",
                              headers=headers, json=body, timeout=8)
            else:
                role_id = discord_by_name[name]['id']
                requests.patch(f"{DISCORD_API}/guilds/{guild_id}/roles/{role_id}",
                               headers=headers, json=body, timeout=8)
        except Exception:
            pass

    # Delete roles removed from config
    for name in old_names - set(new_by_name):
        if name in discord_by_name:
            try:
                requests.delete(f"{DISCORD_API}/guilds/{guild_id}/roles/{discord_by_name[name]['id']}",
                                headers=headers, timeout=8)
            except Exception:
                pass

def _normalize_config_perms(cfg):
    """Rename any legacy discord.py permission names in custom_roles in-place."""
    for role in cfg.get('custom_roles', []):
        perms = role.get('permissions', [])
        if isinstance(perms, list):
            role['permissions'] = [_PERM_ALIASES.get(p, p) for p in perms]
        elif isinstance(perms, dict):
            role['permissions'] = {_PERM_ALIASES.get(k, k): v for k, v in perms.items()}
    return cfg
# ─────────────────────────────────────────────────────────────────────────────


def load_server_config(config_path):
    """Load a per-server config.json. Returns None if missing."""
    if config_path and os.path.exists(config_path):
        with open(config_path, 'r') as f:
            return _apply_to_tokens(json.load(f), _decrypt_token)
    # Path migration: old installs stored paths without the DiscordForge subdirectory
    if config_path and 'SERVER_CREATION_REPO/data/' in config_path:
        migrated = config_path.replace('SERVER_CREATION_REPO/data/', 'SERVER_CREATION_REPO/DiscordForge/data/')
        if os.path.exists(migrated):
            with open(migrated, 'r') as f:
                return _apply_to_tokens(json.load(f), _decrypt_token)
    return None

def save_server_config(config_path, config):
    # Auto-backup: keep one .bak snapshot before each write
    if os.path.exists(config_path):
        try:
            shutil.copy2(config_path, config_path + '.bak')
        except OSError:
            pass
    encrypted = _apply_to_tokens(copy.deepcopy(config), _encrypt_token)
    tmp = config_path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(encrypted, f, indent=4)
    os.replace(tmp, config_path)


_EVENT_ICONS = {
    'bot_online':     '🟢',
    'bot_offline':    '🔴',
    'member_sync':    '🔄',
    'command':        '⚡',
    'setup':          '🚀',
    'invite':         '🔗',
    'update':         '🔧',
    'bot_add':        '➕',
    'bot_delete':     '🗑️',
    'collab_add':     '👥',
    'collab_remove':  '👋',
    'collab_invite':  '📨',
    'edit':           '✏️',
    'rename':         '🏷️',
}

def append_event(owner, server_id, server_name, event_type, description, actor=None):
    """Append an event to the owner's event log (max 200 entries per server)."""
    path = os.path.join(USERS_DATA_DIR,owner, 'events.json')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    events = load_json(path, [])
    events.append({
        'id':          str(uuid.uuid4()),
        'type':        event_type,
        'server_id':   server_id,
        'server_name': server_name,
        'description': description,
        'actor':       actor or owner,
        'ts':          datetime.now(timezone.utc).isoformat(),
    })
    if len(events) > 200:
        events = events[-200:]
    save_json(path, events)


def get_server_or_404(server_id, user_id=None, require_permission=None):
    """
    Return (servers_data, server) or (None, None).
    user_id check passes if the user is owner OR has the required permission as collaborator.
    require_permission: e.g. 'view_server', 'edit_server', 'view_bots', 'edit_bots'
    """
    servers_data = load_servers()
    server = servers_data.get(server_id)
    if not server:
        return None, None
    if user_id:
        is_owner = server['owner'] == user_id
        if not is_owner:
            collabs = server.get('collaborators', {})
            collab_entry = collabs.get(user_id)
            if collab_entry is None:
                return None, None
            # Support both old list format and new dict format
            user_perms = collab_entry if isinstance(collab_entry, list) else collab_entry.get('permissions', [])
            if require_permission and require_permission not in user_perms:
                return None, None
    return servers_data, server

def has_server_permission(server, user_id, permission):
    """Check if user is owner or has a specific collaborator permission."""
    if server['owner'] == user_id:
        return True
    entry = server.get('collaborators', {}).get(user_id)
    if entry is None:
        return False
    perms = entry if isinstance(entry, list) else entry.get('permissions', [])
    return permission in perms


# ============================================
# HELPERS: AUTH
# ============================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        _is_api = request.path.startswith('/api/')
        if 'user_id' not in session:
            if _is_api:
                return jsonify({'error': 'Not logged in', 'login_required': True}), 401
            flash('Please log in to access this page.', 'error')
            return redirect('/app/')
        username = session['user_id']
        _u_data  = load_users().get(username, {})
        # Revoke sessions superseded by a newer login on another device/tab
        stored_nonce = _u_data.get('session_nonce')
        if stored_nonce and session.get('session_nonce') != stored_nonce:
            if _is_api:
                return jsonify({'error': 'Session superseded by a newer login', 'login_required': True}), 401
            session.clear()
            flash('You were logged in from another location. Please log in again.', 'error')
            return redirect('/app/')
        # Enforce per-user session timeout
        timeout_minutes = _u_data.get('session_timeout_minutes', 60)
        if timeout_minutes and timeout_minutes > 0:
            last_active = session.get('last_active')
            now = datetime.now(timezone.utc).timestamp()
            if last_active and (now - last_active) > timeout_minutes * 60:
                if _is_api:
                    # Don't clear session for background API calls — just deny
                    return jsonify({'error': 'Session expired', 'login_required': True}), 401
                session.clear()
                flash('Your session expired. Please log in again.', 'error')
                return redirect(url_for('login'))
        session['last_active'] = datetime.now(timezone.utc).timestamp()
        return f(*args, **kwargs)
    return decorated


def _get_session_timeout(username):
    """Return session timeout in minutes; 0 = never expire."""
    return load_users().get(username, {}).get('session_timeout_minutes', 60)


# ============================================
# HELPERS: DISCORD / INVITE
# ============================================

def build_invite_url(client_id, guild_id, permissions=8):
    """
    Build an OAuth2 bot invite URL for the given client_id pre-targeted at a guild.
    """
    return (
        f"https://discord.com/api/oauth2/authorize"
        f"?client_id={client_id}"
        f"&permissions={permissions}"
        f"&scope=bot%20applications.commands"
        f"&guild_id={guild_id}"
    )

def _find_log_channel(guild_id, bot_token):
    """Return the channel ID of a text channel named 'bot-logs' in the guild, or None."""
    headers = {'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'}
    try:
        resp = requests.get(
            f"{DISCORD_API}/guilds/{guild_id}/channels",
            headers=headers, timeout=5
        )
        print(f"[BOT-LOG] Fetching channels for guild {guild_id}: HTTP {resp.status_code}")
        if resp.status_code != 200:
            print(f"[BOT-LOG] Error: {resp.text}")
            return None
        channels = resp.json()
        print(f"[BOT-LOG] Channels: {[c.get('name') for c in channels if c.get('type') == 0]}")
        for ch in channels:
            if ch.get('type') == 0 and ch.get('name') == 'bot-logs':
                return ch['id']
        print("[BOT-LOG] No 'bot-logs' channel found.")
    except Exception as e:
        print(f"[BOT-LOG] Exception finding channel: {e}")
    return None

def _send_bot_log(guild_id, bot_name, event, extra='', bot_token=None):
    """Send a status embed to #bot-logs using the bot's own token."""
    if not bot_token:
        return
    token      = bot_token
    headers    = {'Authorization': f'Bot {token}', 'Content-Type': 'application/json'}
    channel_id = _find_log_channel(guild_id, token)
    if not channel_id:
        print(f"[BOT-LOG] Skipping — no bot-logs channel in guild {guild_id}")
        return
    colors = {'online': 0x43b581, 'offline': 0xf04747, 'restarting': 0xfaa61a}
    titles = {'online': '🟢 Bot Online', 'offline': '🔴 Bot Offline', 'restarting': '🔄 Bot Restarting'}
    now    = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    embed  = {
        'title':       titles.get(event, event),
        'color':       colors.get(event, 0x7289da),
        'description': f'**{bot_name}** — {event}',
        'fields':      [{'name': 'Time', 'value': now, 'inline': True}],
        'footer':      {'text': 'Discord Server Setup'},
    }
    if extra:
        embed['fields'].append({'name': 'Info', 'value': extra, 'inline': False})
    try:
        resp = requests.post(
            f"{DISCORD_API}/channels/{channel_id}/messages",
            headers=headers,
            json={'embeds': [embed]},
            timeout=5
        )
        print(f"[BOT-LOG] Sent '{event}' for {bot_name}: HTTP {resp.status_code}")
        if resp.status_code not in (200, 201):
            print(f"[BOT-LOG] Response: {resp.text}")
    except Exception as e:
        print(f"[BOT-LOG] Exception sending message: {e}")

def check_bot_in_guild(guild_id, bot_token=None):
    """
    Checks if a bot is in the guild via Discord REST API.
    GET /guilds/{guild_id} returns 200 if bot is a member, 403/404 if not.
    Instant — no subprocess, no asyncio, no timing issues.
    """
    if not bot_token:
        return False
    token = bot_token
    try:
        resp = requests.get(
            f"https://discord.com/api/v10/guilds/{guild_id}",
            headers={
                'Authorization': f'Bot {token}',
                'Content-Type': 'application/json'
            },
            timeout=10
        )
        if resp.status_code == 200:
            print(f"[INFO] Bot confirmed in guild {guild_id} ({resp.json().get('name')})")
            return True
        print(f"[INFO] Bot not in guild {guild_id} — Discord returned {resp.status_code}")
        return False
    except Exception as e:
        print(f"[WARNING] Could not verify bot guild membership: {e}")
        return False


# ============================================
# HELPERS: SETUP
# ============================================

def find_file_ci(directory, filename):
    """
    Case-insensitive file finder — handles repos where casing differs by OS
    (e.g. Setup_server.py vs setup_server.py).
    Returns the real full path if found, else None.
    """
    try:
        for f in os.listdir(directory):
            if f.lower() == filename.lower():
                return os.path.join(directory, f)
    except OSError:
        pass
    return None

def run_setup_server(repo_dir, config_path):
    """
    Runs Setup_server.py (case-insensitive lookup).
    Returns (True, stdout) on success, (False, error_msg) on failure.
    """
    repo_dir = os.path.abspath(repo_dir)
    setup_script = find_file_ci(repo_dir, 'setup_server.py')

    if not setup_script:
        return False, f"setup_server.py not found in: {repo_dir}"

    try:
        result = subprocess.run(
            ['python', setup_script, config_path],
            capture_output=True,
            text=True,
            cwd=repo_dir
        )
        if result.returncode != 0:
            return False, result.stderr or "Unknown error in setup_server.py"
        return True, result.stdout
    except Exception as e:
        return False, str(e)

def get_invite_url_from_script(script_path, cwd):
    """
    Runs generate_invite.py, captures its stdout, and extracts the invite URL.
    The script prints the URL on a line like:
        Bot Invite Link:\nhttps://discord.com/api/oauth2/authorize?...
    Returns the URL string, or None if it couldn't be extracted.
    """
    if not os.path.isfile(script_path):
        print(f"[WARNING] generate_invite.py not found at: {script_path}")
        return None

    try:
        result = subprocess.run(
            ['python', script_path],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=20
        )
        # Parse the URL out of stdout — it's printed right after "Bot Invite Link:"
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith('https://discord.com'):
                return line
        print(f"[WARNING] generate_invite.py ran but no URL found in output:\n{result.stdout}\n{result.stderr}")
        return None
    except subprocess.TimeoutExpired:
        print("[WARNING] generate_invite.py timed out")
        return None
    except Exception as e:
        print(f"[ERROR] Could not run generate_invite.py: {e}")
        return None


def translate_categories(categories):
    """
    Convert frontend category format to the format Setup_server.py expects.

    Frontend stores:
        {
            name, private,
            textChannels:  [{name, private, roles: ['Admin', ...]}],
            voiceChannels: [{name, private, roles: [...]}],
            forumChannels: [{name, private, roles: [...]}]
        }

    Setup_server.py reads:
        {
            name,
            private,
            text_channels:  [{name, permissions: {deny: ['@everyone'], view: ['Admin']}}],
            voice_channels: [{name, permissions: {deny: ['@everyone'], view: ['Admin']}}],
            forum_channels: [{name, permissions: {deny: ['@everyone'], view: ['Admin']}}]
        }
    """
    def make_permissions(ch, cat_private, cat_roles=None):
        ch_private = ch.get('private', False)
        roles = list(ch.get('roles') or [])
        if not roles and cat_private:
            roles = list(cat_roles or [])
        if ch_private or cat_private:
            # Admin and Moderator always retain access to every private channel
            for guaranteed in ('Admin', 'Moderator'):
                if guaranteed not in roles:
                    roles.insert(0, guaranteed)
            return {'deny': ['@everyone'], 'view': roles}
        return None

    result = []
    for cat in categories:
        cat_private = cat.get('private', False)
        cat_roles   = cat.get('roles', [])

        text_channels = []
        for ch in cat.get('textChannels', []):
            entry = {'name': ch['name']}
            if ch.get('nsfw'):     entry['nsfw']     = True
            if ch.get('slowmode'): entry['slowmode'] = int(ch['slowmode'])
            perms = make_permissions(ch, cat_private, cat_roles)
            if perms:
                entry['permissions'] = perms
            text_channels.append(entry)

        voice_channels = []
        for ch in cat.get('voiceChannels', []):
            entry = {'name': ch['name']}
            if ch.get('bitrate') and int(ch['bitrate']) != 64:
                entry['bitrate'] = int(ch['bitrate'])
            perms = make_permissions(ch, cat_private, cat_roles)
            if perms:
                entry['permissions'] = perms
            voice_channels.append(entry)

        forum_channels = []
        for ch in cat.get('forumChannels', []):
            entry = {'name': ch['name']}
            perms = make_permissions(ch, cat_private, cat_roles)
            if perms:
                entry['permissions'] = perms
            forum_channels.append(entry)

        result.append({
            'name':           cat['name'],
            'private':        cat_private,
            'text_channels':  text_channels,
            'voice_channels': voice_channels,
            'forum_channels': forum_channels,
        })
    return result


_DEFAULT_MOD_CHANNELS = [
    {'name': 'mod-chat',      'icon': '#',    'roles': ['Admin', 'Moderator'], 'private': True},
    {'name': 'bot-logs',      'icon': '#',    'roles': ['Admin', 'Moderator'], 'private': True},
    {'name': 'control-panel', 'icon': '#',    'roles': ['Admin'],              'private': True},
    {'name': 'Staff Meeting',  'icon': 'voice','roles': ['Admin', 'Moderator'], 'private': True},
]


def get_mod_channels(repo_dir=None):
    """Return moderation channel list for the preview sidebar.
    Reads from the server's moderation_template.json if available, else uses defaults."""
    if repo_dir:
        tmpl_path = os.path.join(repo_dir, 'templates', 'moderation_template.json')
        tmpl = load_json(tmpl_path, None)
        if tmpl:
            result = []
            for cat in tmpl.get('categories', []):
                for ch in cat.get('text_channels', []):
                    roles = ch.get('permissions', {}).get('view', [])
                    result.append({'name': ch['name'], 'icon': '#', 'roles': roles, 'private': True})
                for ch in cat.get('voice_channels', []):
                    roles = ch.get('permissions', {}).get('view', [])
                    result.append({'name': ch['name'], 'icon': 'voice', 'roles': roles, 'private': True})
            if result:
                return result
    return _DEFAULT_MOD_CHANNELS


def build_server_config(server_name, icon_path, guild_id, repo_dir, config_path,
                        custom_roles=None, categories=None, welcome_template=None,
                        moderator_users=None, server_assets=None, community_server=False,
                        server_webhooks=None, community_settings=None, bot_token=None,
                        banner_data=None, vanity_url=None):
    """Build the config.json dict that Setup_server.py reads."""
    def p(subpath):
        return os.path.join(repo_dir, subpath).replace('\\', '/')

    return {
        'bot_token': bot_token,
        'server': {
            'name': server_name,
            'icon': os.path.abspath(icon_path) if icon_path else None,
            'icon_type': 'file' if icon_path else 'none',
            'guild_id': guild_id
        },
        'paths': {
            'base_dir':       repo_dir.replace('\\', '/'),
            'config_dir':     repo_dir.replace('\\', '/'),
            'config_file':    config_path.replace('\\', '/'),
            'cogs_dir':       p('cogs'),
            'setup_cogs_dir': p('setup_cogs'),
            'template_dir':   p('templates'),
            'utils_dir':      p('utils'),
            'logs_dir':       p('logs'),
        },
        # These keys are what Setup_server.py actually reads
        'custom_roles':        _normalize_config_perms({'custom_roles': custom_roles or []})['custom_roles'],
        'custom_categories':   translate_categories(categories or []),
        'use_welcome_template': welcome_template == 'yes' if welcome_template else False,
        'onboarding': {
            'member_role_name':     (community_settings or {}).get('member_role_name', 'Member')   or 'Member',
            'welcome_channel_name': (community_settings or {}).get('welcome_channel_name', 'welcome') or 'welcome',
            'rules_channel_name':   (community_settings or {}).get('rules_channel_name', 'rules')    or 'rules',
        },
        'community_server':    community_server == 'yes' if isinstance(community_server, str) else bool(community_server),
        'community_settings':  community_settings or {'verification_level': 'medium', 'content_filter': 'all_members', 'default_notifications': 'only_mentions', 'system_channel': ''},
        'moderator_users':     moderator_users or [],
        'server_assets':       server_assets or {'emoji': [], 'stickers': [], 'soundboard': []},
        'server_webhooks':     server_webhooks or [],
        'banner_data':         banner_data or None,
        'vanity_url':          vanity_url  or None,
        'discord_bots': [],
        'setup_completed': False,
        'setup_date': datetime.now().isoformat(),
        'version': '2.0.0'
    }


# ============================================
# STATIC FILES
# ============================================

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOADS_DIR, filename)

@app.route('/uploads/avatars/<filename>')
def uploaded_avatar(filename):
    return send_from_directory(AVATARS_DIR, filename)

@app.route('/stress-tests/')
@app.route('/stress-tests/<path:filename>')
def stress_tests(filename='index.html'):
    return send_from_directory('stress-tests', filename)


# ============================================
# AUTH ROUTES
# ============================================

@app.route('/')
def index():
    return redirect('/app/')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        if not _rl_check(f'login:{request.remote_addr}', 30, 60.0):
            abort(429)
        username = request.form['username']
        password = request.form['password']
        users = load_users()

        if username in users and check_password_hash(users[username]['password'], password):
            nonce = secrets.token_hex(16)
            users[username]['session_nonce'] = nonce
            save_users(users)
            session['user_id'] = username
            session['email'] = users[username]['email']
            session['session_nonce'] = nonce
            flash('Login successful!', 'success')
            # Redirect to pending invite if one was saved before login
            pending = session.pop('pending_invite', None)
            if pending:
                return redirect(url_for('accept_invite', token=pending))
            next_url = request.args.get('next', '').strip()
            from urllib.parse import urlparse as _urlparse
            _p = _urlparse(next_url)
            if next_url and not _p.scheme and not _p.netloc and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('/app/')
        flash('Invalid username or password', 'error')

    return redirect('/app/')   # React LoginPage handles the UI

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if not _rl_check(f'register:{request.remote_addr}', 10, 3600.0):
            abort(429)
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        users = load_users()

        if not _verify_hcaptcha(request.form.get('h-captcha-response', '')):
            flash('Please complete the CAPTCHA.', 'error')
        elif username in users:
            flash('Username already exists', 'error')
        elif password != confirm_password:
            flash('Passwords do not match', 'error')
        elif len(password) < 6:
            flash('Password must be at least 6 characters', 'error')
        else:
            users[username] = {
                'email': email,
                'password': generate_password_hash(password),
                'servers': [],
                'created_at': datetime.now().isoformat(),
            }
            save_users(users)
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))

    return redirect('/app/?auth=register')  # React RegisterPage


# ============================================
# EMAIL — SMTP helper + password reset
# ============================================

_PENDING_RESETS_FILE = os.path.join(DATA_DIR, 'pending_resets.json')

def _smtp_configured():
    return bool(os.environ.get('SMTP_HOST') and os.environ.get('SMTP_USER'))

def _send_email(to_addr: str, subject: str, body_html: str):
    """Send an HTML email via the configured SMTP server. Raises on failure."""
    msg = email.mime.multipart.MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From']    = os.environ.get('SMTP_FROM', 'noreply@discordforge.local')
    msg['To']      = to_addr
    msg.attach(email.mime.text.MIMEText(body_html, 'html'))
    host = os.environ.get('SMTP_HOST', '')
    port = int(os.environ.get('SMTP_PORT', 587))
    user = os.environ.get('SMTP_USER', '')
    pw   = os.environ.get('SMTP_PASS', '')
    with smtplib.SMTP(host, port, timeout=10) as srv:
        srv.ehlo()
        srv.starttls()
        srv.login(user, pw)
        srv.sendmail(msg['From'], [to_addr], msg.as_string())


# ── Password reset ────────────────────────────────────────────────────────────
@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        if not _rl_check(f'forgot:{request.remote_addr}', 5, 3600.0):
            abort(429)
        username   = request.form.get('username', '').strip()
        email_addr = request.form.get('email', '').strip().lower()
        users = load_users()
        # Both username and email must match the same account
        udata   = users.get(username)
        matched = username if udata and udata.get('email', '').lower() == email_addr else None
        # Always show success to avoid user enumeration
        if matched and _smtp_configured():
            token = secrets.token_urlsafe(32)
            resets = load_json(_PENDING_RESETS_FILE, {})
            resets[token] = {'username': matched, 'created_at': datetime.now().isoformat()}
            save_json(_PENDING_RESETS_FILE, resets)
            reset_url = request.host_url.rstrip('/') + url_for('reset_password', token=token)
            try:
                _send_email(email_addr, 'DiscordForge — Reset your password',
                    f'<p>Hi <strong>{username}</strong>,</p>'
                    f'<p>We received a request to reset the password for your DiscordForge account.</p>'
                    f'<p>Click the link below to choose a new password. This link expires in <strong>1 hour</strong>.</p>'
                    f'<p><a href="{reset_url}">{reset_url}</a></p>'
                    f'<hr>'
                    f'<p style="color:#888;font-size:13px;">If you did not request a password reset, you can safely ignore this email. '
                    f'Your password will not be changed unless you click the link above.</p>')
            except Exception as _e:
                print(f'[WARN] Password reset email failed: {_e}')
        flash('Check your mailbox — if the details matched, a reset link is on its way.', 'success')
        return redirect(url_for('login'))
    return redirect('/app/?auth=forgot')  # React ForgotPasswordPage


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if request.method == 'POST':
        if not _rl_check(f'reset:{request.remote_addr}', 10, 3600.0):
            abort(429)
    resets = load_json(_PENDING_RESETS_FILE, {})
    entry  = resets.get(token)
    if not entry:
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('login'))
    # Expire after 1 hour
    try:
        age = (datetime.now() - datetime.fromisoformat(entry['created_at'])).total_seconds()
        if age > 3600:
            resets.pop(token, None)
            save_json(_PENDING_RESETS_FILE, resets)
            flash('This reset link has expired. Please request a new one.', 'error')
            return redirect(url_for('forgot_password'))
    except (ValueError, TypeError):
        pass
    if request.method == 'POST':
        pw      = request.form.get('password', '')
        confirm = request.form.get('confirm_password', '')
        if len(pw) < 6:
            flash('Password must be at least 6 characters.', 'error')
        elif pw != confirm:
            flash('Passwords do not match.', 'error')
        else:
            users = load_users()
            uname = entry['username']
            if uname in users:
                users[uname]['password'] = generate_password_hash(pw)
                save_users(users)
            resets.pop(token, None)
            save_json(_PENDING_RESETS_FILE, resets)
            flash('Password reset successfully. You can now log in.', 'success')
            return redirect(url_for('login'))
    return render_template('login.html',
        discord_configured=bool(DISCORD_CLIENT_ID),
        reset_token=token)


# ============================================
# OAUTH2 — DISCORD & GOOGLE
# ============================================

import urllib.parse

def _oauth_get_token(token_url, client_id, client_secret, code, redirect_uri):
    """Exchange authorization code for access token."""
    resp = requests.post(token_url, data={
        'client_id':     client_id,
        'client_secret': client_secret,
        'grant_type':    'authorization_code',
        'code':          code,
        'redirect_uri':  redirect_uri,
    }, headers={'Accept': 'application/json'})
    resp.raise_for_status()
    return resp.json()

def _get_or_create_oauth_user(provider, provider_id, email, display_name, avatar=''):
    """
    Find existing user by provider ID or email, or create a new one.
    Returns username string.
    """
    users = load_users()

    # Check if any user has this provider ID linked
    id_field = f'{provider}_id'
    for username, udata in users.items():
        if udata.get(id_field) == provider_id:
            if provider == 'discord' and avatar:
                users[username]['discord_avatar'] = avatar
                save_users(users)
            return username

    # Check by email
    for username, udata in users.items():
        if udata.get('email', '').lower() == email.lower():
            # Link this provider to the existing account
            users[username][id_field] = provider_id
            if provider == 'discord':
                users[username]['discord_username'] = display_name
                if avatar:
                    users[username]['discord_avatar'] = avatar
            save_users(users)
            return username

    # Create new account — derive a unique username from display_name
    base = display_name.replace(' ', '_').lower()
    username = base
    counter = 1
    while username in users:
        username = f'{base}{counter}'
        counter += 1

    users[username] = {
        'email':          email,
        'password':       '',    # no password — OAuth only
        'servers':        [],
        id_field:         provider_id,
    }
    if provider == 'discord':
        users[username]['discord_username'] = display_name
        if avatar:
            users[username]['discord_avatar'] = avatar
    save_users(users)
    return username


# ── Discord OAuth ────────────────────────────────────────────────────────────

@app.route('/auth/discord')
def auth_discord():
    """Start Discord OAuth2 flow."""
    if not DISCORD_CLIENT_ID:
        flash('Discord OAuth is not configured.', 'error')
        return redirect(url_for('login'))

    # Save state and intent (login vs link)
    state = secrets.token_urlsafe(16)
    session.permanent = True
    session['oauth_state'] = state
    session['oauth_intent'] = request.args.get('intent', 'login')  # 'login' or 'link'
    host = request.host.split(':')[0]
    redirect_uri = DISCORD_REDIRECT_URI_LOCAL if host in ('127.0.0.1', 'localhost') else DISCORD_REDIRECT_URI
    session['discord_redirect_uri'] = redirect_uri

    params = urllib.parse.urlencode({
        'client_id':     DISCORD_CLIENT_ID,
        'redirect_uri':  redirect_uri,
        'response_type': 'code',
        'scope':         'identify email',
        'state':         state,
    })
    return redirect(f'https://discord.com/oauth2/authorize?{params}')


@app.route('/auth/discord/callback')
def auth_discord_callback():
    error = request.args.get('error')
    if error:
        flash(f'Discord auth failed: {error}', 'error')
        return redirect(url_for('login'))

    state = request.args.get('state')
    if state != session.pop('oauth_state', None):
        flash('Invalid OAuth state.', 'error')
        return redirect(url_for('login'))

    code   = request.args.get('code')
    intent = session.pop('oauth_intent', 'login')

    try:
        token_data = _oauth_get_token(
            'https://discord.com/api/oauth2/token',
            DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET,
            code, session.pop('discord_redirect_uri', DISCORD_REDIRECT_URI)
        )
        access_token = token_data['access_token']

        user_resp = requests.get(f'{DISCORD_API}/users/@me',
            headers={'Authorization': f'Bearer {access_token}'})
        user_resp.raise_for_status()
        duser = user_resp.json()

        discord_id       = duser['id']
        discord_username = duser.get('global_name') or duser.get('username', '')
        discord_avatar   = duser.get('avatar') or ''
        email            = duser.get('email', f'{discord_id}@discord.local')

    except Exception as e:
        flash(f'Discord auth error: {e}', 'error')
        return redirect(url_for('login'))

    if intent == 'link' and 'user_id' in session:
        # Link Discord to existing logged-in account
        users = load_users()
        username = session['user_id']
        users[username]['discord_id']       = discord_id
        users[username]['discord_username'] = discord_username
        if discord_avatar:
            users[username]['discord_avatar'] = discord_avatar
        save_users(users)
        flash(f'✅ Discord account linked ({discord_username})!', 'success')
        return redirect(url_for('account'))

    # Login / register flow
    username = _get_or_create_oauth_user('discord', discord_id, email, discord_username, discord_avatar)
    _oauth_users = load_users()
    _oauth_nonce = secrets.token_hex(16)
    _oauth_users[username]['session_nonce'] = _oauth_nonce
    save_users(_oauth_users)
    session['user_id'] = username
    session['email']   = email
    session['session_nonce'] = _oauth_nonce

    pending = session.pop('pending_invite', None)
    if pending:
        return redirect(url_for('accept_invite', token=pending))
    return redirect(url_for('dashboard'))


@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))


# ============================================
# ACCOUNT
# ============================================

@app.route('/account', methods=['GET', 'POST'])
@login_required
@csrf_protect
def account():
    username = session['user_id']
    users = load_users()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'change_password':
            current = request.form['current_password']
            new_pw = request.form['new_password']
            confirm = request.form['confirm_password']

            # OAuth users have no password — skip current password check
            if users[username].get('password') and current and not check_password_hash(users[username]['password'], current):
                flash('Current password is incorrect', 'error')
            elif new_pw != confirm:
                flash('New passwords do not match', 'error')
            elif len(new_pw) < 6:
                flash('Password must be at least 6 characters', 'error')
            else:
                users[username]['password'] = generate_password_hash(new_pw)
                save_users(users)
                flash('Password changed successfully!', 'success')

        elif action == 'change_email':
            new_email = request.form['new_email']
            users[username]['email'] = new_email
            session['email'] = new_email
            save_users(users)
            flash('Email updated successfully!', 'success')

        elif action == 'unlink_discord':
            if users[username].get('avatar_source') == 'discord':
                users[username]['avatar_source'] = 'initials'
            users[username].pop('discord_id', None)
            users[username].pop('discord_username', None)
            users[username].pop('discord_avatar', None)
            save_users(users)
            flash('Discord account unlinked.', 'success')

        elif action == 'update_timeout':
            try:
                minutes = float(request.form.get('session_timeout_minutes', 1))
                if minutes not in (0, 0.5, 1, 3, 5):
                    minutes = 1
            except ValueError:
                minutes = 1
            users[username]['session_timeout_minutes'] = minutes
            save_users(users)
            flash('Session timeout updated.', 'success')

        elif action == 'delete_account':
            confirm_pw = request.form.get('confirm_password', '')
            stored_hash = users[username].get('password', '')
            if stored_hash and not check_password_hash(stored_hash, confirm_pw):
                flash('Incorrect password. Account not deleted.', 'error')
            else:
                # Remove owned servers and their data
                servers_data = load_servers()
                for sid in list(users[username].get('servers', [])):
                    srv = servers_data.pop(sid, None)
                    if srv:
                        install = srv.get('install_dir', '')
                        if install and os.path.isdir(install):
                            try: rmtree_force(install)
                            except OSError: pass
                        user_srv_dir = os.path.join(USERS_DATA_DIR, username, 'servers', sid)
                        if os.path.isdir(user_srv_dir):
                            try: rmtree_force(user_srv_dir)
                            except OSError: pass
                save_servers(servers_data)
                # Remove user record
                users.pop(username, None)
                save_users(users)
                # Revoke session and log out
                revoke_session(session.get('sid', ''))
                session.clear()
                flash('Your account has been permanently deleted.', 'success')
                return redirect(url_for('login'))

    return redirect('/app/')  # React UserPage


@app.route('/api/account/revoke-other-sessions', methods=['POST'])
@login_required
@csrf_protect
def revoke_other_sessions():
    try:
        old_sid = session.get('sid', '')
        if old_sid:
            revoke_session(old_sid)
        new_sid = secrets.token_hex(16)
        session['sid'] = new_sid
        with _revoked_lock:
            _revoked_sessions.discard(new_sid)
        return jsonify({'ok': True, 'message': 'All other sessions have been revoked.'})
    except Exception as e:
        app.logger.error('revoke_other_sessions error: %s', e)
        return jsonify({'ok': False, 'error': 'Failed to revoke sessions.'}), 500


@app.route('/api/account/unlink-discord', methods=['POST'])
@login_required
@csrf_protect
def unlink_discord():
    username = session['user_id']
    users = load_users()
    if username not in users:
        return jsonify({'error': 'User not found'}), 404
    users[username].pop('discord_id', None)
    users[username].pop('discord_username', None)
    users[username].pop('discord_avatar', None)
    if users[username].get('avatar_source') == 'discord':
        users[username]['avatar_source'] = 'initials'
    save_users(users)
    return jsonify({'ok': True, 'message': 'Discord account unlinked.'})


@app.route('/api/account/avatar', methods=['POST'])
@login_required
def upload_avatar():
    username = session['user_id']
    if 'avatar' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['avatar']
    if not f.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
    if ext not in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        return jsonify({'error': 'Unsupported type. Use JPG, PNG, GIF or WEBP.'}), 400

    data = f.read()
    if len(data) > 2 * 1024 * 1024:
        return jsonify({'error': 'File too large (max 2MB)'}), 400

    os.makedirs(AVATARS_DIR, exist_ok=True)
    filename = f'{username}_avatar.{ext}'
    # Remove any previous avatar file for this user
    for old_ext in ('jpg', 'jpeg', 'png', 'gif', 'webp'):
        old = os.path.join(AVATARS_DIR, f'{username}_avatar.{old_ext}')
        if os.path.exists(old) and old != os.path.join(AVATARS_DIR, filename):
            try:
                os.remove(old)
            except OSError:
                pass

    with open(os.path.join(AVATARS_DIR, filename), 'wb') as out:
        out.write(data)

    users = load_users()
    users[username]['custom_avatar_path'] = filename
    users[username]['avatar_source'] = 'custom'
    save_users(users)
    return jsonify({'ok': True, 'url': f'/uploads/avatars/{filename}'})


@app.route('/api/account/avatar/source', methods=['POST'])
@login_required
def set_avatar_source():
    username = session['user_id']
    data = request.get_json(silent=True) or {}
    source = data.get('source', '')
    if source not in ('initials', 'discord', 'custom'):
        return jsonify({'error': 'Invalid source'}), 400

    users = load_users()
    udata = users[username]

    if source == 'discord':
        if not (udata.get('discord_id') and udata.get('discord_avatar')):
            return jsonify({'error': 'Discord avatar not available'}), 400
    if source == 'custom' and not udata.get('custom_avatar_path'):
        return jsonify({'error': 'No custom avatar uploaded yet'}), 400

    users[username]['avatar_source'] = source
    save_users(users)

    discord_id     = udata.get('discord_id', '')
    discord_avatar = udata.get('discord_avatar', '')
    if source == 'discord' and discord_id and discord_avatar:
        url = f'https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png?size=64'
    elif source == 'custom':
        url = f'/uploads/avatars/{udata["custom_avatar_path"]}'
    else:
        url = ''
    return jsonify({'ok': True, 'url': url})


@app.route('/api/account/profile', methods=['GET'])
@login_required
def account_profile():
    username = session['user_id']
    users    = load_users()
    user     = users.get(username, {})
    discord_id     = user.get('discord_id', '')
    discord_avatar = user.get('discord_avatar', '')
    avatar_source  = user.get('avatar_source', 'initials')
    if avatar_source == 'discord' and discord_id and discord_avatar:
        avatar_url = f'https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png?size=128'
    elif avatar_source == 'custom' and user.get('custom_avatar_path'):
        avatar_url = f'/uploads/avatars/{user["custom_avatar_path"]}'
    else:
        avatar_url = ''
    discord_avatar_url = (
        f'https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png?size=128'
        if (discord_id and discord_avatar) else ''
    )
    return jsonify({
        'username':                 username,
        'email':                    user.get('email', ''),
        'avatar_source':            avatar_source,
        'avatar_url':               avatar_url,
        'discord_avatar_url':       discord_avatar_url,
        'discord_linked':           bool(user.get('discord_id')),
        'discord_username':         user.get('discord_username', ''),
        'server_count':             len(user.get('servers', [])),
        'session_timeout_minutes':  user.get('session_timeout_minutes', 1),
        'csrf_token':               _csrf_token(),
    })


# ── Public config (hCaptcha key etc.) ────────────────────────────────────────

@app.route('/api/config', methods=['GET'])
def public_config():
    return jsonify({
        'hcaptcha_site_key':  HCAPTCHA_SITE_KEY or '',
        'discord_configured': bool(DISCORD_CLIENT_ID),
    })


# ── JSON auth endpoints (used by React SPA) ──────────────────────────────────

@app.route('/api/auth/login', methods=['POST'])
def api_login():
    if not _rl_check(f'login:{request.remote_addr}', 30, 60.0):
        return jsonify({'error': 'Too many attempts. Wait a minute.'}), 429
    data     = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', ''))
    users    = load_users()
    user     = users.get(username)
    if not user or not check_password_hash(user.get('password', ''), password):
        return jsonify({'error': 'Invalid username or password'}), 401
    nonce = secrets.token_hex(16)
    users[username]['session_nonce'] = nonce
    save_users(users)
    session['user_id']       = username
    session['email']         = user.get('email', '')
    session['session_nonce'] = nonce
    return jsonify({'ok': True})


@app.route('/api/auth/register', methods=['POST'])
def api_register():
    if not _rl_check(f'register:{request.remote_addr}', 10, 3600.0):
        return jsonify({'error': 'Too many attempts. Try again later.'}), 429
    data             = request.get_json(silent=True) or {}
    username         = str(data.get('username', '')).strip()
    email            = str(data.get('email', '')).strip().lower()
    password         = str(data.get('password', ''))
    confirm_password = str(data.get('confirm_password', ''))
    captcha          = str(data.get('h-captcha-response', ''))
    if HCAPTCHA_SITE_KEY and not _verify_hcaptcha(captcha):
        return jsonify({'error': 'Please complete the CAPTCHA.'}), 400
    if not username or len(username) < 2:
        return jsonify({'error': 'Username must be at least 2 characters.'}), 400
    if password != confirm_password:
        return jsonify({'error': 'Passwords do not match.'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Password must be at least 6 characters.'}), 400
    users = load_users()
    if username in users:
        return jsonify({'error': 'Username already taken.'}), 409
    users[username] = {
        'email': email, 'password': generate_password_hash(password),
        'servers': [], 'created_at': datetime.now().isoformat(),
    }
    save_users(users)
    return jsonify({'ok': True})


@app.route('/api/auth/forgot-password', methods=['POST'])
def api_forgot_password():
    if not _rl_check(f'forgot:{request.remote_addr}', 5, 3600.0):
        return jsonify({'error': 'Too many attempts. Try again later.'}), 429
    data       = request.get_json(silent=True) or {}
    username   = str(data.get('username', '')).strip()
    email_addr = str(data.get('email', '')).strip().lower()
    users      = load_users()
    udata      = users.get(username)
    if udata and udata.get('email', '').lower() == email_addr and _smtp_configured():
        token  = secrets.token_urlsafe(32)
        resets = load_json(_PENDING_RESETS_FILE, {})
        resets[token] = {'username': username, 'created_at': datetime.now().isoformat()}
        save_json(_PENDING_RESETS_FILE, resets)
        reset_url = request.host_url.rstrip('/') + url_for('reset_password', token=token)
        try: _send_email(email_addr, 'DiscordForge — Reset your password',
            f'<p>Hi <strong>{username}</strong>,</p>'
            f'<p><a href="{reset_url}">Click here to reset your password</a> (valid 1 hour).</p>')
        except Exception: pass
    # Always succeed to avoid user enumeration
    return jsonify({'ok': True})


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    revoke_session(session.get('sid', ''))
    session.clear()
    return jsonify({'ok': True})


# ── JSON invite endpoints ─────────────────────────────────────────────────────

@app.route('/api/invite/<token>', methods=['GET'])
def api_invite_get(token):
    invites = load_invites()
    invite  = invites.get(token)
    if not invite or invite.get('used'):
        return jsonify({'error': 'Invalid or already used invite.'}), 404
    try:
        created = datetime.fromisoformat(invite.get('created_at', ''))
        if (datetime.now() - created).days >= 7:
            return jsonify({'error': 'Invite expired (valid 7 days).'}), 410
    except (ValueError, TypeError):
        pass
    return jsonify({
        'server_name': invite.get('server_name', ''),
        'permissions': invite.get('permissions', []),
        'created_by':  invite.get('created_by', ''),
    })


@app.route('/api/invite/<token>/accept', methods=['POST'])
@login_required
def api_invite_accept(token):
    username    = session['user_id']
    invites     = load_invites()
    invite      = invites.get(token)
    if not invite or invite.get('used'):
        return jsonify({'error': 'Invalid or already used invite.'}), 404
    server_id   = invite['server_id']
    servers_data, server = get_server_or_404(server_id)
    if not server:
        return jsonify({'error': 'Server no longer exists.'}), 404
    if server['owner'] == username:
        return jsonify({'error': 'You are already the server owner.'}), 400
    users = load_users()
    collabs = server.setdefault('collaborators', {})
    existing = set(collabs.get(username, {}).get('permissions', []) if isinstance(collabs.get(username), dict) else collabs.get(username, []))
    existing.update(invite['permissions'])
    collabs[username] = {
        'permissions':      list(existing),
        'discord_id':       users.get(username, {}).get('discord_id', ''),
        'discord_username': users.get(username, {}).get('discord_username', ''),
        'added_at':         datetime.now().isoformat(),
    }
    servers_data[server_id] = server
    save_servers(servers_data)
    invites[token]['used']    = True
    invites[token]['used_by'] = username
    invites[token]['used_at'] = datetime.now().isoformat()
    save_invites(invites)
    append_event(server['owner'], server_id, invite['server_name'],
                 'collab_invite', f'"{username}" accepted invite', actor=username)
    return jsonify({'ok': True, 'server_name': invite['server_name']})


# ── Delete server JSON API ────────────────────────────────────────────────────

@app.route('/api/server/<server_id>/delete', methods=['POST'])
@login_required
@csrf_protect
def api_delete_server(server_id):
    username     = session['user_id']
    servers_data = load_servers()
    users        = load_users()
    if server_id not in servers_data:
        return jsonify({'error': 'Server not found'}), 404
    server = servers_data[server_id]
    if server['owner'] != username:
        return jsonify({'error': 'Forbidden'}), 403
    install_dir = server.get('install_dir')
    if install_dir and os.path.exists(install_dir):
        try: rmtree_force(install_dir)
        except Exception: pass
    del servers_data[server_id]
    save_servers(servers_data)
    if server_id in users[username].get('servers', []):
        users[username]['servers'].remove(server_id)
        save_users(users)
    return jsonify({'ok': True})


# ── Redirect old invite URL to SPA ───────────────────────────────────────────

@app.route('/app/invite/<token>')
def spa_invite(token):
    """Serve the SPA for invite URLs so React can handle them."""
    return send_from_directory(os.path.join(app.root_path, 'static', 'dist'), 'index.html')


# ============================================
# TEMPLATE CONTEXT — plan/ads info
# ============================================

@app.context_processor
def inject_user_info():
    if 'user_id' in session:
        username = session['user_id']
        udata    = load_users().get(username, {})
        discord_id     = udata.get('discord_id', '')
        discord_avatar = udata.get('discord_avatar', '')

        stored_source = udata.get('avatar_source', '')
        if not stored_source:
            effective_source = 'discord' if (discord_id and discord_avatar) else 'initials'
        else:
            effective_source = stored_source

        if effective_source == 'discord' and discord_id and discord_avatar:
            avatar_url = f'https://cdn.discordapp.com/avatars/{discord_id}/{discord_avatar}.png?size=64'
        elif effective_source == 'custom':
            custom_path = udata.get('custom_avatar_path', '')
            avatar_url = f'/uploads/avatars/{custom_path}' if custom_path else ''
        else:
            avatar_url = ''

        return {
            'current_username': username,
            'user_avatar_url':  avatar_url,
            'avatar_source':   effective_source,
            'is_admin':        username == ADMIN_USERNAME,
        }
    return {'current_username': '', 'user_avatar_url': '', 'avatar_source': 'initials', 'is_admin': False}


# ============================================
# DASHBOARD
# ============================================

@app.route('/dashboard')
@login_required
def dashboard():
    return redirect('/app/')  # React SPA dashboard


# ============================================
# SERVER SETUP  —  NEW TWO-PHASE FLOW
#
#   Phase 1 (POST /setup):
#     - Validate form, clone repo, write config.json, save server record
#     - Returns JSON with { server_id, invite_url }
#     - Frontend shows modal: "Add the bot → click Continue"
#
#   Phase 2 (POST /api/setup/run):
#     - Called after user confirms bot is in the server
#     - Optionally verifies bot membership via Discord API
#     - Runs setup_server.py + init_database.py
# ============================================

@app.route('/load_config', methods=['POST'])
@login_required
def load_config():
    data     = request.get_json()
    guild_id = data.get('guild_id')
    username = session['user_id']
    users    = load_users()
    owned    = set(users.get(username, {}).get('servers', []))
    servers_data = load_servers()

    for server_id, server in servers_data.items():
        if server['guild_id'] == guild_id and server_id in owned:
            return jsonify(server)

    return jsonify({"error": "Server not found"}), 404


@app.route('/api/server/<server_id>/export')
@login_required
def export_server_config(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    export_data = {
        '_template': True,
        'server_name':      server.get('server_name', ''),
        'custom_roles':     server.get('custom_roles', []),
        'categories':       server.get('categories', []),
        'welcome_template': server.get('welcome_template', 'no'),
        'community_server': server.get('community_server', False),
        'moderator_users':  server.get('moderator_users', []),
    }
    safe_name = server.get('server_name', 'server').replace(' ', '_')
    from flask import Response
    return Response(
        json.dumps(export_data, indent=2),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{safe_name}_template.json"'}
    )


@app.route('/setup/import', methods=['POST'])
@login_required
def import_server_config():
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify({'error': 'Invalid format'}), 400
        session['prefill_data'] = {
            'server_name':     str(data.get('server_name', '')),
            'custom_roles':    data.get('custom_roles', []),
            'categories':      data.get('categories', []),
            'welcome_template': data.get('welcome_template', 'no'),
        }
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/discord/import-guild', methods=['POST'])
@login_required
def import_discord_guild():
    """Read the structure of an existing Discord server via the API and prefill the setup form."""
    data = request.get_json(force=True) or {}
    guild_id  = str(data.get('guild_id',  '')).strip()
    bot_token = str(data.get('bot_token', '')).strip()

    if not guild_id or not bot_token:
        return jsonify({'error': 'guild_id and bot_token are required'}), 400

    headers = {'Authorization': f'Bot {bot_token}'}
    base    = 'https://discord.com/api/v10'

    # Fetch guild info (name + roles)
    try:
        guild_resp = requests.get(f'{base}/guilds/{guild_id}', headers=headers, timeout=10)
    except requests.RequestException as e:
        return jsonify({'error': f'Network error: {e}'}), 502

    if guild_resp.status_code == 401:
        return jsonify({'error': 'Invalid bot token'}), 401
    if guild_resp.status_code == 403:
        return jsonify({'error': 'Bot is not a member of this server'}), 403
    if guild_resp.status_code == 404:
        return jsonify({'error': 'Server not found'}), 404
    if not guild_resp.ok:
        return jsonify({'error': f'Discord API error {guild_resp.status_code}'}), 502

    guild = guild_resp.json()

    # Fetch channels
    try:
        ch_resp = requests.get(f'{base}/guilds/{guild_id}/channels', headers=headers, timeout=10)
    except requests.RequestException as e:
        return jsonify({'error': f'Network error fetching channels: {e}'}), 502

    if not ch_resp.ok:
        return jsonify({'error': f'Could not fetch channels: {ch_resp.status_code}'}), 502

    channels = ch_resp.json()

    # --- Map roles (skip @everyone and bot-managed roles) ---
    _RESERVED = {'admin', 'moderator', 'moderation'}
    custom_roles = []
    for r in guild.get('roles', []):
        if r['name'] == '@everyone':
            continue
        if r.get('managed'):   # integration/bot roles
            continue
        name = r['name'].strip()
        if not name or name.lower() in _RESERVED:
            continue
        # Discord stores color as integer; convert to hex
        color_int = r.get('color', 0)
        color_hex = f'#{color_int:06x}' if color_int else '#99aab5'
        custom_roles.append({
            'name':        name,
            'permissions': [],
            'color':       color_hex,
            'hoist':       bool(r.get('hoist', False)),
        })

    # --- Map channels into categories ---
    # Channel type constants
    TYPE_TEXT     = 0
    TYPE_VOICE    = 2
    TYPE_CATEGORY = 4
    TYPE_FORUM    = 15

    # Build category lookup {discord_id: category_dict}
    cat_map = {}
    for ch in channels:
        if ch['type'] == TYPE_CATEGORY:
            cat_map[ch['id']] = {
                'name':          ch['name'],
                'private':       False,
                'roles':         [],
                'textChannels':  [],
                'voiceChannels': [],
                'forumChannels': [],
                '_position':     ch.get('position', 0),
            }

    # Uncategorised bucket for channels without a parent
    uncategorised = {
        'name':          'General',
        'private':       False,
        'roles':         [],
        'textChannels':  [],
        'voiceChannels': [],
        'forumChannels': [],
        '_position':     -1,
    }

    for ch in sorted(channels, key=lambda c: c.get('position', 0)):
        ch_type   = ch['type']
        parent_id = ch.get('parent_id')
        name      = ch['name']

        if ch_type == TYPE_CATEGORY:
            continue  # already added above

        bucket = cat_map.get(parent_id, uncategorised)

        if ch_type == TYPE_TEXT:
            bucket['textChannels'].append({'name': name, 'private': False, 'roles': []})
        elif ch_type == TYPE_VOICE:
            bucket['voiceChannels'].append({'name': name, 'private': False, 'roles': []})
        elif ch_type == TYPE_FORUM:
            bucket['forumChannels'].append({'name': name, 'private': False, 'roles': []})

    # Sort categories by position and collect; add uncategorised only if it has channels
    categories = sorted(cat_map.values(), key=lambda c: c['_position'])
    for c in categories:
        del c['_position']

    if uncategorised['textChannels'] or uncategorised['voiceChannels'] or uncategorised['forumChannels']:
        categories.insert(0, {k: v for k, v in uncategorised.items() if k != '_position'})

    session['prefill_data'] = {
        'server_name':      guild.get('name', ''),
        'guild_id':         guild_id,
        'custom_roles':     custom_roles,
        'categories':       categories,
        'welcome_template': 'no',
    }
    return jsonify({'ok': True, 'server_name': guild.get('name', '')})


@app.route('/api/discord/register-existing', methods=['POST'])
@login_required
def register_existing_server():
    """Register an already-configured Discord server into DiscordForge without running setup."""
    data          = request.get_json(force=True) or {}
    guild_id      = str(data.get('guild_id',      '')).strip()
    bot_token     = str(data.get('bot_token',     '')).strip()
    server_name   = str(data.get('server_name',   '')).strip()
    bot_name      = str(data.get('bot_name',      '')).strip() or 'My Bot'
    bot_client_id = str(data.get('bot_client_id', '')).strip()
    custom_roles  = data.get('roles',      [])
    categories    = data.get('categories', [])

    if not guild_id or not bot_token:
        return jsonify({'error': 'guild_id and bot_token are required'}), 400
    if not server_name:
        return jsonify({'error': 'server_name is required'}), 400

    username     = session['user_id']
    servers_data = load_servers()
    users_data   = load_users()

    existing_id = next((sid for sid, s in servers_data.items() if s['guild_id'] == guild_id), None)
    if existing_id:
        if servers_data[existing_id]['owner'] != username:
            return jsonify({'error': 'This server already exists and is owned by another user.'}), 409
        return jsonify({'error': 'This server is already configured.', 'server_id': existing_id}), 409

    server_id   = f"{username}_{guild_id}"
    install_dir = os.path.join(USERS_DATA_DIR, username, 'installations', f'server_{guild_id}')
    os.makedirs(install_dir, exist_ok=True)

    import shutil as _shutil
    repo_dir = os.path.join(install_dir, 'discord-server-setup')
    if not os.path.exists(repo_dir):
        if not os.path.isdir(SETUP_TEMPLATE_DIR):
            return jsonify({'error': 'Setup template directory not found.'}), 500
        _shutil.copytree(SETUP_TEMPLATE_DIR, repo_dir)

    config_path = os.path.join(repo_dir, 'config.json')
    config = build_server_config(
        server_name, None, guild_id, repo_dir, config_path,
        custom_roles=custom_roles, categories=categories,
        bot_token=bot_token,
    )
    config['setup_completed'] = True
    config['discord_bots'] = [{
        'id':          str(uuid.uuid4()),
        'name':        bot_name,
        'token':       bot_token,
        'client_id':   bot_client_id,
        'maintenance': True,
    }]
    try:
        save_server_config(config_path, config)
    except RuntimeError as e:
        return jsonify({'error': str(e)}), 500

    server_data = {
        'server_id':        server_id,
        'server_name':      server_name,
        'guild_id':         guild_id,
        'owner':            username,
        'icon_path':        None,
        'custom_roles':     custom_roles,
        'categories':       categories,
        'welcome_template': 'no',
        'community_server': 'no',
        'moderator_users':  [],
        'server_assets':    {'emoji': [], 'stickers': [], 'soundboard': []},
        'install_dir':      install_dir,
        'config_path':      config_path,
        'setup_completed':  True,
        'created_at':       datetime.now().isoformat(),
    }
    servers_data[server_id] = server_data
    save_servers(servers_data)

    if server_id not in users_data[username]['servers']:
        users_data[username]['servers'].append(server_id)
        save_users(users_data)

    append_event(username, server_id, server_name, 'server_added',
                 'Existing Discord server registered in DiscordForge.')

    return jsonify({'success': True, 'server_id': server_id, 'server_name': server_name})


@app.route('/setup', methods=['GET', 'POST'])
@login_required
def setup():
    if request.method == 'GET':
        return redirect('/app/')  # React CreateServerModal handles setup

    username = session['user_id']
    server_name = request.form['server_name']
    guild_id = request.form['guild_id']
    server_id = request.form.get('server_id')  # present only in edit mode

    servers_data = load_servers()
    users = load_users()

    # --- Ownership / duplicate checks ---
    existing_id = next(
        (sid for sid, s in servers_data.items() if s['guild_id'] == guild_id),
        None
    )

    if not server_id:
        if existing_id:
            if servers_data[existing_id]['owner'] != username:
                return jsonify({'error': 'This server already exists and is owned by another user.'}), 409
            return jsonify({
                'error': 'This server is already configured.',
                'edit_url': url_for('edit_server', server_id=existing_id)
            }), 409
        server_id = f"{username}_{guild_id}"
    else:
        if server_id not in servers_data:
            return jsonify({'error': 'Server not found.'}), 404
        if servers_data[server_id]['owner'] != username:
            return jsonify({'error': 'You are not the owner of this server.'}), 403

    # --- Icon upload ---
    icon_path = servers_data.get(server_id, {}).get('icon_path')
    icon_file = request.files.get('icon_file')

    if icon_file and icon_file.filename:
        if icon_path and os.path.exists(icon_path):
            try:
                os.remove(icon_path)
            except OSError:
                pass
        safe_name = _secure_filename(icon_file.filename)
        if not safe_name:
            return jsonify({'error': 'Invalid icon filename'}), 400
        filename  = f"{server_id}_{safe_name}"
        icon_path = os.path.join(UPLOADS_DIR, filename)
        icon_file.save(icon_path)

    # --- Form data ---
    _RESERVED_ROLES = {'admin', 'moderator', 'moderation'}
    custom_roles = []
    for r in json.loads(request.form.get('customRolesData', '[]')):
        if isinstance(r, dict):
            name = r.get('name', '').strip()
            if name and name.lower() not in _RESERVED_ROLES:
                custom_roles.append({
                    'name':        name,
                    'permissions': r.get('permissions', []),
                    'color':       r.get('color', '#99aab5'),
                    'hoist':       r.get('hoist', False),
                })
        elif isinstance(r, str):
            name = r.strip()
            if name and name.lower() not in _RESERVED_ROLES:
                custom_roles.append({'name': name, 'permissions': [], 'color': '#99aab5', 'hoist': False})
    categories = json.loads(request.form.get('categoriesData', '[]'))

    # Merge uncategorized channels into a leading "General" category if any exist.
    # Discord allows channels without a parent, but Setup_server.py models everything
    # inside categories. We create/prepend a General category so they get created.
    try:
        _uncat = json.loads(request.form.get('uncategorizedChannelsData', '{}') or '{}')
    except (ValueError, TypeError):
        _uncat = {}
    _uncat_text  = [ch for ch in _uncat.get('text',  []) if ch.get('name', '').strip()]
    _uncat_voice = [ch for ch in _uncat.get('voice', []) if ch.get('name', '').strip()]
    if _uncat_text or _uncat_voice:
        categories.insert(0, {
            'name': 'General',
            'private': False,
            'roles': [],
            'textChannels':  _uncat_text,
            'voiceChannels': _uncat_voice,
            'forumChannels': [],
        })

    welcome_template   = request.form.get('welcome_template', 'no')
    community_server   = request.form.get('community_server', 'no')
    moderator_users = json.loads(request.form.get('moderatorUsersData', '[]'))
    _assets_submitted = 'assetsData' in request.form
    _assets_raw = request.form.get('assetsData', '') or ''
    try:
        server_assets = json.loads(_assets_raw) if _assets_raw else {}
    except (ValueError, TypeError):
        server_assets = {}
    server_assets.setdefault('emoji', [])
    server_assets.setdefault('stickers', [])
    server_assets.setdefault('soundboard', [])

    _webhooks_submitted = 'webhooksData' in request.form
    try:
        server_webhooks = json.loads(request.form.get('webhooksData', '[]') or '[]')
    except (ValueError, TypeError):
        server_webhooks = []

    try:
        community_settings = json.loads(request.form.get('communitySettingsData', '{}') or '{}')
    except (ValueError, TypeError):
        community_settings = {}
    community_settings.setdefault('verification_level', 'medium')
    community_settings.setdefault('content_filter', 'all_members')
    community_settings.setdefault('default_notifications', 'only_mentions')
    community_settings.setdefault('system_channel', '')

    maint_bot_token  = str(request.form.get('maintBotToken', '') or '').strip()
    maint_bot_name   = str(request.form.get('maintBotName',  '') or '').strip() or 'My Bot'
    maint_bot_cid    = str(request.form.get('maintBotClientId', '') or '').strip()
    banner_data      = str(request.form.get('bannerData', '') or '').strip() or None
    vanity_url       = str(request.form.get('vanityUrl',  '') or '').strip().lower() or None
    # Bot token is always required — no setup-bot fallback
    effective_token = maint_bot_token or None
    if not effective_token and not is_update:
        return jsonify({'error': 'A bot token is required to create a server.'}), 400

    is_update = server_id in servers_data

    # ---- UPDATE path — diff-based, runs update_server.py ----
    if is_update:
        existing = servers_data[server_id]
        install_dir_upd = os.path.abspath(existing['install_dir'])
        repo_dir_upd    = os.path.join(install_dir_upd, 'discord-server-setup')
        config_path_upd = os.path.join(repo_dir_upd, 'config.json')

        # Write updated config.json so update_server.py picks up the new state
        updated_config = build_server_config(
            server_name, icon_path, guild_id, repo_dir_upd, config_path_upd,
            custom_roles=custom_roles, categories=categories,
            welcome_template=welcome_template, community_server=community_server,
            moderator_users=moderator_users, server_assets=server_assets,
            server_webhooks=server_webhooks, community_settings=community_settings,
            bot_token=effective_token, banner_data=banner_data, vanity_url=vanity_url
        )
        # Preserve existing discord_bots and setup_date; merge new bot if provided
        existing_cfg = load_server_config(config_path_upd) or {}
        existing_bots = existing_cfg.get('discord_bots', [])
        if effective_token and maint_bot_name:
            if not any(b.get('token') == effective_token for b in existing_bots):
                existing_bots.append({'id': str(uuid.uuid4()), 'name': maint_bot_name, 'token': effective_token, 'client_id': maint_bot_cid, 'maintenance': True})
        updated_config['discord_bots'] = existing_bots
        # If user didn't supply a new bot token this edit, preserve whatever was already stored
        if effective_token is None:
            prev_token = existing_cfg.get('bot_token')
            if prev_token:
                updated_config['bot_token'] = prev_token
        updated_config['setup_date']      = existing_cfg.get('setup_date', updated_config['setup_date'])
        updated_config['setup_completed'] = existing_cfg.get('setup_completed', False)
        # If banner/vanity not submitted this edit, preserve whatever was stored before
        if not banner_data:
            updated_config['banner_data'] = existing_cfg.get('banner_data')
        if not vanity_url:
            updated_config['vanity_url']  = existing_cfg.get('vanity_url')
        # If assets/webhooks not submitted (removed from wizard), preserve existing values
        if not _assets_submitted:
            updated_config['server_assets']   = existing_cfg.get('server_assets',   server_assets)
            server_assets = updated_config['server_assets']
        if not _webhooks_submitted:
            updated_config['server_webhooks'] = existing_cfg.get('server_webhooks', server_webhooks)
            server_webhooks = updated_config['server_webhooks']
        save_server_config(config_path_upd, updated_config)

        # Save updated metadata to servers_config.json
        servers_data[server_id] = {
            **existing,
            "server_name":       server_name,
            "icon_path":         icon_path,
            "custom_roles":      custom_roles,
            "categories":        categories,
            "welcome_template":  welcome_template,
            "community_server":  community_server,
            "moderator_users":     moderator_users,
            "server_assets":       server_assets,
            "server_webhooks":     server_webhooks,
            "community_settings":  community_settings,
            "config_path":         config_path_upd,
            "update_running":    False,
            "update_error":      None,
        }
        save_servers(servers_data)

        # Return JSON — frontend will show update modal and poll /api/setup/status
        return jsonify({
            'success':   True,
            'is_update': True,
            'server_id': server_id,
            'message':   'Config saved. Call /api/update/run to apply changes to Discord.'
        })

    # ---- NEW SERVER path ----
    # 1. Clone repo
    install_dir = os.path.join(USERS_DATA_DIR, username, 'installations', f'server_{guild_id}')
    os.makedirs(install_dir, exist_ok=True)
    repo_dir = os.path.join(install_dir, 'discord-server-setup')

    if not os.path.exists(repo_dir):
        import shutil as _shutil
        if not os.path.isdir(SETUP_TEMPLATE_DIR):
            return jsonify({'error': 'Setup template directory not found. Re-install DiscordForge.'}), 500
        _shutil.copytree(SETUP_TEMPLATE_DIR, repo_dir)

    # 2. Write config.json
    config_path = os.path.join(repo_dir, 'config.json')
    config = build_server_config(server_name, icon_path, guild_id, repo_dir, config_path,
                               custom_roles=custom_roles, categories=categories,
                               welcome_template=welcome_template, community_server=community_server,
                               moderator_users=moderator_users, server_assets=server_assets,
                               server_webhooks=server_webhooks, community_settings=community_settings,
                               bot_token=effective_token, banner_data=banner_data, vanity_url=vanity_url)
    if effective_token and maint_bot_name:
        config['discord_bots'] = [{'id': str(uuid.uuid4()), 'name': maint_bot_name, 'token': effective_token, 'client_id': maint_bot_cid, 'maintenance': True}]
    save_server_config(config_path, config)

    # 3. Save server record (setup_completed=False — runs in phase 2)
    server_data = {
        "server_id": server_id,
        "server_name": server_name,
        "guild_id": guild_id,
        "owner": username,
        "icon_path": icon_path,
        "custom_roles": custom_roles,
        "categories": categories,
        "welcome_template": welcome_template,
        "community_server": community_server,
        "moderator_users": moderator_users,
        "server_assets": server_assets,
        "install_dir": install_dir,
        "config_path": config_path,
        "setup_completed": False,
        "created_at": datetime.now().isoformat()
    }
    servers_data[server_id] = server_data
    save_servers(servers_data)

    if server_id not in users[username]['servers']:
        users[username]['servers'].append(server_id)
        save_users(users)

    # 4. Check if the bot is already in the guild; only build invite URL when it isn't.
    in_guild = check_bot_in_guild(guild_id, effective_token) if effective_token else False
    if not in_guild and maint_bot_cid:
        invite_url = build_invite_url(maint_bot_cid, guild_id)
    else:
        invite_url = None

    return jsonify({
        'success':   True,
        'server_id': server_id,
        'in_guild':  in_guild,
        'invite_url': invite_url,
        'bot_name':  maint_bot_name,
    })


@app.route('/api/discord-linked-users')
@login_required
def discord_linked_users():
    """Return Discord-linked users who share at least one server with the caller."""
    caller   = session['user_id']
    users    = load_users()
    servers  = load_servers()
    # Collect usernames that co-own at least one server with the caller
    caller_servers = set(users.get(caller, {}).get('servers', []))
    visible = set()
    for sid, srv in servers.items():
        if sid in caller_servers:
            visible.add(srv.get('owner', ''))
    visible.add(caller)  # always include self
    result = []
    for username, info in users.items():
        if username in visible and info.get('discord_id'):
            result.append({
                'username':        username,
                'discord_id':      info['discord_id'],
                'discord_username': info.get('discord_username', ''),
            })
    result.sort(key=lambda u: u['username'].lower())
    return jsonify({'users': result})


def _post_setup_apply_assets(server_id, config_path, log_path):
    """After setup/update succeeds, upload any configured assets using the first bot token."""
    import base64 as _b64, time as _time
    log_lines = []

    def _write_log():
        if not log_lines:
            return
        try:
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write('\n--- Asset upload ---\n' + '\n'.join(log_lines) + '\n')
        except Exception:
            pass

    def _strip(d):
        return d.split(',', 1)[1] if d and d.startswith('data:') and ',' in d else d

    def _data_url(d, mime):
        return f'data:{mime};base64,{_strip(d)}'

    try:
        cfg = load_server_config(config_path)
        if not cfg:
            log_lines.append('⚠️ asset-upload: config not found')
            return
        # Prefer the designated maintenance bot; fall back to bot_token.
        _bots = cfg.get('discord_bots', [])
        token = next((b['token'] for b in _bots if b.get('maintenance') and b.get('token')), None)
        if not token:
            token = next((b['token'] for b in _bots if b.get('token')), None)
        if not token:
            token = cfg.get('bot_token') or None
        if not token:
            log_lines.append('⚠️ asset-upload: no bot token in config — add a bot first')
            return
        guild_id = cfg.get('server', {}).get('guild_id', '')
        if not guild_id:
            log_lines.append('⚠️ asset-upload: guild_id missing from config')
            return
        assets = cfg.get('server_assets', {})
        has_assets = any(assets.get(k) for k in ('emoji', 'stickers', 'soundboard'))
        if not has_assets:
            return

        ok_e, live_e, _ = _disc_get(token, f'/guilds/{guild_id}/emojis')
        live_emoji_names = {e['name'].lower() for e in (live_e if ok_e and isinstance(live_e, list) else [])}
        for emoji in assets.get('emoji', []):
            name, fd = emoji.get('name', ''), emoji.get('file_data')
            if not name or not fd or name.lower() in live_emoji_names:
                continue
            try:
                ext  = (emoji.get('file_name') or 'e.png').rsplit('.', 1)[-1].lower()
                mime = {'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg','gif':'image/gif','webp':'image/webp'}.get(ext, 'image/png')
                ok, res, _ = _disc_post(token, f'/guilds/{guild_id}/emojis', {'name': name, 'image': _data_url(fd, mime)})
                log_lines.append(f'{"✅" if ok else "❌"} emoji:{name}' + (f' — {res.get("message", "")}' if not ok else ''))
            except Exception as exc:
                log_lines.append(f'❌ emoji:{name} — exception: {exc}')
            _time.sleep(0.4)

        ok_s, live_s, _ = _disc_get(token, f'/guilds/{guild_id}/stickers')
        live_sticker_names = {s['name'].lower() for s in (live_s if ok_s and isinstance(live_s, list) else [])}
        for sticker in assets.get('stickers', []):
            name, fd = sticker.get('name', ''), sticker.get('file_data')
            if not name or not fd or name.lower() in live_sticker_names:
                continue
            try:
                fn   = sticker.get('file_name') or 'sticker.png'
                ext  = fn.rsplit('.', 1)[-1].lower()
                mime = {'png':'image/png','gif':'image/gif','json':'application/json'}.get(ext, 'image/png')
                ok, res, status = _disc_post(token, f'/guilds/{guild_id}/stickers',
                                        payload={'name': name, 'description': sticker.get('description', name), 'tags': '⭐'},
                                        files={'file': (fn, _b64.b64decode(_strip(fd)), mime)})
                if not ok and status == 429:
                    retry_after = res.get('retry_after', 2)
                    log_lines.append(f'⏳ sticker:{name} — rate limited, retrying in {retry_after}s')
                    _time.sleep(float(retry_after) + 0.2)
                    ok, res, status = _disc_post(token, f'/guilds/{guild_id}/stickers',
                                            payload={'name': name, 'description': sticker.get('description', name), 'tags': '⭐'},
                                            files={'file': (fn, _b64.b64decode(_strip(fd)), mime)})
                if ok:
                    live_sticker_names.add(name.lower())
                log_lines.append(f'{"✅" if ok else "❌"} sticker:{name}' + (f' — {res.get("message", f"HTTP {status}")}' if not ok else ''))
            except Exception as exc:
                log_lines.append(f'❌ sticker:{name} — exception: {exc}')
            _time.sleep(1.5)

        ok_sb, live_sb_raw, _ = _disc_get(token, f'/guilds/{guild_id}/soundboard-sounds')
        sb_items = (live_sb_raw.get('items', []) if isinstance(live_sb_raw, dict) else live_sb_raw) if ok_sb else []
        live_sound_names = {s['name'].lower() for s in (sb_items if isinstance(sb_items, list) else [])}
        for sound in assets.get('soundboard', []):
            name, fd = sound.get('name', ''), sound.get('file_data')
            if not name or not fd or name.lower() in live_sound_names:
                continue
            try:
                fn   = sound.get('file_name') or 'sound.mp3'
                ext  = fn.rsplit('.', 1)[-1].lower()
                amime = {'mp3':'audio/mpeg','ogg':'audio/ogg','wav':'audio/wav'}.get(ext, 'audio/mpeg')
                payload = {'name': name, 'sound': _data_url(fd, amime), 'volume': 1.0}
                if sound.get('emoji_name'):
                    payload['emoji_name'] = sound['emoji_name']
                ok, res, _ = _disc_post(token, f'/guilds/{guild_id}/soundboard-sounds', payload)
                log_lines.append(f'{"✅" if ok else "❌"} sound:{name}' + (f' — {res.get("message", "")}' if not ok else ''))
            except Exception as exc:
                log_lines.append(f'❌ sound:{name} — exception: {exc}')
            _time.sleep(0.5)

    except Exception as exc:
        log_lines.append(f'❌ asset-upload aborted — {exc}')
    finally:
        _write_log()


def _post_setup_apply_guild_settings(config_path, log_path):
    """Apply tier-gated guild settings after setup/update: banner, vanity URL, voice bitrates."""
    import time as _time
    log_lines = []

    def _append_log():
        if not log_lines:
            return
        try:
            with open(log_path, 'a', encoding='utf-8') as lf:
                lf.write('\n--- Guild settings ---\n' + '\n'.join(log_lines) + '\n')
        except Exception:
            pass

    def _strip(d):
        return d.split(',', 1)[1] if d and d.startswith('data:') and ',' in d else d

    try:
        cfg = load_server_config(config_path)
        if not cfg:
            return
        bots = cfg.get('discord_bots', [])
        token = (
            next((b['token'] for b in bots if b.get('maintenance') and b.get('token')), None)
            or next((b['token'] for b in bots if b.get('token')), None)
            or cfg.get('bot_token') or None
        )
        if not token:
            return
        guild_id = cfg.get('server', {}).get('guild_id', '')
        if not guild_id:
            return

        patch_payload = {}

        # Banner
        banner_data = cfg.get('banner_data')
        if banner_data:
            try:
                raw   = _strip(banner_data)
                ext   = 'gif' if 'image/gif' in banner_data else 'png'
                mime  = f'image/{ext}'
                patch_payload['banner'] = f'data:{mime};base64,{raw}'
            except Exception as exc:
                log_lines.append(f'❌ banner encode — {exc}')

        # Vanity URL
        vanity_url = cfg.get('vanity_url')
        if vanity_url:
            try:
                ok, res, status = _disc_patch(token, f'/guilds/{guild_id}', {'vanity_url_code': vanity_url})
                if ok:
                    log_lines.append(f'✅ vanity URL set to discord.gg/{vanity_url}')
                else:
                    log_lines.append(f'❌ vanity URL — {res.get("message", f"HTTP {status}")}')
            except Exception as exc:
                log_lines.append(f'❌ vanity URL — {exc}')

        # Apply banner via guild PATCH
        if patch_payload:
            try:
                ok, res, status = _disc_patch(token, f'/guilds/{guild_id}', patch_payload)
                if ok:
                    log_lines.append('✅ server banner applied')
                else:
                    log_lines.append(f'❌ banner — {res.get("message", f"HTTP {status}")}')
            except Exception as exc:
                log_lines.append(f'❌ banner — {exc}')

        # Voice channel bitrates — fetch live channels, match by name, PATCH each
        categories = cfg.get('custom_categories', [])
        channels_with_bitrate = [
            ch for cat in categories for ch in cat.get('voice_channels', [])
            if ch.get('bitrate')
        ]
        if channels_with_bitrate:
            try:
                ok_ch, live_chs, _ = _disc_get(token, f'/guilds/{guild_id}/channels')
                if ok_ch and isinstance(live_chs, list):
                    live_voice = {ch['name'].lower(): ch['id'] for ch in live_chs if ch.get('type') == 2}
                    for ch in channels_with_bitrate:
                        ch_id = live_voice.get(ch['name'].lower())
                        if not ch_id:
                            continue
                        bitrate_bps = int(ch['bitrate']) * 1000
                        ok_p, res_p, st_p = _disc_patch(token, f'/channels/{ch_id}', {'bitrate': bitrate_bps})
                        if ok_p:
                            log_lines.append(f'✅ bitrate {ch["bitrate"]}kbps → #{ch["name"]}')
                        else:
                            log_lines.append(f'❌ bitrate #{ch["name"]} — {res_p.get("message", f"HTTP {st_p}")}')
                        _time.sleep(0.3)
            except Exception as exc:
                log_lines.append(f'❌ voice bitrates — {exc}')

    except Exception as exc:
        log_lines.append(f'❌ guild-settings aborted — {exc}')
    finally:
        _append_log()


@app.route('/api/guild-limits', methods=['GET'])
@login_required
def guild_limits_api():
    """
    Return premium tier, boost count, computed asset limits, and unlocked features
    for a Discord guild. Uses the server's stored bot token.
    """
    guild_id  = request.args.get('guild_id',  '').strip()
    server_id = request.args.get('server_id', '').strip()

    if not guild_id:
        return jsonify({'error': 'guild_id required'}), 400

    # Resolve the best available token from the server's config
    token = None
    if server_id:
        username = session['user_id']
        _, server = get_server_or_404(server_id, username)
        if server:
            install_dir = os.path.abspath(server['install_dir'])
            config_path = os.path.join(install_dir, 'discord-server-setup', 'config.json')
            cfg  = load_server_config(config_path) or {}
            bots = cfg.get('discord_bots', [])
            token = (
                next((b['token'] for b in bots if b.get('maintenance') and b.get('token')), None)
                or next((b['token'] for b in bots if b.get('token')), None)
                or cfg.get('bot_token')
            )

    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    try:
        resp = requests.get(
            f'https://discord.com/api/v10/guilds/{guild_id}',
            headers={'Authorization': f'Bot {token}'},
            timeout=10
        )
    except Exception as exc:
        return jsonify({'error': str(exc)}), 502

    if resp.status_code != 200:
        return jsonify({'error': f'Discord returned {resp.status_code} — make sure the bot is in this guild'}), resp.status_code

    guild  = resp.json()
    tier   = int(guild.get('premium_tier', 0))
    boosts = int(guild.get('premium_subscription_count', 0) or 0)

    tier_thresholds = [0, 2, 7, 14]
    next_threshold  = tier_thresholds[tier + 1] if tier < 3 else None
    boosts_to_next  = (next_threshold - boosts) if next_threshold is not None else 0

    limits = {
        'emoji':      [50, 100, 150, 250][tier],
        'stickers':   [5,   15,  30,  60][tier],
        'soundboard': 8,
        'bitrate':    [96, 128, 256, 384][tier],
    }
    features = {
        'animated_icon':     tier >= 1,
        'invite_background': tier >= 1,
        'banner':            tier >= 2,
        'animated_banner':   tier >= 3,
        'vanity_url':        tier >= 3,
    }

    return jsonify({
        'premium_tier':               tier,
        'premium_subscription_count': boosts,
        'boosts_to_next_tier':        boosts_to_next,
        'next_tier_threshold':        next_threshold,
        'limits':                     limits,
        'features':                   features,
        'guild_name':                 guild.get('name', ''),
    })


@app.route('/api/validate-bot-token', methods=['POST'])
@login_required
def validate_bot_token_api():
    data     = request.get_json() or {}
    token    = str(data.get('token', '')).strip()
    guild_id = str(data.get('guild_id', '')).strip()
    if not token:
        return jsonify({'error': 'Token required'}), 400
    try:
        resp = requests.get(
            'https://discord.com/api/v10/users/@me',
            headers={'Authorization': f'Bot {token}'},
            timeout=8
        )
        if resp.status_code != 200:
            return jsonify({'error': f'Invalid token (Discord returned {resp.status_code})'}), 400
        bot_data  = resp.json()
        client_id = bot_data.get('id', '')
        bot_name  = bot_data.get('username', 'Unknown Bot')
        invite_url = (
            f'https://discord.com/oauth2/authorize'
            f'?client_id={client_id}&permissions=8&scope=bot%20applications.commands'
        )
        # Optionally check if the bot is already in the guild
        in_guild = None
        if guild_id:
            ok_g, _, _ = _disc_get(token, f'/guilds/{guild_id}')
            in_guild = ok_g
        return jsonify({'ok': True, 'bot_name': bot_name, 'client_id': client_id,
                        'invite_url': invite_url, 'in_guild': in_guild})
    except Exception as e:
        return jsonify({'error': f'Could not reach Discord: {e}'}), 500


def _patch_keep_in_guild(script_path: str) -> None:
    """Idempotently patch a cloned Setup/Update script to honour keep_in_guild."""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='replace') as fh:
            src = fh.read()
        if 'keep_in_guild' in src:
            return  # already patched
        old_block = (
            "        try:\n"
            "            print('Removing bot from server...')\n"
            "            await guild.leave()\n"
            "            print('✅ Bot has left the server')\n"
            "        except Exception as e:\n"
            "            print(f'❌ Error leaving server: {e}')\n"
        )
        new_block = (
            "        if not config.get('keep_in_guild', False):\n"
            "            try:\n"
            "                print('Removing bot from server...')\n"
            "                await guild.leave()\n"
            "                print('✅ Bot has left the server')\n"
            "            except Exception as e:\n"
            "                print(f'❌ Error leaving server: {e}')\n"
            "        else:\n"
            "            print('ℹ️ Bot stays in server (keep_in_guild=true)')\n"
        )
        if old_block in src:
            patched = src.replace(old_block, new_block, 1)
            with open(script_path, 'w', encoding='utf-8') as fh:
                fh.write(patched)
            print(f'[INFO] Patched keep_in_guild into {os.path.basename(script_path)}')
    except Exception as e:
        print(f'[WARN] _patch_keep_in_guild failed for {script_path}: {e}')


def _patch_onboarding_names(script_path: str) -> None:
    """Idempotently patch Setup_server.py to apply custom onboarding role/channel names from config."""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='replace') as fh:
            src = fh.read()
        if '_ob_names_patch' in src:
            return  # already patched
        old = (
            "            with open(WELCOME_TEMPLATE_PATH, 'r', encoding='utf-8') as f:\n"
            "                welcome_template = json.load(f)\n"
        )
        new = (
            "            with open(WELCOME_TEMPLATE_PATH, 'r', encoding='utf-8') as f:\n"
            "                welcome_template = json.load(f)\n"
            "            # Apply custom onboarding names if the user configured them  # _ob_names_patch\n"
            "            ob = config.get('onboarding', {})\n"
            "            if ob and welcome_template:\n"
            "                for role_data in welcome_template.get('roles', []):\n"
            "                    if role_data.get('name') == 'Member' and ob.get('member_role_name'):\n"
            "                        role_data['name'] = ob['member_role_name']\n"
            "                for ch_data in welcome_template.get('text_channels', []):\n"
            "                    if ch_data.get('name') == 'welcome' and ob.get('welcome_channel_name'):\n"
            "                        ch_data['name'] = ob['welcome_channel_name']\n"
            "                    elif ch_data.get('name') == 'rules' and ob.get('rules_channel_name'):\n"
            "                        ch_data['name'] = ob['rules_channel_name']\n"
        )
        if old not in src:
            print(f'[WARN] _patch_onboarding_names: expected block not found in {os.path.basename(script_path)}')
            return
        patched = src.replace(old, new, 1)
        with open(script_path, 'w', encoding='utf-8') as fh:
            fh.write(patched)
        print(f'[INFO] Patched onboarding names into {os.path.basename(script_path)}')
    except Exception as e:
        print(f'[WARN] _patch_onboarding_names failed for {script_path}: {e}')


def _patch_custom_roles_dict(script_path: str) -> None:
    """Idempotently patch Setup_server.py to handle custom roles stored as dicts (not plain strings)."""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='replace') as fh:
            src = fh.read()
        if '_custom_roles_dict_patch' in src:
            return  # already patched
        # Match both the old simple loop patterns
        old = (
            "        if 'custom_roles' in config and config['custom_roles']:\n"
            "            for role_name in config['custom_roles']:\n"
            "                role_data = {'name': role_name}\n"
            "                role = await create_role_with_permissions(guild, role_data)\n"
            "                role_map[role_name] = role\n"
        )
        new = (
            "        if 'custom_roles' in config and config['custom_roles']:  # _custom_roles_dict_patch\n"
            "            for entry in config['custom_roles']:\n"
            "                if isinstance(entry, dict):\n"
            "                    role_name = entry['name']\n"
            "                    perms_list = entry.get('permissions', [])\n"
            "                    role_data = {\n"
            "                        'name': role_name,\n"
            "                        'permissions': {p: True for p in perms_list} if isinstance(perms_list, list) else perms_list,\n"
            "                        'color': entry.get('color', 'default'),\n"
            "                        'hoist': entry.get('hoist', False),\n"
            "                    }\n"
            "                else:\n"
            "                    role_name = str(entry)\n"
            "                    role_data = {'name': role_name}\n"
            "                role = await create_role_with_permissions(guild, role_data)\n"
            "                role_map[role_name] = role\n"
        )
        if old not in src:
            print(f'[WARN] _patch_custom_roles_dict: expected block not found in {os.path.basename(script_path)}')
            return
        patched = src.replace(old, new, 1)
        with open(script_path, 'w', encoding='utf-8') as fh:
            fh.write(patched)
        print(f'[INFO] Patched custom_roles dict handling into {os.path.basename(script_path)}')
    except Exception as e:
        print(f'[WARN] _patch_custom_roles_dict failed for {script_path}: {e}')


def _patch_welcome_template(template_dir: str) -> None:
    """Idempotently add announcements channel to welcome_template.json if not already present."""
    tmpl_path = os.path.join(template_dir, 'welcome_template.json')
    if not os.path.exists(tmpl_path):
        return
    try:
        with open(tmpl_path, 'r', encoding='utf-8') as fh:
            tmpl = json.load(fh)
        channels = tmpl.get('text_channels', [])
        names = [ch.get('name', '') if isinstance(ch, dict) else ch for ch in channels]
        if 'announcements' not in names:
            channels.insert(0, {'name': 'announcements', 'permissions': {'view': ['@everyone'], 'deny': []}})
            tmpl['text_channels'] = channels
            with open(tmpl_path, 'w', encoding='utf-8') as fh:
                json.dump(tmpl, fh, indent=4)
            print(f'[INFO] Added announcements channel to welcome_template.json')
    except Exception as e:
        print(f'[WARN] _patch_welcome_template failed: {e}')


def _patch_channel_attrs(script_path: str) -> None:
    """Idempotently patch Setup_server.py to pass nsfw and slowmode_delay from config."""
    try:
        with open(script_path, 'r', encoding='utf-8', errors='replace') as fh:
            src = fh.read()
        if '_ch_nsfw' in src:
            return  # already patched
        old = (
            "                # Create text channels\n"
            "                for channel_data in category_data.get('text_channels', []):\n"
            "                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data\n"
            "                    channel = await guild.create_text_channel(channel_name, category=category)\n"
        )
        new = (
            "                # Create text channels\n"
            "                for channel_data in category_data.get('text_channels', []):\n"
            "                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data\n"
            "                    _ch_nsfw = bool(channel_data.get('nsfw', False)) if isinstance(channel_data, dict) else False\n"
            "                    _ch_slow = int(channel_data.get('slowmode', 0) or 0) if isinstance(channel_data, dict) else 0\n"
            "                    channel = await guild.create_text_channel(channel_name, category=category, nsfw=_ch_nsfw, slowmode_delay=_ch_slow)\n"
        )
        if old not in src:
            print(f'[WARN] _patch_channel_attrs: expected block not found in {os.path.basename(script_path)}')
            return
        patched = src.replace(old, new, 1)
        with open(script_path, 'w', encoding='utf-8') as fh:
            fh.write(patched)
        print(f'[INFO] Patched nsfw/slowmode into {os.path.basename(script_path)}')
    except Exception as e:
        print(f'[WARN] _patch_channel_attrs failed for {script_path}: {e}')


def _patch_forum_community(script_path: str) -> None:
    """Patch Setup_server.py to refresh guild state after enabling Community via fetch_guild (API call).

    discord.py's internal cache doesn't reflect guild.features until a GUILD_UPDATE WS event
    arrives. bot.get_guild() reads the stale cache; bot.fetch_guild() makes a real API call.
    Also removes the has_any_forums override that forced Community on non-community servers.
    """
    try:
        with open(script_path, 'r', encoding='utf-8', errors='replace') as fh:
            src = fh.read()
        if '_guild_refresh_fetch' in src:
            return  # already patched with current version

        # 1. Remove has_any_forums override (forced Community when community_server=false)
        old_flag = (
            "        has_any_forums = any(\n"
            "            cat.get('forum_channels') for cat in config.get('custom_categories', [])\n"
            "        )\n"
            "        if config.get('community_server') or has_any_forums:\n"
        )
        new_flag = "        if config.get('community_server'):  # _guild_refresh_fetch\n"
        if old_flag in src:
            src = src.replace(old_flag, new_flag, 1)

        # 2. Upgrade stale bot.get_guild cache reads (from previous patch version) to fetch_guild
        src = src.replace(
            "                        _fresh = bot.get_guild(int(GUILD_ID))\n"
            "                        if _fresh: guild = _fresh  # _guild_refresh_community\n",
            "                        guild = await bot.fetch_guild(int(GUILD_ID))  # _guild_refresh_fetch\n",
        )
        src = src.replace(
            "                _fresh = bot.get_guild(int(GUILD_ID))\n"
            "                if _fresh: guild = _fresh  # _guild_refresh_community\n",
            "                guild = await bot.fetch_guild(int(GUILD_ID))  # _guild_refresh_fetch\n",
        )

        # 3. If still no fetch_guild (fresh clone), inject it after the asyncio.sleep(1)
        old_sleep = (
            "                        await asyncio.sleep(1)\n"
            "                    except Exception as e:\n"
            "                        print(f'Could not enable Community: {e}')\n"
        )
        new_sleep = (
            "                        await asyncio.sleep(1)\n"
            "                        guild = await bot.fetch_guild(int(GUILD_ID))  # _guild_refresh_fetch\n"
            "                    except Exception as e:\n"
            "                        print(f'Could not enable Community: {e}')\n"
        )
        old_already = (
            "            else:\n"
            "                print('Community already enabled.')\n"
        )
        new_already = (
            "            else:\n"
            "                print('Community already enabled.')\n"
            "                guild = await bot.fetch_guild(int(GUILD_ID))  # _guild_refresh_fetch\n"
        )
        if '_guild_refresh_fetch' not in src:
            if old_sleep in src:
                src = src.replace(old_sleep, new_sleep, 1)
            if old_already in src:
                src = src.replace(old_already, new_already, 1)

        with open(script_path, 'w', encoding='utf-8') as fh:
            fh.write(src)
        print(f'[INFO] Patched Community guild refresh (fetch_guild) in {os.path.basename(script_path)}')
    except Exception as e:
        print(f'[WARN] _patch_forum_community failed for {script_path}: {e}')


@app.route('/api/setup/run', methods=['POST'])
@login_required
def run_setup_api():
    """
    Phase 2: kick off Setup_server.py in a background thread and return immediately.
    The frontend polls /api/setup/status/<server_id> until setup_completed is True.
    """
    username = session['user_id']
    data = request.get_json()
    server_id = data.get('server_id')

    if not server_id:
        return jsonify({'error': 'Missing server_id'}), 400

    servers_data, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    if not has_server_permission(server, username, 'edit_server'):
        return jsonify({'error': 'You need edit access to run setup on this server.'}), 403

    # Don't re-run if already completed
    if server.get('setup_completed'):
        return jsonify({'started': True, 'already_done': True})

    guild_id = server['guild_id']
    # Normalize paths — abspath resolves both relative paths and mixed slashes on Windows
    install_dir = os.path.abspath(server['install_dir'])
    repo_dir    = os.path.join(install_dir, 'discord-server-setup')
    config_path = os.path.join(repo_dir, 'config.json')  # always canonical, never doubled

    cfg_for_check = load_server_config(config_path) or {}
    maint_bots    = [b for b in cfg_for_check.get('discord_bots', []) if b.get('maintenance') and b.get('token')]
    setup_token   = (
        next((b['token'] for b in maint_bots), None)
        or cfg_for_check.get('bot_token')
    )
    if not setup_token:
        return jsonify({'error': 'No bot token configured. Please add your bot in server settings.'}), 400
    if not check_bot_in_guild(guild_id, setup_token):
        return jsonify({
            'error': 'Please invite your bot to your Discord server before running setup.'
        }), 400

    _lock = _get_setup_lock(server_id)
    if not _lock.acquire(blocking=False):
        return jsonify({'error': 'Setup is already running for this server. Please wait.'}), 409

    log_path = os.path.join(server['install_dir'], 'setup_log.txt')

    def _run():
        """Background thread: stream Setup_server.py stdout to a log file line by line."""
        try:
            sd = load_servers()
            sd[server_id]['setup_running'] = True
            sd[server_id]['setup_completed'] = False
            sd[server_id]['setup_error'] = None
            save_servers(sd)

            setup_script = find_file_ci(repo_dir, 'setup_server.py')
            if not setup_script:
                sd = load_servers()
                sd[server_id]['setup_running'] = False
                sd[server_id]['setup_error'] = 'setup_server.py not found'
                save_servers(sd)
                return

            # Patch the cloned script and templates before running
            _patch_keep_in_guild(setup_script)
            _patch_channel_attrs(setup_script)
            _patch_forum_community(setup_script)
            _patch_onboarding_names(setup_script)
            _patch_custom_roles_dict(setup_script)
            _patch_welcome_template(os.path.join(repo_dir, 'templates'))

            # Write config.json with PLAINTEXT tokens. The cloned Setup_server.py reads
            # bot_token directly and passes it to discord.py — it cannot handle enc: values.
            # load_server_config() already decrypts; we bypass save_server_config() here
            # (which would re-encrypt) and write json.dump directly instead.
            try:
                _cfg = load_server_config(config_path) or {}
                _cfg['keep_in_guild'] = True
                _normalize_config_perms(_cfg)
                _tmp = config_path + '.tmp'
                with open(_tmp, 'w', encoding='utf-8') as _f:
                    json.dump(_cfg, _f, indent=4)
                os.replace(_tmp, config_path)
            except Exception as _pe:
                print(f'[WARN] Could not write plaintext config for setup: {_pe}')

            success = False
            error_msg = None

            try:
                with open(log_path, 'w', encoding='utf-8') as log_file:
                    proc = subprocess.Popen(
                        ['python', setup_script, config_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding='utf-8',
                        errors='replace',
                        cwd=repo_dir,
                        env=_utf8_env()
                    )
                    for line in proc.stdout:
                        log_file.write(line)
                        log_file.flush()
                    proc.wait()
                    # discord.py sometimes exits with code 1 after guild.leave() + bot.close()
                    # even when setup completed successfully. Treat stdout marker as ground truth.
                    if '✅ Server setup complete!' in open(log_path, 'r', encoding='utf-8', errors='replace').read():
                        success = True
                    elif proc.returncode == 0:
                        success = True
                    else:
                        error_msg = f'Script exited with code {proc.returncode}'

            except Exception as e:
                error_msg = str(e)
            finally:
                # Re-encrypt tokens in config.json — subprocess left them as plaintext
                try:
                    _re = load_server_config(config_path) or {}
                    save_server_config(config_path, _re)
                except Exception:
                    pass

            if success:
                init_db = os.path.join(repo_dir, 'setup_cogs', 'init_database.py')
                if os.path.exists(init_db):
                    subprocess.run(['python', init_db], cwd=repo_dir, capture_output=True)
                cfg = load_server_config(config_path)
                if cfg:
                    cfg['setup_completed'] = True
                    save_server_config(config_path, cfg)
                # Apply assets (emoji/stickers/soundboard) via user bot token if available
                _post_setup_apply_assets(server_id, config_path, log_path)
                _post_setup_apply_guild_settings(config_path, log_path)

            sd = load_servers()
            sd[server_id]['setup_running'] = False
            sd[server_id]['setup_completed'] = success
            sd[server_id]['setup_error'] = error_msg
            save_servers(sd)
        finally:
            _lock.release()

    threading.Thread(target=_run, daemon=True).start()
    append_event(server['owner'], server_id, server.get('server_name', server_id),
                 'setup', 'Server setup initiated', actor=username)
    return jsonify({'started': True})


@app.route('/api/setup/status/<server_id>', methods=['GET'])
@login_required
def setup_status(server_id):
    """
    Polling endpoint. Returns current setup state for a server.
    Frontend polls this every 3s after calling /api/setup/run.
    """
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    return jsonify({
        'setup_completed': server.get('setup_completed', False),
        'setup_running':   server.get('setup_running', False),
        'setup_error':     server.get('setup_error'),
    })


@app.route('/api/setup/log/<server_id>', methods=['GET'])
@login_required
def setup_log(server_id):
    """
    Returns the current lines of setup_log.txt for a server.
    Frontend polls this alongside /api/setup/status to show live progress.
    """
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    log_path = os.path.join(server['install_dir'], 'setup_log.txt')
    lines = []
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = [l.rstrip() for l in f.readlines() if l.strip()]
        except Exception:
            pass

    return jsonify({'lines': lines})


@app.route('/api/server/<server_id>/assets', methods=['GET', 'POST'])
@login_required
def server_assets_api(server_id):
    """GET: return server_assets. POST: update server_assets in config."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner', '') != username and 'edit_server' not in server.get('user_permissions', []):
        return jsonify({'error': 'Permission denied'}), 403

    config_path = server.get('config_path', '')
    cfg = load_server_config(config_path) or {}
    current_assets = cfg.get('server_assets', {'emoji': [], 'stickers': [], 'soundboard': []})

    if request.method == 'GET':
        return jsonify({'assets': current_assets})

    data = request.get_json(silent=True) or {}
    new_assets = data.get('assets', {})
    if not isinstance(new_assets, dict):
        return jsonify({'error': 'Invalid assets payload'}), 400
    new_assets.setdefault('emoji', [])
    new_assets.setdefault('stickers', [])
    new_assets.setdefault('soundboard', [])

    cfg['server_assets'] = new_assets
    save_server_config(config_path, cfg)

    servers_data = load_servers()
    if server_id in servers_data:
        servers_data[server_id]['server_assets'] = new_assets
        save_servers(servers_data)

    return jsonify({'ok': True, 'assets': new_assets})


@app.route('/api/server/<server_id>/assets/live', methods=['GET'])
@login_required
def server_assets_live(server_id):
    """Fetch emoji, stickers, and soundboard directly from Discord via the bot token."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    guild_id = server.get('guild_id', '')
    config_path = server.get('config_path', '')
    cfg = load_server_config(config_path) or {}

    # Prefer the maintenance bot token, fall back to the first discord_bot token
    bot_token = cfg.get('bot_token')
    if not bot_token:
        for bot in cfg.get('discord_bots', []):
            t = bot.get('token')
            if t:
                bot_token = t
                break

    if not bot_token:
        return jsonify({'error': 'No bot token configured', 'bot_online': False}), 400

    if not check_bot_in_guild(guild_id, bot_token):
        return jsonify({'error': 'Bot is offline or not in this server', 'bot_online': False}), 503

    headers = {'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'}

    try:
        emoji_r   = requests.get(f"{DISCORD_API}/guilds/{guild_id}/emojis",           headers=headers, timeout=8)
        sticker_r = requests.get(f"{DISCORD_API}/guilds/{guild_id}/stickers",          headers=headers, timeout=8)
        sound_r   = requests.get(f"{DISCORD_API}/guilds/{guild_id}/soundboard-sounds", headers=headers, timeout=8)

        if emoji_r.status_code == 200:
            emojis = [
                {'id': e['id'], 'name': e['name'], 'animated': e.get('animated', False)}
                for e in emoji_r.json() if e.get('id')
            ]
        else:
            emojis = []

        if sticker_r.status_code == 200:
            stickers = [
                {'id': s['id'], 'name': s['name'],
                 'description': s.get('description', ''),
                 'format_type': s.get('format_type', 1)}
                for s in sticker_r.json() if s.get('id')
            ]
        else:
            stickers = []

        if sound_r.status_code == 200:
            raw = sound_r.json()
            sound_items = raw.get('items', raw) if isinstance(raw, dict) else raw
            sounds = [
                {'sound_id': s['sound_id'], 'name': s['name'],
                 'emoji_name': s.get('emoji_name', ''),
                 'volume': s.get('volume', 1.0)}
                for s in sound_items if isinstance(s, dict) and s.get('sound_id')
            ]
        else:
            sounds = []

        return jsonify({
            'bot_online': True,
            'assets': {'emoji': emojis, 'stickers': stickers, 'soundboard': sounds}
        })
    except Exception as e:
        return jsonify({'error': str(e), 'bot_online': True}), 500


@app.route('/api/server/<server_id>/assets/push', methods=['POST'])
@login_required
def server_assets_push(server_id):
    """Trigger immediate asset upload to Discord for the given server."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner', '') != username and 'edit_server' not in server.get('user_permissions', []):
        return jsonify({'error': 'Permission denied'}), 403
    config_path = server.get('config_path', '')

    # Pre-flight diagnostics so silent early returns are surfaced to the UI
    cfg = load_server_config(config_path) or {}
    if not cfg:
        return jsonify({'ok': False, 'error': 'Server config not found. Has setup been run?'}), 400
    _bots = cfg.get('discord_bots', [])
    _token = (next((b['token'] for b in _bots if b.get('maintenance') and b.get('token')), None)
              or next((b['token'] for b in _bots if b.get('token')), None)
              or cfg.get('bot_token') or None)
    if not _token:
        return jsonify({'ok': False, 'error': 'No bot token configured. Add a bot to this server first.'}), 400
    if not cfg.get('server', {}).get('guild_id', ''):
        return jsonify({'ok': False, 'error': 'guild_id missing from server config.'}), 400
    _assets = cfg.get('server_assets', {})
    _uploadable = [
        item for key in ('emoji', 'stickers', 'soundboard')
        for item in _assets.get(key, [])
        if item.get('file_data')
    ]
    if not _uploadable:
        return jsonify({'ok': False, 'error': (
            'No assets with file data found. Use the file picker (📁 Choose Image/Audio) to attach '
            'files before adding — saved text-only names cannot be uploaded to Discord.'
        )}), 400

    import tempfile as _tempfile, os as _os
    log_fd, log_path = _tempfile.mkstemp(suffix='.log', prefix='assets_push_')
    _os.close(log_fd)
    try:
        _post_setup_apply_assets(server_id, config_path, log_path)
        try:
            with open(log_path, 'r', encoding='utf-8') as f:
                log = f.read()
        except Exception:
            log = ''
        return jsonify({'ok': True, 'log': log})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500
    finally:
        try:
            _os.unlink(log_path)
        except Exception:
            pass


@app.route('/api/server/<server_id>/edit-data', methods=['GET'])
@login_required
def server_edit_data(server_id):
    """Return editable config fields for the inline edit modals."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner', '') != username and 'edit_server' not in server.get('user_permissions', []):
        return jsonify({'error': 'Permission denied'}), 403

    config_path = server.get('config_path', '')
    cfg = load_server_config(config_path) or {}
    cs = cfg.get('community_settings', {})

    return jsonify({
        'info': {
            'server_name':     cfg.get('server_name', server.get('server_name', '')),
            'welcome_template': cfg.get('welcome_template', server.get('welcome_template', 'no')),
            'community_server': cfg.get('community_server', server.get('community_server', False)),
            'vanity_url':      cfg.get('vanity_url', server.get('vanity_url', '')) or '',
        },
        'community_settings': {
            'verification_level':    cs.get('verification_level', 'medium'),
            'content_filter':        cs.get('content_filter', 'all_members'),
            'default_notifications': cs.get('default_notifications', 'only_mentions'),
        },
        'roles': cfg.get('custom_roles', server.get('custom_roles', [])),
        'moderation': {
            'moderator_users': cfg.get('moderator_users', server.get('moderator_users', [])),
        },
    })


@app.route('/api/server/<server_id>/patch', methods=['POST'])
@login_required
def server_patch(server_id):
    """Patch individual sections of server config from the inline edit modals."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner', '') != username and 'edit_server' not in server.get('user_permissions', []):
        return jsonify({'error': 'Permission denied'}), 403

    data    = request.get_json(silent=True) or {}
    section = data.get('section')
    payload = data.get('data', {})

    if section not in ('info', 'roles', 'moderation', 'community'):
        return jsonify({'error': f'Unknown section: {section}'}), 400

    config_path  = server.get('config_path', '')
    cfg          = load_server_config(config_path) or {}
    servers_data = load_servers()

    def _sync(key, val):
        cfg[key] = val
        if server_id in servers_data:
            servers_data[server_id][key] = val

    if section == 'info':
        name = str(payload.get('server_name', '')).strip()
        if name:
            _sync('server_name', name)
            # Also update the nested key that Setup_server.py reads
            if isinstance(cfg.get('server'), dict):
                cfg['server']['name'] = name
            # Attempt a live Discord rename via the maintenance bot token
            guild_id = server.get('guild_id', '')
            maint_bots = [b for b in cfg.get('discord_bots', []) if b.get('maintenance') and b.get('token')]
            bot_token = (maint_bots[0].get('token') if maint_bots else None) or cfg.get('bot_token')
            if guild_id and bot_token:
                try:
                    requests.patch(
                        f"{DISCORD_API}/guilds/{guild_id}",
                        headers={'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'},
                        json={'name': name},
                        timeout=8,
                    )
                except Exception:
                    pass
        _sync('welcome_template', payload.get('welcome_template', cfg.get('welcome_template', 'no')))

    elif section == 'roles':
        old_custom_roles = list(cfg.get('custom_roles', []))   # snapshot before _sync
        roles = payload.get('custom_roles', [])
        _RESERVED = {'admin', 'moderator', 'moderation'}
        clean = []
        for r in roles:
            if isinstance(r, dict):
                name = r.get('name', '').strip()
                if name and name.lower() not in _RESERVED:
                    clean.append({
                        'name':        name,
                        'color':       r.get('color', '#99aab5'),
                        'hoist':       bool(r.get('hoist', False)),
                        'permissions': r.get('permissions', []),
                    })
        _sync('custom_roles', clean)

        # Apply diff live to Discord
        guild_id  = server.get('guild_id', '')
        bot_token = _bot_token_for_server(cfg)
        if guild_id and bot_token:
            _discord_apply_roles_diff(guild_id, bot_token, old_custom_roles, clean)

    elif section == 'moderation':
        mods = [str(m).strip() for m in payload.get('moderator_users', []) if str(m).strip()]
        _sync('moderator_users', mods)

    elif section == 'community':
        was_community = bool(cfg.get('community_server', False))
        now_community = bool(payload.get('community_server', False))
        _sync('community_server', now_community)
        vanity = str(payload.get('vanity_url', '') or '').strip().lower() or None
        _sync('vanity_url', vanity)
        cs = cfg.get('community_settings', {})
        for k in ('verification_level', 'content_filter'):
            if k in payload:
                cs[k] = payload[k]
        cs.setdefault('verification_level', 'medium')
        cs.setdefault('content_filter', 'all_members')
        cs.setdefault('default_notifications', 'only_mentions')
        cs.setdefault('system_channel', '')
        _sync('community_settings', cs)
        if server_id in servers_data:
            servers_data[server_id]['community_settings'] = cs

        # Disable Community on Discord if the flag was just turned off
        if was_community and not now_community:
            guild_id  = server.get('guild_id', '')
            bot_token = _bot_token_for_server(cfg)
            if guild_id and bot_token:
                try:
                    headers = {'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'}
                    guild_resp = requests.get(f"{DISCORD_API}/guilds/{guild_id}",
                                             headers=headers, timeout=10)
                    if guild_resp.ok:
                        current_features = guild_resp.json().get('features', [])
                        new_features = [f for f in current_features if f != 'COMMUNITY']
                        requests.patch(f"{DISCORD_API}/guilds/{guild_id}", headers=headers,
                                       json={
                                           'features':                   new_features,
                                           'rules_channel_id':           None,
                                           'public_updates_channel_id':  None,
                                       }, timeout=10)
                except Exception as e:
                    print(f'[WARN] Could not disable Community on Discord: {e}')

    save_server_config(config_path, cfg)
    save_servers(servers_data)
    return jsonify({'ok': True})


def _build_cats_from_channel_list(all_ch):
    """Convert a flat Discord channel list to the nested categories structure (camelCase).

    Channels without a parent_id are welcome/moderation template channels managed outside
    the wizard config — they are intentionally excluded to avoid a phantom General category.
    """
    cat_map = {}
    for ch in sorted(all_ch, key=lambda x: x.get('position', 0)):
        if ch.get('type') == 4:
            cat_map[ch['id']] = {
                'name': ch['name'], 'private': False, 'roles': [],
                'textChannels': [], 'voiceChannels': [], 'forumChannels': [],
                '_position': ch.get('position', 0),
            }

    for ch in sorted(all_ch, key=lambda x: x.get('position', 0)):
        if ch.get('type') == 4:
            continue
        bucket = cat_map.get(ch.get('parent_id'))
        if bucket is None:
            continue  # skip uncategorised channels (welcome/mod template channels)
        name = ch.get('name', '')
        t = ch.get('type')
        if t == 0:
            bucket['textChannels'].append({'name': name, 'private': False, 'roles': []})
        elif t == 2:
            bucket['voiceChannels'].append({'name': name, 'private': False, 'roles': []})
        elif t == 15:
            bucket['forumChannels'].append({'name': name, 'private': False, 'roles': []})

    cats = sorted(cat_map.values(), key=lambda c: c['_position'])
    for c in cats:
        del c['_position']
    return cats


def _persist_cats(server_id, config_path, cats):
    """Persist camelCase cats list to both servers_data.json and config.json."""
    try:
        sd = load_servers()
        if server_id in sd:
            sd[server_id]['categories'] = cats
            save_servers(sd)
    except Exception:
        pass

    try:
        cfg = load_server_config(config_path) or {}
        cfg['custom_categories'] = [
            {
                'name': cat['name'],
                'private': cat.get('private', False),
                'text_channels':  [ch if isinstance(ch, dict) else {'name': ch} for ch in cat.get('textChannels', [])],
                'voice_channels': [ch if isinstance(ch, dict) else {'name': ch} for ch in cat.get('voiceChannels', [])],
                'forum_channels': [ch if isinstance(ch, dict) else {'name': ch} for ch in cat.get('forumChannels', [])],
            }
            for cat in cats
        ]
        save_server_config(config_path, cfg)
    except Exception:
        pass


def _sync_categories_from_discord(server_id, guild_id, bot_token, config_path):
    """Re-fetch guild channels from Discord and persist to both data stores (fire-and-forget safe)."""
    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{guild_id}/channels",
                            headers={'Authorization': f'Bot {bot_token}'}, timeout=10)
        if not resp.ok:
            return
        all_ch = resp.json()
    except Exception:
        return

    cats = _build_cats_from_channel_list(all_ch)
    _persist_cats(server_id, config_path, cats)


@app.route('/api/server/<server_id>/live-channels', methods=['GET'])
@login_required
def live_channels_get(server_id):
    """Return the current channel/category structure directly from Discord."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    cfg       = load_server_config(server.get('config_path', '')) or {}
    bot_token = _bot_token_for_server(cfg)
    guild_id  = server.get('guild_id', '')

    if not guild_id or not bot_token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    try:
        resp = requests.get(f"{DISCORD_API}/guilds/{guild_id}/channels",
                            headers={'Authorization': f'Bot {bot_token}'}, timeout=10)
        if not resp.ok:
            return jsonify({'error': f'Discord API returned {resp.status_code}'}), 502
        all_ch   = resp.json()
        # Sync as side effect so the static page display always reflects reality
        _persist_cats(server_id, server.get('config_path', ''), _build_cats_from_channel_list(all_ch))
        cats     = sorted([c for c in all_ch if c['type'] == 4],  key=lambda x: x.get('position', 0))
        channels = sorted([c for c in all_ch if c['type'] != 4],  key=lambda x: x.get('position', 0))
        return jsonify({'categories': cats, 'channels': channels})
    except Exception as e:
        return jsonify({'error': str(e)}), 502


@app.route('/api/server/<server_id>/live-channels/op', methods=['POST'])
@login_required
def live_channels_op(server_id):
    """Execute a single create / rename / delete operation on a Discord channel or category."""
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner', '') != username and 'edit_server' not in server.get('user_permissions', []):
        return jsonify({'error': 'Permission denied'}), 403

    cfg       = load_server_config(server.get('config_path', '')) or {}
    bot_token = _bot_token_for_server(cfg)
    guild_id  = server.get('guild_id', '')

    if not guild_id or not bot_token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    data    = request.get_json(silent=True) or {}
    op      = data.get('op')
    headers = {'Authorization': f'Bot {bot_token}', 'Content-Type': 'application/json'}

    config_path = server.get('config_path', '')

    def _sync():
        _sync_categories_from_discord(server_id, guild_id, bot_token, config_path)

    try:
        if op == 'create_category':
            name = str(data.get('name', '')).strip()
            if not name:
                return jsonify({'error': 'name required'}), 400
            r = requests.post(f"{DISCORD_API}/guilds/{guild_id}/channels",
                              headers=headers, json={'name': name, 'type': 4}, timeout=10)
            if not r.ok:
                return jsonify({'error': f'Discord: {r.status_code} — {r.text[:300]}'}), 502
            _sync()
            return jsonify({'ok': True, 'channel': r.json()})

        elif op == 'create_channel':
            name      = str(data.get('name', '')).strip()
            ch_type   = int(data.get('type', 0))          # 0=text 2=voice 15=forum
            parent_id = data.get('parent_id')
            if not name:
                return jsonify({'error': 'name required'}), 400
            body = {'name': name, 'type': ch_type}
            if parent_id:
                body['parent_id'] = str(parent_id)
                # Copy parent category's permission overwrites so channels in private
                # categories are restricted immediately without needing a second edit
                try:
                    cat_r = requests.get(f"{DISCORD_API}/channels/{parent_id}",
                                         headers=headers, timeout=5)
                    if cat_r.ok:
                        parent_overwrites = cat_r.json().get('permission_overwrites', [])
                        if parent_overwrites:
                            body['permission_overwrites'] = parent_overwrites
                except Exception:
                    pass
            r = requests.post(f"{DISCORD_API}/guilds/{guild_id}/channels",
                              headers=headers, json=body, timeout=10)
            if not r.ok:
                return jsonify({'error': f'Discord: {r.status_code} — {r.text[:300]}'}), 502
            _sync()
            return jsonify({'ok': True, 'channel': r.json()})

        elif op == 'rename':
            channel_id = str(data.get('channel_id', ''))
            name       = str(data.get('name', '')).strip()
            if not channel_id or not name:
                return jsonify({'error': 'channel_id and name required'}), 400
            r = requests.patch(f"{DISCORD_API}/channels/{channel_id}",
                               headers=headers, json={'name': name}, timeout=10)
            if not r.ok:
                return jsonify({'error': f'Discord: {r.status_code} — {r.text[:300]}'}), 502
            _sync()
            return jsonify({'ok': True})

        elif op == 'delete':
            channel_id = str(data.get('channel_id', ''))
            if not channel_id:
                return jsonify({'error': 'channel_id required'}), 400
            r = requests.delete(f"{DISCORD_API}/channels/{channel_id}",
                                headers=headers, timeout=10)
            if not r.ok:
                try:
                    err_json = r.json()
                except Exception:
                    err_json = {}
                if err_json.get('code') == 50074:
                    return jsonify({'error': (
                        'This channel is set as your server\'s Rules or Updates channel and cannot be deleted. '
                        'In Discord: Server Settings → Community → unset it first, then delete here.'
                    )}), 409
                return jsonify({'error': f'Discord: {r.status_code} — {r.text[:300]}'}), 502
            _sync()
            return jsonify({'ok': True})

        elif op == 'edit':
            channel_id = str(data.get('channel_id', ''))
            if not channel_id:
                return jsonify({'error': 'channel_id required'}), 400
            patch = {}
            if 'name'               in data: patch['name']                = str(data['name']).strip()
            if 'topic'              in data: patch['topic']               = str(data['topic'])
            if 'nsfw'               in data: patch['nsfw']                = bool(data['nsfw'])
            if 'rate_limit_per_user'in data: patch['rate_limit_per_user'] = max(0, int(data['rate_limit_per_user']))
            if not patch:
                return jsonify({'error': 'Nothing to update'}), 400
            r = requests.patch(f"{DISCORD_API}/channels/{channel_id}",
                               headers=headers, json=patch, timeout=10)
            if not r.ok:
                return jsonify({'error': f'Discord: {r.status_code} — {r.text[:300]}'}), 502
            _sync()
            return jsonify({'ok': True})

        else:
            return jsonify({'error': f'Unknown op: {op}'}), 400

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/update/invite', methods=['POST'])
@login_required
def update_invite():
    """
    Returns { in_guild: bool, invite_url: str } for the update flow.
    The frontend checks this first — if the bot isn't in the guild it shows
    the invite step before calling /api/update/run.
    """
    username = session['user_id']
    data = request.get_json()
    server_id = data.get('server_id')

    if not server_id:
        return jsonify({'error': 'Missing server_id'}), 400

    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    guild_id = server['guild_id']

    # Resolve which bot token to use — same logic as run_setup_api
    install_dir = os.path.abspath(server['install_dir'])
    config_path = os.path.join(install_dir, 'discord-server-setup', 'config.json')
    cfg        = load_server_config(config_path) or {}
    maint_bots = [b for b in cfg.get('discord_bots', []) if b.get('maintenance') and b.get('token')]
    chosen     = maint_bots[0] if maint_bots else None
    bot_token  = (chosen or {}).get('token') or cfg.get('bot_token')
    bot_client_id = (chosen or {}).get('client_id') or ''
    bot_name   = (chosen or {}).get('name', 'Your Bot')

    in_guild   = check_bot_in_guild(guild_id, bot_token)
    invite_url = (
        build_invite_url(bot_client_id, guild_id)
        if (not in_guild and bot_client_id) else None
    )

    return jsonify({
        'in_guild':   in_guild,
        'invite_url': invite_url,
        'bot_name':   bot_name,
    })


@app.route('/api/update/run', methods=['POST'])
@login_required
def run_update_api():
    """
    Run update_server.py in a background thread for an existing server.
    Uses the same polling pattern as /api/setup/run.
    """
    username   = session['user_id']
    data       = request.get_json()
    server_id  = data.get('server_id')
    use_bot_id = data.get('use_bot_id')  # optional: bot ID to use for this update run

    if not server_id:
        return jsonify({'error': 'Missing server_id'}), 400

    servers_data, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    if not has_server_permission(server, username, 'edit_server'):
        return jsonify({'error': 'You need edit access to run updates on this server.'}), 403

    install_dir = os.path.abspath(server['install_dir'])
    repo_dir    = os.path.join(install_dir, 'discord-server-setup')
    config_path = os.path.join(repo_dir, 'config.json')
    log_path    = os.path.join(install_dir, 'update_log.txt')

    # Auto-deploy update_server.py into the repo if it's not there yet.
    # This covers existing servers created before the file existed, and any
    # new servers — it just lives next to app.py and gets copied on demand.
    update_script = find_file_ci(repo_dir, 'update_server.py')
    if not update_script:
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'update_server.py')
        if os.path.isfile(src):
            dest = os.path.join(repo_dir, 'update_server.py')
            shutil.copy2(src, dest)
            update_script = dest
            print(f'[INFO] Copied update_server.py into {repo_dir}')
        else:
            return jsonify({'error': 'update_server.py not found — place it next to app.py'}), 404

    def _run():
        sd = load_servers()
        sd[server_id]['update_running'] = True
        sd[server_id]['update_error']   = None
        save_servers(sd)

        # If the caller chose a specific bot, temporarily patch bot_token in config
        original_token = None
        if use_bot_id:
            try:
                cfg = load_server_config(config_path) or {}
                bots = cfg.get('discord_bots', [])
                chosen = next((b for b in bots if str(b.get('bot_id') or b.get('id') or '') == str(use_bot_id)), None)
                if chosen and chosen.get('token'):
                    original_token = cfg.get('bot_token')
                    cfg['bot_token'] = chosen['token']
                    save_server_config(config_path, cfg)
            except Exception as _e:
                print(f'[WARN] use_bot_id patch failed: {_e}')

        # Patch script and set keep_in_guild before running
        _patch_keep_in_guild(update_script)
        _patch_channel_attrs(update_script)
        _patch_forum_community(update_script)
        # Write config.json with PLAINTEXT tokens (same reason as setup flow above).
        try:
            _cfg = load_server_config(config_path) or {}
            _cfg['keep_in_guild'] = True
            _normalize_config_perms(_cfg)
            _tmp = config_path + '.tmp'
            with open(_tmp, 'w', encoding='utf-8') as _f:
                json.dump(_cfg, _f, indent=4)
            os.replace(_tmp, config_path)
        except Exception as _pe:
            print(f'[WARN] Could not write plaintext config for update: {_pe}')

        success    = False
        error_msg  = None
        try:
            with open(log_path, 'w', encoding='utf-8') as log_file:
                proc = subprocess.Popen(
                    ['python', update_script, config_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    cwd=repo_dir,
                    env=_utf8_env()
                )
                for line in proc.stdout:
                    log_file.write(line)
                    log_file.flush()
                proc.wait()
                # discord.py sometimes exits with code 1 after guild.leave() + bot.close()
                # even when setup completed successfully. Treat stdout marker as ground truth.
                if '✅ Server update complete!' in open(log_path, 'r', encoding='utf-8', errors='replace').read():
                    success = True
                elif proc.returncode == 0:
                    success = True
                else:
                    error_msg = f'Script exited with code {proc.returncode}'
        except Exception as e:
            error_msg = str(e)
        finally:
            # Re-encrypt tokens (subprocess left them plaintext); restore use_bot_id patch if applied
            try:
                cfg = load_server_config(config_path) or {}
                if original_token is not None:
                    cfg['bot_token'] = original_token
                save_server_config(config_path, cfg)
            except Exception:
                pass

        sd = load_servers()
        sd[server_id]['update_running'] = False
        sd[server_id]['update_error']   = error_msg
        # Re-use setup_completed flag so the status endpoint works for both flows
        if success:
            sd[server_id]['setup_completed'] = True
            _post_setup_apply_assets(server_id, config_path, log_path)
            _post_setup_apply_guild_settings(config_path, log_path)
        save_servers(sd)

    threading.Thread(target=_run, daemon=True).start()
    append_event(server['owner'], server_id, server.get('server_name', server_id),
                 'update', 'Configuration update applied', actor=username)
    return jsonify({'started': True})


@app.route('/api/update/log/<server_id>', methods=['GET'])
@login_required
def update_log(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    log_path = os.path.join(os.path.abspath(server['install_dir']), 'update_log.txt')
    lines = []
    if os.path.exists(log_path):
        try:
            with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
                lines = [l.rstrip() for l in f.readlines() if l.strip()]
        except Exception:
            pass
    return jsonify({'lines': lines})


@app.route('/api/update/status/<server_id>', methods=['GET'])
@login_required
def update_status(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    return jsonify({
        'update_running':  server.get('update_running', False),
        'update_complete': not server.get('update_running', False) and server.get('update_error') is None and server.get('setup_completed', False),
        'update_error':    server.get('update_error'),
    })


# ============================================
# COLLABORATORS & INVITES
# ============================================

PERMISSIONS = ['view_server', 'edit_server', 'view_bots', 'edit_bots']

@app.route('/api/invites/create', methods=['POST'])
@login_required
def create_invite():
    """Owner creates a one-time invite link with specific permissions."""
    username = session['user_id']
    data = request.get_json()
    server_id   = data.get('server_id')
    permissions = data.get('permissions', ['view_server'])

    servers_data, server = get_server_or_404(server_id, username, require_permission='manage_collaborators')
    if not server:
        # Also allow owner explicitly
        servers_data, server = get_server_or_404(server_id)
        if not server or server['owner'] != username:
            return jsonify({'error': 'Not found or not authorized'}), 404

    # Validate permissions
    permissions = [p for p in permissions if p in PERMISSIONS]
    if not permissions:
        return jsonify({'error': 'No valid permissions selected'}), 400

    token = secrets.token_urlsafe(24)
    invites = load_invites()
    invites[token] = {
        'server_id':    server_id,
        'server_name':  server['server_name'],
        'permissions':  permissions,
        'created_by':   username,
        'created_at':   datetime.now().isoformat(),
        'used':         False,
    }
    save_invites(invites)

    invite_url = f"/invite/{token}"
    return jsonify({'success': True, 'token': token, 'invite_url': invite_url})


@app.route('/invite/<token>', methods=['GET', 'POST'])
def accept_invite(token):
    """Redirect to React SPA invite page; keep POST path for legacy compatibility."""
    if request.method == 'GET':
        return redirect(f'/app/invite/{token}')
    # Legacy POST kept for backward compatibility
    invites = load_invites()
    invite  = invites.get(token)

    if not invite:
        flash('❌ Invalid or expired invite link.', 'error')
        return redirect(url_for('dashboard'))
    if invite.get('used'):
        flash('❌ This invite link has already been used.', 'error')
        return redirect(url_for('dashboard'))
    # Expiry: invites older than 7 days are rejected
    INVITE_TTL_DAYS = 7
    try:
        created = datetime.fromisoformat(invite.get('created_at', ''))
        if (datetime.now() - created).days >= INVITE_TTL_DAYS:
            flash('❌ This invite link has expired (valid for 7 days).', 'error')
            return redirect(url_for('dashboard'))
    except (ValueError, TypeError):
        pass

    # Must be logged in
    if 'user_id' not in session:
        session['pending_invite'] = token
        flash('Please log in to accept the invite.', 'error')
        return redirect(url_for('login'))

    username = session['user_id']
    servers_data = load_servers()
    server_id = invite['server_id']

    if server_id not in servers_data:
        flash('❌ Server no longer exists.', 'error')
        return redirect(url_for('dashboard'))

    server = servers_data[server_id]

    if server['owner'] == username:
        flash('ℹ️ You are already the owner of this server.', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'GET':
        return redirect(f'/app/invite/{token}')  # React InvitePage

    # POST — legacy accept (React uses /api/invite/<token>/accept instead)
    collabs = server.setdefault('collaborators', {})
    # Merge permissions if already a collaborator
    existing = set(collabs.get(username, []))
    existing.update(invite['permissions'])
    users = load_users()
    discord_id = users.get(username, {}).get('discord_id', '')
    discord_uname = users.get(username, {}).get('discord_username', '')
    collabs[username] = {
        'permissions':        list(existing),
        'discord_id':         discord_id,
        'discord_username':   discord_uname,
        'added_at':           datetime.now().isoformat(),
    }
    servers_data[server_id] = server
    save_servers(servers_data)

    # Mark invite as used
    invites[token]['used'] = True
    invites[token]['used_by'] = username
    invites[token]['used_at'] = datetime.now().isoformat()
    save_invites(invites)

    perm_str = ', '.join(invite.get('permissions', []))
    append_event(server['owner'], server_id, invite['server_name'],
                 'collab_invite', f'"{username}" accepted invite (permissions: {perm_str})',
                 actor=username)

    flash(f'✅ You now have access to {invite["server_name"]}!', 'success')
    return redirect(url_for('dashboard'))


@app.route('/api/collaborators/<server_id>', methods=['GET'])
@login_required
def get_collaborators(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id)
    if not server or server['owner'] != username:
        return jsonify({'error': 'Not authorized'}), 403

    return jsonify({'collaborators': server.get('collaborators', {})})


@app.route('/api/collaborators/<server_id>/update', methods=['POST'])
@login_required
def update_collaborator(server_id):
    """Update permissions for an existing collaborator."""
    username = session['user_id']
    data = request.get_json()
    target_user = data.get('username')
    permissions = data.get('permissions', [])

    servers_data, server = get_server_or_404(server_id)
    if not server or server['owner'] != username:
        return jsonify({'error': 'Not authorized'}), 403

    permissions = [p for p in permissions if p in PERMISSIONS]
    collabs = server.setdefault('collaborators', {})

    if not permissions:
        collabs.pop(target_user, None)
        msg = f'{target_user} removed as collaborator.'
        append_event(username, server_id, server.get('server_name', server_id),
                     'collab_remove', f'Collaborator "{target_user}" removed', actor=username)
    else:
        existing = collabs.get(target_user, {})
        if isinstance(existing, list):
            existing = {}
        existing['permissions'] = permissions
        collabs[target_user] = existing
        perm_str = ', '.join(permissions)
        msg = f'{target_user} permissions updated.'
        append_event(username, server_id, server.get('server_name', server_id),
                     'collab_add', f'Collaborator "{target_user}" granted: {perm_str}', actor=username)

    servers_data[server_id] = server
    save_servers(servers_data)
    return jsonify({'success': True, 'message': msg})


@app.route('/api/collaborators/<server_id>/remove', methods=['POST'])
@login_required
def remove_collaborator(server_id):
    username = session['user_id']
    data = request.get_json()
    target_user = data.get('username')

    servers_data, server = get_server_or_404(server_id)
    if not server or server['owner'] != username:
        return jsonify({'error': 'Not authorized'}), 403

    server.get('collaborators', {}).pop(target_user, None)
    servers_data[server_id] = server
    save_servers(servers_data)
    return jsonify({'success': True, 'message': f'{target_user} removed.'})

@app.route('/collaborators/<server_id>')
@login_required
def collaborators_page(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('dashboard'))
    if server['owner'] != username:
        flash('Only the server owner can manage collaborators.', 'error')
        return redirect(url_for('servers_page'))
    return redirect('/app/')  # React CollaboratorsPage


@app.route('/server/<server_id>/overview')
@login_required
def server_overview(server_id):
    return redirect('/app/')  # React ServerPage / DashboardPage


@app.route('/edit_server/<server_id>')
@login_required
def edit_server(server_id):
    return redirect('/app/')  # React SettingsPage


@app.route('/delete_server/<server_id>', methods=['POST'])
@login_required
@csrf_protect
def delete_server(server_id):
    username = session['user_id']
    servers_data = load_servers()
    users = load_users()

    if server_id not in servers_data:
        flash('Server not found', 'error')
        return redirect(url_for('dashboard'))

    server = servers_data[server_id]
    if server['owner'] != username:
        flash('You are not the owner of this server', 'error')
        return redirect(url_for('dashboard'))

    # Delete icon
    icon_path = server.get('icon_path')
    if icon_path and os.path.exists(icon_path):
        try:
            os.remove(icon_path)
        except OSError:
            pass

    # Delete installation directory
    install_dir = server.get('install_dir')
    if install_dir and os.path.exists(install_dir):
        try:
            rmtree_force(install_dir)
        except Exception as e:
            flash(f'Warning: could not fully remove installation files: {e}', 'warning')

    del servers_data[server_id]
    save_servers(servers_data)

    if server_id in users[username].get('servers', []):
        users[username]['servers'].remove(server_id)
        save_users(users)

    flash('Server deleted successfully', 'success')
    return redirect(url_for('dashboard'))


@app.route('/api/environment/<server_id>/rename', methods=['POST'])
@login_required
def rename_environment(server_id):
    username = session['user_id']
    data = request.get_json(silent=True) or {}
    new_name = str(data.get('env_name', '')).strip()
    if not new_name:
        return jsonify({'error': 'Name cannot be empty'}), 400
    if len(new_name) > 80:
        return jsonify({'error': 'Name too long (max 80 chars)'}), 400

    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404

    servers_data = load_servers()
    if server_id not in servers_data:
        return jsonify({'error': 'Not found'}), 404
    old_name = servers_data[server_id].get('env_name') or servers_data[server_id].get('server_name', server_id)
    servers_data[server_id]['env_name'] = new_name
    save_servers(servers_data)
    srv_name = servers_data[server_id].get('server_name', server_id)
    append_event(servers_data[server_id]['owner'], server_id, srv_name,
                 'rename', f'Environment renamed from "{old_name}" to "{new_name}"', actor=username)
    return jsonify({'ok': True, 'env_name': new_name})


@app.route('/environment/<server_id>/activity')
@login_required
def env_activity(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        flash('Environment not found or access denied.', 'error')
        return redirect(url_for('dashboard'))
    if server['owner'] != username:
        flash('Only the environment owner can view the activity log.', 'error')
        return redirect(url_for('dashboard'))
    return redirect('/app/')  # React ActivityPage


@app.route('/api/environment/<server_id>/events')
@login_required
def env_events(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server or server['owner'] != username:
        return jsonify({'error': 'Not found or not authorized'}), 404
    path = os.path.join(USERS_DATA_DIR,username, 'events.json')
    events = load_json(path, [])
    events = [e for e in events if e.get('server_id') == server_id]
    events.sort(key=lambda e: e.get('ts', ''), reverse=True)
    for e in events:
        e['icon'] = _EVENT_ICONS.get(e.get('type', ''), '📌')
    return jsonify(events)


@app.route('/api/environment/<server_id>/events/export')
@login_required
def export_env_events(server_id):
    import csv as _csv
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server or server['owner'] != username:
        return jsonify({'error': 'Not authorized'}), 403
    path = os.path.join(USERS_DATA_DIR,username, 'events.json')
    events = load_json(path, [])
    events = [e for e in events if e.get('server_id') == server_id]
    events.sort(key=lambda e: e.get('ts', ''), reverse=True)
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(['Timestamp (UTC)', 'Type', 'Actor', 'Description'])
    for e in events:
        writer.writerow([e.get('ts',''), e.get('type',''), e.get('actor',''), e.get('description','')])
    env_name = (server.get('env_name') or server.get('server_name', server_id)).replace(' ', '_')
    fname = f'{env_name}_activity_{datetime.now(timezone.utc).strftime("%Y%m%d")}.csv'
    return buf.getvalue(), 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{fname}"',
    }


# ============================================
# BOTS PAGE
# ============================================

@app.route('/servers')
@login_required
def servers_page():
    return redirect('/app/')  # React SPA server list


@app.route('/api/servers/<server_id>', methods=['GET'])
@login_required
def server_detail_api(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    server = dict(server)
    config = load_server_config(server.get('config_path'))
    server['discord_bots'] = config.get('discord_bots', []) if config else []
    cogs_dir = (config or {}).get('paths', {}).get('cogs_dir', '')
    server['installed_cogs'] = []
    if cogs_dir and os.path.isdir(cogs_dir):
        server['installed_cogs'] = [
            d for d in os.listdir(cogs_dir)
            if os.path.isdir(os.path.join(cogs_dir, d)) and not d.startswith('__')
        ]
    return jsonify(server)


@app.route('/bots')
@login_required
def bots_page():
    return redirect('/app/')  # React BotPage


@app.route('/bots/logs/<server_id>/<bot_id>')
@login_required
def bot_logs_page(server_id, bot_id):
    return redirect('/app/')  # React BotPage logs tab


# ============================================
# BOT CONFIGURATION
# ============================================

def _get_authorized_config(server_id, user_id, permission='edit_server'):
    """
    Shared helper: validate access and return (servers_data, server, config, config_path).
    Returns (None, None, None, None) on any failure.
    """
    servers_data, server = get_server_or_404(server_id, user_id, require_permission=permission)
    if not server:
        return None, None, None, None

    config_path = server.get('config_path')
    config = load_server_config(config_path)
    if config is None:
        return None, None, None, None

    return servers_data, server, config, config_path


@app.route('/api/servers/list', methods=['GET'])
@login_required
def servers_list_api():
    """Returns a minimal list of servers the current user owns or collaborates on."""
    username = session['user_id']
    users = load_users()
    servers_data = load_servers()

    user_servers = set(users[username].get('servers', []))
    for sid, srv in servers_data.items():
        if username in srv.get('collaborators', {}):
            user_servers.add(sid)

    servers = [
        {'server_id': sid, 'server_name': servers_data[sid]['server_name'], 'guild_id': servers_data[sid]['guild_id']}
        for sid in user_servers if sid in servers_data
    ]
    return jsonify({
        'servers': servers,
        'count': count_user_servers(username),
    })


_bot_info_cache: dict = {}  # bot_id → {'avatar_url': str, 'fetched_at': float}

def _fetch_bot_discord_info(bot_id, token):
    """Background fetch of bot's Discord avatar. Cached in _bot_info_cache."""
    if not token:
        return
    try:
        r = requests.get(
            'https://discord.com/api/v10/users/@me',
            headers={'Authorization': f'Bot {token}'},
            timeout=3,
        )
        if r.ok:
            d = r.json()
            uid = d.get('id', '')
            av  = d.get('avatar', '')
            url = (f'https://cdn.discordapp.com/avatars/{uid}/{av}.png?size=64'
                   if (uid and av) else '')
            _bot_info_cache[bot_id] = {'avatar_url': url, 'fetched_at': time.time()}
            return
    except Exception:
        pass
    _bot_info_cache[bot_id] = {'avatar_url': '', 'fetched_at': time.time()}


@app.route('/api/bots/list', methods=['GET'])
@login_required
def list_bots():
    """
    Returns all bots across all servers owned by this user,
    as a flat list the dashboard can render.
    """
    username = session['user_id']
    users = load_users()
    servers_data = load_servers()

    import bot_docker as _bd
    docker_statuses = _bd.get_all_statuses() if _bd.is_docker_mode() else {}

    # Collect owned servers + collaborated servers where user has bot access
    bot_server_ids = set(users[username].get('servers', []))
    for sid, srv in servers_data.items():
        entry = srv.get('collaborators', {}).get(username)
        if entry is not None:
            perms = entry if isinstance(entry, list) else entry.get('permissions', [])
            if 'view_bots' in perms or 'edit_bots' in perms:
                bot_server_ids.add(sid)

    bots = []
    for server_id in bot_server_ids:
        if server_id not in servers_data:
            continue
        server = servers_data[server_id]
        config = load_server_config(server.get('config_path'))
        if not config:
            continue
        # Read installed cogs from the filesystem for this server
        cogs_dir = os.path.join(server.get('install_dir', ''), 'discord-server-setup', 'cogs')
        installed_scripts = []
        if os.path.exists(cogs_dir):
            installed_scripts = [
                {'id': d, 'name': d.replace('_', ' ').replace('-', ' ').title()}
                for d in os.listdir(cogs_dir)
                if os.path.isdir(os.path.join(cogs_dir, d)) and not d.startswith('__')
            ]

        config_dirty = False
        for bot in config.get('discord_bots', []):
            # Lazily assign a stable ID to bots that pre-date this field
            if not bot.get('id'):
                bot['id'] = str(uuid.uuid4())
                config_dirty = True
            key    = f'{server_id}:{bot["name"]}'
            status = docker_statuses.get(key, bot.get('local_status', 'offline')) \
                     if docker_statuses else bot.get('local_status', 'offline')
            pid    = None
            # Kick off background avatar fetch if not cached or stale (1 h TTL)
            cached_info = _bot_info_cache.get(bot['id'])
            if cached_info is None or time.time() - cached_info.get('fetched_at', 0) > 3600:
                threading.Thread(
                    target=_fetch_bot_discord_info,
                    args=(bot['id'], bot.get('token', '')),
                    daemon=True,
                ).start()
            bot_avatar_url = (cached_info or {}).get('avatar_url', '')

            bots.append({
                'bot_id':            bot['id'],
                'bot_name':          bot['name'],
                'guild_id':          server['guild_id'],
                'server_name':       server['server_name'],
                'server_id':         server_id,
                'status':            status,
                'pid':               pid,
                'installed_scripts': installed_scripts,
                'created_at':        server.get('created_at', ''),
                'local_status':      bot.get('local_status', 'offline'),
                'local_last_seen':   bot.get('local_last_seen', None),
                'ping':              bot.get('local_ping_ms', 0),
                'uptime':            bot.get('local_uptime', '—'),
                'avatar_url':        bot_avatar_url,
                'runner':            os.environ.get('BOT_RUNNER', 'subprocess'),
            })
        if config_dirty:
            save_server_config(server.get('config_path'), config)

    return jsonify({
        'bots': bots,
        'count': len(bots),
    })


@app.route('/api/bots/add-to-server', methods=['POST'])
@login_required
def add_bot_to_server():
    data = request.json
    server_id = data.get('server_id')
    bot_name = data.get('bot_name')
    bot_token = data.get('bot_token')

    if not all([server_id, bot_name, bot_token]):
        return jsonify({'error': 'Missing required fields'}), 400

    username = session['user_id']
    _, _, config, config_path = _get_authorized_config(server_id, username, permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found, not authorized, or config missing'}), 404

    bots = config.setdefault('discord_bots', [])
    if any(b['token'] == bot_token for b in bots):
        return jsonify({'error': 'Bot already configured'}), 400

    bots.append({'id': str(uuid.uuid4()), 'name': bot_name, 'token': bot_token})
    save_server_config(config_path, config)

    srv_name = (load_servers().get(server_id) or {}).get('server_name', server_id)
    owner    = (load_servers().get(server_id) or {}).get('owner', username)
    append_event(owner, server_id, srv_name, 'bot_add', f'Bot "{bot_name}" added', actor=username)
    return jsonify({'success': True, 'message': f'Bot {bot_name} added.', 'total_bots': len(bots)})


@app.route('/api/bots/remove-from-server', methods=['POST'])
@login_required
def remove_bot_from_server():
    data = request.json
    server_id = data.get('server_id')
    bot_id    = data.get('bot_id')

    if not all([server_id, bot_id]):
        return jsonify({'error': 'Missing required fields'}), 400

    _, _, config, config_path = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found, not authorized, or config missing'}), 404

    config['discord_bots'] = [b for b in config.get('discord_bots', []) if b.get('id') != bot_id]
    save_server_config(config_path, config)

    return jsonify({'success': True, 'message': 'Bot removed successfully'})


@app.route('/api/bots/delete', methods=['POST'])
@login_required
def delete_bot():
    data = request.json
    server_id = data.get('server_id')
    bot_id    = data.get('bot_id')

    if not all([server_id, bot_id]):
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, config, config_path = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found, not authorized, or config missing'}), 404

    bot_cfg = _find_bot_by_id(config, bot_id)
    if not bot_cfg:
        return jsonify({'error': 'Bot not found'}), 404

    bot_name  = bot_cfg['name']
    bot_token = bot_cfg['token']

    # Remove bot from config and delete its config file
    config['discord_bots'] = [b for b in config.get('discord_bots', []) if b.get('id') != bot_id]
    save_server_config(config_path, config)

    install_dir = server.get('install_dir', '')
    bot_config_file = os.path.join(install_dir, 'discord-server-setup', f'config_{bot_name}.json')
    if os.path.isfile(bot_config_file):
        os.remove(bot_config_file)

    # Kick the bot from the Discord server
    guild_id = server.get('guild_id')
    kicked = False
    kick_error = None
    if guild_id and bot_token:
        try:
            resp = requests.delete(
                f'https://discord.com/api/v10/users/@me/guilds/{guild_id}',
                headers={'Authorization': f'Bot {bot_token}'},
                timeout=10,
            )
            # 204 = left successfully, 404 = bot was already not in the server
            kicked = resp.status_code in (204, 404)
            if not kicked:
                kick_error = f'Discord API returned {resp.status_code}'
        except requests.RequestException as e:
            kick_error = str(e)

    actor = session['user_id']
    append_event(server['owner'], server_id, server.get('server_name', server_id),
                 'bot_delete', f'Bot "{bot_name}" deleted', actor=actor)
    return jsonify({
        'success': True,
        'message': f'Bot {bot_name} deleted.',
        'kicked_from_server': kicked,
        'kick_error': kick_error,
    })


@app.route('/api/bots/start', methods=['POST'])
@login_required
def start_bot():
    data      = request.json
    server_id = data.get('server_id')
    bot_id    = data.get('bot_id')

    if not all([server_id, bot_id]):
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found, not authorized, or config missing'}), 404

    bot_cfg  = _find_bot_by_id(config, bot_id)
    if not bot_cfg:
        return jsonify({'error': 'Bot not configured'}), 404

    bot_name  = bot_cfg['name']
    bot_token = bot_cfg['token']

    import bot_docker as _bd
    if _bd.is_docker_mode():
        single_config = dict(config)
        single_config['discord_bots'] = [bot_cfg]
        ok, msg = _bd.start(server_id, bot_name, bot_token, single_config)
        if not ok:
            return jsonify({'error': msg}), 500
        threading.Thread(
            target=_send_bot_log,
            args=(server['guild_id'], bot_name, 'online', 'container started', bot_token),
            daemon=True
        ).start()
        return jsonify({'success': True, 'message': f'Bot {bot_name} started in container.'})

    return jsonify({
        'error': 'Start/stop is only available in Docker mode. Use your downloaded bot_manager package to control local bots.',
        'local_required': True,
    }), 400


@app.route('/api/bots/stop', methods=['POST'])
@login_required
def stop_bot():
    data      = request.json
    server_id = data.get('server_id')
    bot_id    = data.get('bot_id')

    if not all([server_id, bot_id]):
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found, not authorized, or config missing'}), 404

    bot_cfg = _find_bot_by_id(config, bot_id)
    if not bot_cfg:
        return jsonify({'error': 'Bot not found in config'}), 404

    bot_name  = bot_cfg['name']
    bot_token = bot_cfg['token']

    import bot_docker as _bd
    if _bd.is_docker_mode():
        ok, msg = _bd.stop(server_id, bot_name)
        if not ok:
            return jsonify({'error': msg}), 500
        threading.Thread(
            target=_send_bot_log,
            args=(server['guild_id'], bot_name, 'offline', '', bot_token),
            daemon=True
        ).start()
        return jsonify({'success': True, 'message': f'Bot {bot_name} stopped.'})

    return jsonify({'success': True, 'message': 'Local bot — stop it via your bot_manager package.'})


_LOCAL_BOT_PY = '''\
import discord
from discord.ext import commands
import json, os, logging, asyncio, aiohttp, time
from logging.handlers import RotatingFileHandler

# Config path comes from BOT_CONFIG env var so bot_manager.py can run multiple
# bots in the same folder by giving each its own config_<name>.json file.
_cfg_path = os.environ.get(
    'BOT_CONFIG',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
)
_cfg_stem = os.path.splitext(os.path.basename(_cfg_path))[0]   # e.g. "config_mybot"
_log_path = os.path.join(os.path.dirname(os.path.abspath(_cfg_path)), f'{_cfg_stem}.log')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"),
    ],
)

with open(_cfg_path, "r", encoding="utf-8") as _f:
    _cfg = json.load(_f)

TOKEN     = _cfg["bot_token"]
PREFIX    = _cfg.get("prefix", "!")
API_URL   = _cfg.get("api_url", "")
API_TOKEN = _cfg.get("api_token", "")
SERVER_ID = _cfg.get("server_id", "")          # composite key for web API calls
BOT_ID    = _cfg.get("bot_id", "")
GUILD_ID  = _cfg.get("server", {}).get("guild_id", "")  # numeric Discord guild ID

# ── utils.config_loader shim ──────────────────────────────────────────
# Cogs written for launcher.py do `from utils.config_loader import ...`
# Inject a compatible module so they load without errors.
import sys as _sys, types as _types
if "utils.config_loader" not in _sys.modules:
    _um  = _types.ModuleType("utils")
    _ucm = _types.ModuleType("utils.config_loader")
    def _shim_load_config():
        _srv = _cfg.get("server", {})
        return {
            "guild_id":     _srv.get("guild_id", _cfg.get("guild_id", "")),
            "server_name":  _srv.get("name",     _cfg.get("server_name", "")),
            "discord_bots": _cfg.get("discord_bots", [
                {"token": _cfg.get("bot_token", ""), "name": _cfg.get("bot_name", "")}
            ]),
            "paths": _cfg.get("paths", {}),
        }
    def _shim_get_bot_token(bot_name=None):
        _c    = _shim_load_config()
        _bots = _c.get("discord_bots", [])
        if bot_name:
            return next((b.get("token","") for b in _bots if b.get("name") == bot_name), "")
        return _bots[0].get("token", "") if _bots else ""
    _ucm.load_config   = _shim_load_config
    _ucm.get_bot_token = _shim_get_bot_token
    _um.config_loader  = _ucm
    _sys.modules["utils"]               = _um
    _sys.modules["utils.config_loader"] = _ucm
# ─────────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents)
_BOT_START_TIME = time.time()


def _uptime_str():
    s = int(time.time() - _BOT_START_TIME)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h {m}m" if h > 0 else f"{m}m {sec}s"


async def _post(path, payload):
    if not API_URL or not API_TOKEN:
        return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(
                f"{API_URL}{path}",
                json=payload,
                headers={"X-Bot-Token": API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=5),
            )
    except Exception:
        pass


@bot.event
async def on_ready():
    logging.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    await _post("/api/local-bot/heartbeat", {
        "server_id": SERVER_ID, "bot_id": BOT_ID, "status": "online",
        "ping_ms": round(bot.latency * 1000),
        "uptime": _uptime_str(),
    })
    if GUILD_ID:
        guild = discord.utils.get(bot.guilds, id=int(GUILD_ID))
        if guild:
            bot_role = discord.utils.get(guild.roles, name="Bot")
            if bot_role and bot_role not in guild.me.roles:
                try:
                    await guild.me.add_roles(bot_role)
                    logging.info("Assigned \'Bot\' role to self.")
                except Exception as _e:
                    logging.warning(f"Could not assign Bot role: {_e}")
            try:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                logging.info("Slash commands synced to guild.")
            except Exception as _e:
                logging.warning(f"Could not sync slash commands: {_e}")
    bot.loop.create_task(_heartbeat_loop())


def _tail_log(n=50):
    if not os.path.exists(_log_path):
        return []
    try:
        with open(_log_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return []


_restart_pending = False


async def _heartbeat_loop():
    global _restart_pending
    while not bot.is_closed():
        await asyncio.sleep(30)
        await _post("/api/local-bot/heartbeat", {
            "server_id": SERVER_ID, "bot_id": BOT_ID, "status": "online",
            "log_tail": _tail_log(50),
            "ping_ms": round(bot.latency * 1000),
            "uptime": _uptime_str(),
        })
        await _execute_commands()
        if _restart_pending:
            _restart_pending = False
            logging.info("Restarting bot process as requested via dashboard.")
            import subprocess as _sp, sys as _sys
            _sp.Popen([_sys.executable] + _sys.argv)
            await bot.close()
            return


async def _execute_commands():
    if not API_URL or not API_TOKEN or not SERVER_ID:
        return
    try:
        async with aiohttp.ClientSession() as s:
            r = await s.get(
                f"{API_URL}/api/local-bot/commands",
                headers={"X-Bot-Token": API_TOKEN},
                params={"server_id": SERVER_ID, "bot_id": BOT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if r.status != 200:
                return
            data = await r.json()
    except Exception:
        return
    guild = discord.utils.get(bot.guilds, id=int(GUILD_ID)) if GUILD_ID else None
    if not guild:
        return
    for cmd in data.get("commands", []):
        await _run_cmd(guild, cmd)


async def _run_cmd(guild, cmd):
    global _restart_pending
    cmd_id   = cmd.get("id", "")
    ctype    = cmd.get("type", "")
    reason   = cmd.get("reason") or "Action via dashboard"
    rolename = cmd.get("role_name", "")
    success, err = False, ""

    if ctype == "restart" and cmd.get("bot_id", BOT_ID) == BOT_ID:
        _restart_pending = True
        success = True
        await _post("/api/local-bot/command-result", {
            "server_id": SERVER_ID, "bot_id": BOT_ID,
            "command_id": cmd_id, "success": True, "error": "",
        })
        return

    if ctype == "sync_scripts":
        import zipfile as _zf, io as _io
        scripts  = cmd.get("scripts", [])
        synced, errs = [], []
        cogs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cogs")
        os.makedirs(cogs_dir, exist_ok=True)
        for script_name in scripts:
            try:
                async with aiohttp.ClientSession() as _s:
                    _r = await _s.get(
                        f"{API_URL}/api/local-bot/script-zip",
                        headers={"X-Bot-Token": API_TOKEN},
                        params={"server_id": SERVER_ID, "script": script_name},
                        timeout=aiohttp.ClientTimeout(total=30),
                    )
                    if _r.status != 200:
                        errs.append(f"{script_name}: HTTP {_r.status}")
                        continue
                    zip_bytes = await _r.read()
                dest = os.path.join(cogs_dir, script_name)
                os.makedirs(dest, exist_ok=True)
                with _zf.ZipFile(_io.BytesIO(zip_bytes)) as _z:
                    _z.extractall(dest)
                synced.append(script_name)
                logging.info(f"Synced script: {script_name}")
            except Exception as _e:
                errs.append(f"{script_name}: {_e}")
                logging.error(f"Failed to sync script {script_name}: {_e}")
        for script_name in synced:
            folder = os.path.join(cogs_dir, script_name)
            for _fn in sorted(os.listdir(folder)):
                if not _fn.endswith(".py") or _fn.startswith("_"):
                    continue
                try:
                    with open(os.path.join(folder, _fn), "r", encoding="utf-8") as _f:
                        _src = _f.read()
                    if "def setup(" not in _src and "async def setup(" not in _src:
                        continue
                    ext = f"cogs.{script_name}.{_fn[:-3]}"
                    try:
                        await bot.reload_extension(ext)
                    except commands.ExtensionNotLoaded:
                        await bot.load_extension(ext)
                    logging.info(f"Reloaded cog: {ext}")
                except Exception as _e:
                    logging.error(f"Failed to reload {script_name}/{_fn}: {_e}")
        if synced and GUILD_ID:
            _guild = discord.utils.get(bot.guilds, id=int(GUILD_ID))
            if _guild:
                try:
                    bot.tree.copy_global_to(guild=_guild)
                    await bot.tree.sync(guild=_guild)
                    logging.info("Slash commands synced after script sync.")
                except Exception as _e:
                    logging.warning(f"Could not sync slash commands: {_e}")
        await _post("/api/local-bot/command-result", {
            "server_id": SERVER_ID, "bot_id": BOT_ID,
            "command_id": cmd_id,
            "success": len(synced) > 0,
            "error": "; ".join(errs),
        })
        return

    try:
        uid    = int(cmd.get("user_id", 0))
        member = guild.get_member(uid) or await guild.fetch_member(uid)
        if ctype == "kick":
            await member.kick(reason=reason)
            success = True
        elif ctype == "ban":
            await member.ban(reason=reason, delete_message_days=0)
            success = True
        elif ctype in ("assign_role", "remove_role"):
            role = discord.utils.get(guild.roles, name=rolename)
            if not role:
                err = f"Role \'{rolename}\' not found"
            else:
                if ctype == "assign_role":
                    await member.add_roles(role, reason=reason)
                else:
                    await member.remove_roles(role, reason=reason)
                success = True
        elif ctype == "sync_roles":
            success = True  # handled by bot owner manually for now
    except Exception as e:
        err = str(e)[:200]
    await _post("/api/local-bot/command-result", {
        "server_id": SERVER_ID, "bot_id": BOT_ID,
        "command_id": cmd_id, "success": success, "error": err,
    })


async def load_cogs():
    cogs_path = os.path.join(os.path.dirname(__file__), "cogs")
    if not os.path.isdir(cogs_path):
        return
    loaded, failed = 0, 0
    for folder_name in sorted(os.listdir(cogs_path)):
        folder_path = os.path.join(cogs_path, folder_name)
        if not os.path.isdir(folder_path) or folder_name.startswith("_"):
            continue
        for fname in sorted(os.listdir(folder_path)):
            if not fname.endswith(".py") or fname.startswith("_"):
                continue
            fpath = os.path.join(folder_path, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as _f:
                    src = _f.read()
                if "def setup(" not in src and "async def setup(" not in src:
                    continue
                ext = f"cogs.{folder_name}.{fname[:-3]}"
                await bot.load_extension(ext)
                logging.info(f"Loaded cog: {ext}")
                loaded += 1
            except Exception as exc:
                logging.error(f"Failed to load cog {folder_name}/{fname}: {exc}")
                failed += 1
    logging.info(f"Cogs loaded: {loaded}, failed: {failed}")


async def main():
    async with bot:
        await load_cogs()
        await bot.start(TOKEN)


asyncio.run(main())
'''

_LOCAL_MEMBER_SYNC_PY = '''\
import discord
from discord.ext import commands
import aiohttp, json, os, logging

log = logging.getLogger(__name__)

def _load_cfg():
    p = os.path.join(os.path.dirname(__file__), "..", "..", "config.json")
    try:
        with open(os.path.normpath(p), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

class MemberSync(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        cfg = _load_cfg()
        self.api_url   = cfg.get("api_url", "")
        self.api_token = cfg.get("api_token", "")
        self.server_id = cfg.get("server_id", "")
        self.bot_id    = cfg.get("bot_id", "")

    async def _push(self, members):
        if not self.api_url or not self.api_token:
            return
        payload = [
            {
                "discord_id":   str(m.id),
                "username":     str(m),
                "display_name": m.display_name,
                "roles":        [r.name for r in m.roles if r.name != "@everyone"],
                "joined_at":    m.joined_at.isoformat() if m.joined_at else None,
                "bot":          m.bot,
            }
            for m in members
        ]
        try:
            async with aiohttp.ClientSession() as s:
                await s.post(
                    f"{self.api_url}/api/local-bot/members",
                    json={"server_id": self.server_id, "bot_id": self.bot_id, "members": payload},
                    headers={"X-Bot-Token": self.api_token},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
        except Exception as e:
            log.warning(f"MemberSync push failed: {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            await self._push(guild.members)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        await self._push(guild.members)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        await self._push(guild.members)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            await self._push(after.guild.members)


async def setup(bot):
    await bot.add_cog(MemberSync(bot))
'''

_LOCAL_REQUIREMENTS = "discord.py>=2.3.0\naiohttp>=3.8.0\n"


# ── Bot Manager (local GUI app bundled in the ZIP) ───────────────────────────
# ── Bot Manager (local GUI app bundled in the ZIP) ───────────────────────────
_BOT_MANAGER_PY = r'''#!/usr/bin/env python3
"""
Discord Bot Manager – local web interface.
Run:  python bot_manager.py [--debug]
Then open: http://127.0.0.1:5001  (opens automatically)
"""
import sys, os, json, re, subprocess, threading, time, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
import urllib.parse

PORT     = 5001
BASE_DIR = Path(__file__).parent.resolve()
REQS     = BASE_DIR / 'requirements.txt'
SETUP_F  = BASE_DIR / '.setup_done'
DEBUG    = '--debug' in sys.argv
_server  = None   # set in __main__, used by /api/shutdown

def _dlog(msg):
    if DEBUG:
        print(f'[DBG] {msg}', flush=True)


# ── Bot process ───────────────────────────────────────────────────────────────
class BotProcess:
    def __init__(self, name, config_path):
        self.name        = name
        self.config_path = config_path
        self.process     = None
        self.log_lines   = []
        self.lock        = threading.Lock()
        self.status      = 'stopped'
        self.started_at  = None
        self._log_th     = None

    def _is_alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self._is_alive():
            return False, 'Already running'
        bot_py = BASE_DIR / 'bot.py'
        if not bot_py.exists():
            return False, 'bot.py not found'
        env = {**os.environ, 'BOT_CONFIG': str(self.config_path)}
        try:
            self.process = subprocess.Popen(
                [sys.executable, str(bot_py)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=str(BASE_DIR), env=env,
            )
            self.status     = 'starting'
            self.started_at = time.time()
            self._log_th    = threading.Thread(target=self._read_output, daemon=True)
            self._log_th.start()
            return True, 'Started'
        except Exception as e:
            self.status = 'error'
            return False, str(e)

    def _read_output(self):
        try:
            for raw in self.process.stdout:
                line = raw.rstrip()
                with self.lock:
                    self.log_lines.append(line)
                    if len(self.log_lines) > 600:
                        self.log_lines = self.log_lines[-600:]
                low = line.lower()
                if 'logged in as' in low or 'ready' in low:
                    self.status = 'running'
                elif 'error' in low and self.status == 'starting':
                    self.status = 'error'
        except Exception:
            pass
        self.process.wait()
        if self.status not in ('stopped',):
            self.status = 'stopped'

    def stop(self):
        if not self._is_alive():
            self.status = 'stopped'
            return False, 'Not running'
        try:
            self.process.terminate()
            try: self.process.wait(timeout=6)
            except subprocess.TimeoutExpired: self.process.kill()
            self.status = 'stopped'
            return True, 'Stopped'
        except Exception as e:
            return False, str(e)

    def uptime_str(self):
        if not self._is_alive() or not self.started_at:
            return None
        s = int(time.time() - self.started_at)
        h, m, ss = s // 3600, (s % 3600) // 60, s % 60
        return (f'{h}h {m}m' if h else f'{m}m {ss}s' if m else f'{ss}s')

    def info(self):
        alive = self._is_alive()
        if not alive and self.status not in ('stopped', 'error'):
            self.status = 'stopped'
        with self.lock:
            logs = list(self.log_lines[-200:])
        return {
            'name':   self.name,
            'config': os.path.basename(self.config_path),
            'status': self.status,
            'pid':    self.process.pid if alive else None,
            'uptime': self.uptime_str(),
            'logs':   logs,
        }


# ── Registry ──────────────────────────────────────────────────────────────────
_bots: dict = {}
_bots_lock   = threading.Lock()

def _discover():
    found = sorted(BASE_DIR.glob('config*.json'))
    _dlog(f'_discover: {BASE_DIR}  →  {len(found)} config(s): {[f.name for f in found]}')
    for cfg in found:
        try:
            data = json.loads(cfg.read_text(encoding='utf-8'))
        except Exception as e:
            _dlog(f'  skip {cfg.name}: {e}')
            continue
        stem = cfg.stem
        raw  = stem[len('config'):].lstrip('_') or 'main'
        name = data.get('bot_name', raw)
        with _bots_lock:
            if name not in _bots:
                _dlog(f'  registered "{name}" from {cfg.name}')
                _bots[name] = BotProcess(name, str(cfg))


# ── Script variable editor ────────────────────────────────────────────────────
_VAR_RE = re.compile(
    r'^([A-Z][A-Z0-9_]+)\s*=\s*'
    r'(True|False|-?\d+(?:\.\d+)?|"[^"]*"|\'[^\']*\')'
    r'\s*(?:#.*)?$'
)

def _read_all_vars():
    """Return {script_name: [{key, type, value}, ...]} for all cogs/*/variables.py."""
    cogs_dir = BASE_DIR / 'cogs'
    if not cogs_dir.is_dir():
        return {}
    result = {}
    for folder in sorted(cogs_dir.iterdir()):
        if not folder.is_dir() or folder.name.startswith('_'):
            continue
        vf = folder / 'variables.py'
        if not vf.exists():
            continue
        entries = []
        for line in vf.read_text(encoding='utf-8', errors='replace').splitlines():
            m = _VAR_RE.match(line)
            if not m:
                continue
            key, raw = m.group(1), m.group(2)
            if raw in ('True', 'False'):
                typ, val = 'bool', raw == 'True'
            elif '.' in raw and not raw.startswith('"') and not raw.startswith("'"):
                typ, val = 'float', float(raw)
            elif raw.lstrip('-').isdigit():
                typ, val = 'int', int(raw)
            else:
                typ, val = 'str', raw[1:-1]
            entries.append({'key': key, 'type': typ, 'value': val})
        if entries:
            result[folder.name] = entries
    return result

def _write_vars(script_name, updates):
    """Write updated variable values back to cogs/<script>/variables.py."""
    vf = BASE_DIR / 'cogs' / script_name / 'variables.py'
    if not vf.exists():
        return False, f'variables.py not found for {script_name}'
    lines = vf.read_text(encoding='utf-8', errors='replace').splitlines()
    changed = 0
    for i, line in enumerate(lines):
        m = _VAR_RE.match(line)
        if not m:
            continue
        key, old_raw = m.group(1), m.group(2)
        if key not in updates:
            continue
        new_v = updates[key]
        if old_raw in ('True', 'False'):
            new_raw = 'True' if str(new_v).lower() in ('true', '1', 'yes') else 'False'
        elif old_raw.startswith('"'):
            new_raw = f'"{new_v}"'
        elif old_raw.startswith("'"):
            new_raw = f"'{new_v}'"
        else:
            new_raw = str(new_v)
        indent = line[:len(line) - len(line.lstrip())]
        cmt = re.search(r'\s*#.*$', line)
        lines[i] = f'{indent}{key} = {new_raw}' + (cmt.group(0) if cmt else '')
        changed += 1
    vf.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return True, f'Updated {changed} variable(s)'


# ── Prerequisites ─────────────────────────────────────────────────────────────
_prereq_lines   = []
_prereq_lock    = threading.Lock()
_prereq_running = False
_prereq_done    = SETUP_F.exists()

def _plog(line):
    with _prereq_lock:
        _prereq_lines.append(line)

def _run_prereq():
    global _prereq_running, _prereq_done
    _prereq_running = True
    _plog(f'Python {sys.version}')
    if sys.version_info < (3, 8):
        _plog('ERROR: Python 3.8+ required.')
        _prereq_running = False; return
    _plog(f'✓ Python {sys.version_info.major}.{sys.version_info.minor}')

    r = subprocess.run([sys.executable, '-m', 'pip', '--version'],
                       capture_output=True, text=True)
    if r.returncode != 0:
        _plog('ERROR: pip not available.')
        _prereq_running = False; return
    _plog(f'✓ pip {r.stdout.split()[1]}')

    if REQS.exists():
        _plog('')
        _plog('Installing dependencies…')
        proc = subprocess.Popen(
            [sys.executable, '-m', 'pip', 'install', '-r', str(REQS),
             '--disable-pip-version-check'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        for line in proc.stdout:
            _plog(line.rstrip())
        proc.wait()
        if proc.returncode != 0:
            _plog('ERROR: install failed.')
            _prereq_running = False; return
        _plog('✓ All dependencies installed.')
    else:
        _plog('WARNING: requirements.txt not found — skipping.')

    _plog('')
    _plog('DONE')
    SETUP_F.touch()
    _prereq_done    = True
    _prereq_running = False


# ── HTTP helpers ──────────────────────────────────────────────────────────────
def _json_resp(handler, code, data):
    body = json.dumps(data).encode()
    handler.send_response(code)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.end_headers()
    handler.wfile.write(body)

def _html_resp(handler):
    body = _HTML.encode('utf-8')
    handler.send_response(200)
    handler.send_header('Content-Type', 'text/html; charset=utf-8')
    handler.send_header('Content-Length', str(len(body)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(body)


# ── HTTP handler ──────────────────────────────────────────────────────────────
class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if DEBUG:
            print(f'[HTTP] {self.address_string()} {fmt % args}', flush=True)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET,POST,OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path in ('/', '/index.html'):
            _html_resp(self); return

        if path == '/api/status':
            _discover()
            with _bots_lock:
                infos = [b.info() for b in _bots.values()]
            _json_resp(self, 200, {
                'bots': infos,
                'setup_done': _prereq_done,
                'setup_running': _prereq_running,
            }); return

        if path == '/api/prereq/log':
            with _prereq_lock:
                lines = list(_prereq_lines)
            _json_resp(self, 200, {
                'lines':   lines,
                'running': _prereq_running,
                'done':    _prereq_done,
            }); return

        if path == '/api/debug':
            configs = [str(f.name) for f in sorted(BASE_DIR.glob('config*.json'))]
            with _bots_lock:
                snap = {n: {'status': b.status, 'config': os.path.basename(b.config_path)}
                        for n, b in _bots.items()}
            _json_resp(self, 200, {
                'base_dir': str(BASE_DIR), 'setup_done': _prereq_done,
                'config_files': configs, 'bots': snap,
                'python': sys.version, 'debug': DEBUG,
            }); return

        parts = path.strip('/').split('/')

        if len(parts) == 4 and parts[:2] == ['api', 'bot'] and parts[3] == 'log':
            name = urllib.parse.unquote(parts[2])
            with _bots_lock:
                bot = _bots.get(name)
            if not bot:
                _json_resp(self, 404, {'error': 'Not found'}); return
            with bot.lock:
                logs = list(bot.log_lines[-300:])
            _json_resp(self, 200, {'logs': logs}); return

        if len(parts) == 4 and parts[:2] == ['api', 'bot'] and parts[3] == 'stream':
            name = urllib.parse.unquote(parts[2])
            with _bots_lock:
                bot = _bots.get(name)
            if not bot:
                _json_resp(self, 404, {'error': 'Not found'}); return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            sent = 0
            try:
                while True:
                    with bot.lock:
                        chunk = bot.log_lines[sent:]
                    for line in chunk:
                        self.wfile.write(f'data: {line}\n\n'.encode())
                        sent += 1
                    if chunk:
                        self.wfile.flush()
                    time.sleep(0.4)
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return

        if len(parts) == 4 and parts[:2] == ['api', 'bot'] and parts[3] == 'vars':
            _json_resp(self, 200, {'scripts': _read_all_vars()}); return

        _json_resp(self, 404, {'error': 'Not found'})

    def do_POST(self):
        path   = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        if path == '/api/shutdown':
            _json_resp(self, 200, {'ok': True})
            def _do_shutdown():
                time.sleep(0.5)
                print('\nShutting down (user request)...', flush=True)
                if _server:
                    _server.shutdown()
            threading.Thread(target=_do_shutdown, daemon=True).start()
            return

        if path == '/api/prereq/install':
            global _prereq_running
            if _prereq_running:
                _json_resp(self, 409, {'error': 'Already running'}); return
            with _prereq_lock:
                _prereq_lines.clear()
            threading.Thread(target=_run_prereq, daemon=True).start()
            _json_resp(self, 200, {'started': True}); return

        if path == '/api/upload-config':
            try:
                data = json.loads(body)
                if 'bot_token' not in data or 'bot_name' not in data:
                    _json_resp(self, 400, {'error': 'Missing bot_token or bot_name'}); return
                name = data['bot_name']
                safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in name)
                cfg_path = BASE_DIR / f'config_{safe}.json'
                cfg_path.write_text(json.dumps(data, indent=2), encoding='utf-8')
                _discover()
                _json_resp(self, 200, {'ok': True, 'name': name}); return
            except Exception as e:
                _json_resp(self, 400, {'error': str(e)}); return

        parts = path.strip('/').split('/')

        if len(parts) == 4 and parts[:2] == ['api', 'bot'] and parts[3] == 'vars':
            try:
                data    = json.loads(body)
                ok, msg = _write_vars(data.get('script', ''), data.get('updates', {}))
                _json_resp(self, 200 if ok else 400, {'ok': ok, 'msg': msg}); return
            except Exception as e:
                _json_resp(self, 400, {'error': str(e)}); return

        if len(parts) == 4 and parts[:2] == ['api', 'bot']:
            name   = urllib.parse.unquote(parts[2])
            action = parts[3]
            with _bots_lock:
                bot = _bots.get(name)
            if not bot:
                _json_resp(self, 404, {'error': 'Not found'}); return
            if action == 'start':
                ok, msg = bot.start()
            elif action == 'stop':
                ok, msg = bot.stop()
            elif action == 'restart':
                bot.stop(); time.sleep(0.8); ok, msg = bot.start()
            else:
                _json_resp(self, 400, {'error': 'Unknown action'}); return
            _json_resp(self, 200, {'ok': ok, 'msg': msg, 'info': bot.info()}); return

        _json_resp(self, 404, {'error': 'Not found'})


class _ThreadingServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


# ── Embedded UI ───────────────────────────────────────────────────────────────
_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Discord Bot Manager</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#1e2124;color:#dcddde;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;flex-direction:column}

/* Nav */
.nav{background:#2f3136;height:54px;display:flex;align-items:center;padding:0 24px;box-shadow:0 2px 8px rgba(0,0,0,.4);flex-shrink:0;gap:10px}
.nav-brand{font-size:1.1em;font-weight:700;color:#7289da;white-space:nowrap}
.nav-sub{font-size:12px;color:#72767d;flex:1;margin-left:4px}
.btn-off{background:rgba(240,71,71,.12);color:#f04747;border:1px solid rgba(240,71,71,.28);border-radius:5px;padding:6px 13px;font-size:12px;font-weight:600;cursor:pointer;transition:background .15s;white-space:nowrap}
.btn-off:hover{background:rgba(240,71,71,.28)}

/* Page */
.page{flex:1;padding:28px 24px 48px;max-width:980px;width:100%;margin:0 auto}

/* Buttons */
.btn{display:inline-flex;align-items:center;gap:6px;border:none;border-radius:5px;padding:8px 16px;font-size:13px;font-weight:600;cursor:pointer;transition:background .15s,transform .1s;white-space:nowrap}
.btn:active:not(:disabled){transform:scale(.97)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn-green{background:#43b581;color:#fff}.btn-green:hover:not(:disabled){background:#3ca374}
.btn-red{background:#f04747;color:#fff}.btn-red:hover:not(:disabled){background:#d84040}
.btn-blue{background:#7289da;color:#fff}.btn-blue:hover:not(:disabled){background:#5b6eae}
.btn-ghost{background:transparent;color:#b9bbbe;border:1px solid #40444b}.btn-ghost:hover:not(:disabled){background:#40444b;color:#fff}
.btn-sm{padding:6px 12px;font-size:12px}
.btn-full{width:100%;justify-content:center}

/* Badges */
.badge{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:10px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.4px}
.badge-running{background:rgba(67,181,129,.15);color:#43b581}
.badge-starting{background:rgba(250,166,26,.15);color:#faa61a}
.badge-stopped{background:rgba(79,84,92,.3);color:#72767d}
.badge-error{background:rgba(240,71,71,.15);color:#f04747}

/* Bot grid */
.bot-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.bot-card{background:#2f3136;border-radius:8px;border:1px solid #40444b;overflow:hidden;transition:border-color .15s}
.bot-card:hover{border-color:#7289da}
.bc-top{padding:18px 20px 14px;display:flex;align-items:center;gap:14px}
.bot-avatar{width:46px;height:46px;border-radius:50%;background:#7289da;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:700;color:#fff;flex-shrink:0}
.bot-name{font-size:1em;font-weight:700;color:#fff}
.bot-cfg{font-size:11px;color:#72767d;margin-top:2px;font-family:monospace}
.bot-uptime{font-size:11px;color:#72767d;margin-top:3px}
.bc-actions{padding:0 20px 14px;display:flex;gap:8px;flex-wrap:wrap}
.bc-log-hdr{border-top:1px solid #40444b}
.log-toggle{width:100%;background:none;border:none;color:#72767d;font-size:12px;cursor:pointer;padding:10px 16px;display:flex;align-items:center;gap:6px;font-weight:600;text-transform:uppercase;letter-spacing:.4px;transition:color .15s,background .15s}
.log-toggle:hover{color:#dcddde;background:rgba(255,255,255,.03)}
.log-box{display:none;background:#202225;padding:10px 14px;font-family:monospace;font-size:11px;line-height:1.7;max-height:220px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;color:#b9bbbe}
.log-box.open{display:block}
.lok{color:#43b581}.lwarn{color:#faa61a}.lerr{color:#f04747}

/* Wizard */
.wizard{background:#2f3136;border-radius:10px;padding:36px 40px;max-width:580px;margin:40px auto;border:1px solid #40444b}
.wiz-icon{font-size:52px;text-align:center;margin-bottom:16px}
.wiz-title{text-align:center;font-size:1.45em;font-weight:700;color:#fff;margin-bottom:8px}
.wiz-sub{text-align:center;color:#72767d;font-size:14px;margin-bottom:24px;line-height:1.6}
.wiz-steps{display:flex;margin-bottom:22px;border-radius:6px;overflow:hidden;border:1px solid #40444b}
.wstep{flex:1;padding:9px 6px;text-align:center;font-size:12px;font-weight:600;color:#72767d;background:#36393f;border-right:1px solid #40444b;transition:all .2s}
.wstep:last-child{border-right:none}
.wstep.active{background:rgba(114,137,218,.15);color:#7289da}
.wstep.done{background:rgba(67,181,129,.1);color:#43b581}
.wiz-log{background:#202225;border-radius:6px;padding:12px 14px;font-family:monospace;font-size:12px;line-height:1.7;max-height:240px;overflow-y:auto;margin-bottom:20px;color:#b9bbbe;display:none}
.wiz-log.show{display:block}

/* Drop zone */
.drop-zone{border:2px dashed #40444b;border-radius:8px;padding:15px 24px;margin-bottom:20px;text-align:center;color:#72767d;font-size:13px;cursor:pointer;transition:border-color .2s,background .2s}
.drop-zone.over{border-color:#7289da;background:rgba(114,137,218,.07)}

/* Dashboard header */
.dash-hdr{display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:20px;flex-wrap:wrap;gap:12px}
.dash-title{font-size:1.2em;font-weight:700;color:#fff}
.dash-hint{color:#72767d;font-size:13px;margin-top:2px}

/* Empty */
.empty{text-align:center;padding:60px 20px;color:#72767d}
.empty-icon{font-size:48px;margin-bottom:14px}

/* Spinner */
@keyframes spin{to{transform:rotate(360deg)}}
.spin{display:inline-block;border-style:solid;border-color:rgba(255,255,255,.15);border-top-color:#7289da;border-radius:50%;animation:spin .8s linear infinite}

/* Toast */
#toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:10px 22px;border-radius:6px;font-weight:600;font-size:14px;box-shadow:0 4px 16px rgba(0,0,0,.4);z-index:9999;transition:opacity .4s;opacity:0;pointer-events:none;color:#fff}

/* Footer */
footer{background:#2f3136;border-top:1px solid #40444b;padding:10px 28px;text-align:center;color:#72767d;font-size:12px;flex-shrink:0}

/* ── Vars modal ─────────────────────────────────────────────────────────── */
.modal-ov{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:500;display:flex;align-items:center;justify-content:center;padding:20px}
.modal{background:#2f3136;border-radius:12px;border:1px solid #40444b;width:100%;max-width:660px;max-height:86vh;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.55)}
.modal-hdr{display:flex;align-items:center;gap:10px;padding:18px 22px;border-bottom:1px solid #40444b;flex-shrink:0}
.modal-hdr-ico{font-size:20px;line-height:1}
.modal-title{font-weight:700;color:#fff;font-size:1.05em;flex:1}
.modal-body{overflow-y:auto;padding:18px 22px;flex:1}
.modal-ftr{padding:14px 22px;border-top:1px solid #40444b;display:flex;gap:8px;justify-content:flex-end;flex-shrink:0;background:#292b2f;border-radius:0 0 12px 12px}
/* Script section */
.vs-sec{margin-bottom:20px}
.vs-sec:last-child{margin-bottom:4px}
.vs-sec-hdr{display:flex;align-items:center;gap:10px;padding:9px 14px;background:rgba(114,137,218,.08);border-radius:8px;border-left:3px solid #7289da;margin-bottom:8px}
.vs-sec-name{font-size:13px;font-weight:700;color:#fff}
.vs-sec-count{font-size:11px;color:#72767d;margin-left:auto;font-style:italic}
/* Variable rows */
.vs-row{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:14px;padding:8px 10px;border-radius:6px;transition:background .1s}
.vs-row:hover{background:rgba(255,255,255,.025)}
.vs-lbl{font-size:13px;color:#dcddde;font-weight:500;line-height:1.3}
.vs-raw{font-size:10px;font-family:monospace;color:#4f545c;margin-top:1px}
.vs-badge{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px;letter-spacing:.3px;text-transform:uppercase;flex-shrink:0;white-space:nowrap}
.vs-badge-int{background:rgba(88,101,242,.2);color:#8b9cf7}
.vs-badge-float{background:rgba(114,137,218,.15);color:#99aab5}
.vs-badge-str{background:rgba(67,181,129,.15);color:#43b581}
.vs-badge-bool{background:rgba(250,166,26,.15);color:#faa61a}
.vs-inp{background:#202225;border:1px solid #40444b;border-radius:6px;color:#dcddde;font-size:13px;padding:6px 10px;width:165px;transition:border-color .15s,background .15s}
.vs-inp:focus{outline:none;border-color:#7289da;background:#1a1d21}
/* Toggle switch for booleans */
.vs-tog{position:relative;width:42px;height:24px;flex-shrink:0}
.vs-tog input{opacity:0;width:0;height:0;position:absolute}
.vs-track{position:absolute;inset:0;background:#40444b;border-radius:12px;cursor:pointer;transition:background .2s}
.vs-track::before{content:'';position:absolute;width:18px;height:18px;left:3px;top:3px;background:#fff;border-radius:50%;transition:transform .2s;box-shadow:0 1px 3px rgba(0,0,0,.3)}
.vs-tog input:checked + .vs-track{background:#43b581}
.vs-tog input:checked + .vs-track::before{transform:translateX(18px)}
.vs-empty{text-align:center;padding:40px 20px;color:#72767d}
.vs-empty-ico{font-size:36px;margin-bottom:10px}
</style>
</head>
<body>

<nav class="nav">
  <span class="nav-brand">🤖 Discord Bot Manager</span>
  <span class="nav-sub" id="navSub"></span>
  <button class="btn-off" onclick="doShutdown()">⏹ Shutdown</button>
</nav>

<div class="page" id="app">
  <div class="empty"><div class="spin" style="width:28px;height:28px;border-width:3px"></div></div>
</div>

<div id="toast"></div>

<div id="varsModal" style="display:none" class="modal-ov" onclick="if(event.target===this)closeVars()">
  <div class="modal">
    <div class="modal-hdr">
      <span class="modal-hdr-ico">&#9881;</span>
      <span class="modal-title" id="varsMTitle">Script Variables</span>
      <button class="btn btn-ghost btn-sm" onclick="closeVars()" style="padding:4px 9px;font-size:14px;">&#x2715;</button>
    </div>
    <div class="modal-body" id="varsMBody"></div>
    <div class="modal-ftr">
      <span id="varsSaveMsg" style="font-size:12px;color:#72767d;align-self:center;margin-right:auto;"></span>
      <button class="btn btn-ghost btn-sm" onclick="closeVars()">Cancel</button>
      <button class="btn btn-blue btn-sm" id="varsSaveBtn" onclick="saveVars()">&#128190; Save changes</button>
    </div>
  </div>
</div>

<footer>Discord Bot Manager &mdash; running locally on port 5001</footer>

<script>
window.onerror = function(msg, src, line) {
  var a = document.getElementById('app');
  if (a) a.innerHTML = '<div class="empty"><div class="empty-icon" style="font-size:28px">&#x26A0;</div>'
    + '<div style="color:#f04747;font-weight:700;margin-bottom:6px">JavaScript error</div>'
    + '<div style="font-size:12px;font-family:monospace;color:#b9bbbe">' + String(msg) + ' (line ' + line + ')</div></div>';
  return false;
};
window.onunhandledrejection = function(e) {
  var msg = (e.reason && e.reason.message) ? e.reason.message : String(e.reason);
  var a = document.getElementById('app');
  if (a && a.innerHTML.indexOf('spin') !== -1)
    a.innerHTML = '<div class="empty"><div class="empty-icon" style="font-size:28px">&#x26A0;</div>'
      + '<div style="color:#f04747;font-weight:700;margin-bottom:6px">Async error</div>'
      + '<div style="font-size:12px;font-family:monospace;color:#b9bbbe">' + String(msg) + '</div></div>';
};

var _logOpen  = {};
var _sseConns = {};
var _pollTid  = null;

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function colorLine(l) {
  var lo = l.toLowerCase();
  var cls = /error|exception|traceback|failed|fatal/.test(lo) ? 'lerr'
          : /warn(?:ing)?/.test(lo) ? 'lwarn'
          : /logged in|ready|loaded|started|success/.test(lo) ? 'lok' : '';
  return cls ? '<span class="' + cls + '">' + esc(l) + '</span>' : esc(l);
}

async function api(method, path, body) {
  var opts = { method: method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined && body !== null) opts.body = JSON.stringify(body);
  var ctrl = new AbortController();
  var tid  = setTimeout(function() { ctrl.abort(); }, 8000);
  try {
    var r = await fetch(path, Object.assign(opts, { signal: ctrl.signal }));
    clearTimeout(tid);
    return r.json();
  } catch(e) { clearTimeout(tid); throw e; }
}

function toast(msg, bg) {
  var t = document.getElementById('toast');
  if (!t) return;
  t.textContent = msg;
  t.style.background = bg || '#43b581';
  t.style.opacity = '1';
  clearTimeout(t._tid);
  t._tid = setTimeout(function() { t.style.opacity = '0'; }, 3000);
}

// ── Shutdown ──────────────────────────────────────────────────────────────────
async function doShutdown() {
  if (!confirm('Stop the Bot Manager?\n\nRunning bots will also be stopped.')) return;
  try { await api('POST', '/api/shutdown'); } catch(e) {}
  clearInterval(_pollTid);
  Object.keys(_sseConns).forEach(function(n) { _sseConns[n].close(); });
  document.getElementById('app').innerHTML =
    '<div class="empty"><div class="empty-icon">✅</div>'
    + '<div style="font-size:1.1em;font-weight:700;color:#fff;margin-bottom:8px">Bot Manager stopped</div>'
    + '<div>You can close this tab.</div></div>';
  var ns = document.getElementById('navSub');
  if (ns) ns.textContent = 'offline';
}

// ── Polling ───────────────────────────────────────────────────────────────────
async function poll() {
  try {
    var d = await api('GET', '/api/status');
    var ns = document.getElementById('navSub');
    if (!d.setup_done) {
      if (ns) ns.textContent = 'Setup required';
      renderWizard();
    } else {
      var nb = d.bots.length;
      if (ns) ns.textContent = nb + ' bot' + (nb !== 1 ? 's' : '') + ' configured';
      renderDash(d.bots);
    }
  } catch(e) {
    var a = document.getElementById('app');
    if (a) a.innerHTML = '<div class="empty"><div class="empty-icon">&#x26A0;</div>'
      + '<div style="font-weight:700;color:#fff;margin-bottom:8px">Cannot reach bot manager</div>'
      + '<div>Is it still running?</div>'
      + '<div style="font-size:12px;color:#72767d;margin-top:8px">' + esc(String(e)) + '</div></div>';
  }
}

function startPoll() {
  if (_pollTid) clearInterval(_pollTid);
  _pollTid = setInterval(poll, 2500);
}

// ── Wizard ────────────────────────────────────────────────────────────────────
function renderWizard() {
  if (document.getElementById('wizCard')) return;
  document.getElementById('app').innerHTML =
    '<div class="wizard" id="wizCard">'
    + '<div class="wiz-icon">🤖</div>'
    + '<div class="wiz-title">First-time Setup</div>'
    + '<div class="wiz-sub">We\'ll check Python and install your bot\'s dependencies.<br>This only runs once.</div>'
    + '<div class="wiz-steps">'
    + '<div class="wstep active" id="ws0">1. Python</div>'
    + '<div class="wstep" id="ws1">2. Dependencies</div>'
    + '<div class="wstep" id="ws2">3. Ready!</div>'
    + '</div>'
    + '<div class="wiz-log" id="wizLog"></div>'
    + '<div id="wizAct"><button class="btn btn-blue btn-full" onclick="startSetup()">&#9654; Check &amp; Install</button></div>'
    + '</div>';
}

async function startSetup() {
  document.getElementById('wizAct').innerHTML =
    '<button class="btn btn-blue btn-full" disabled>'
    + '<span class="spin" style="width:13px;height:13px;border-width:2px"></span> Running…</button>';
  var lb = document.getElementById('wizLog');
  if (lb) lb.classList.add('show');
  document.getElementById('ws0').className = 'wstep active';
  try { await api('POST', '/api/prereq/install'); } catch(e) {}
  pollPrereq();
}

function pollPrereq() {
  var t = setInterval(async function() {
    try {
      var d = await api('GET', '/api/prereq/log');
      var lb = document.getElementById('wizLog');
      if (!lb) { clearInterval(t); return; }
      var txt = d.lines.join('\n');
      var isDeps = /installing dep|collecting|requirement/i.test(txt);
      var isDone = d.lines.some(function(l) { return l.trim() === 'DONE'; });
      document.getElementById('ws0').className = 'wstep done';
      if (isDeps) document.getElementById('ws1').className = 'wstep active';
      if (isDone) {
        document.getElementById('ws1').className = 'wstep done';
        document.getElementById('ws2').className = 'wstep done';
      }
      lb.innerHTML = d.lines.map(function(l) {
        if (l.startsWith('ERROR')) return '<span class="lerr">' + esc(l) + '</span>';
        if (l.startsWith('✓') || l === 'DONE') return '<span class="lok">' + esc(l) + '</span>';
        return esc(l);
      }).join('<br>');
      lb.scrollTop = lb.scrollHeight;
      if (!d.running) {
        clearInterval(t);
        if (isDone) {
          document.getElementById('wizAct').innerHTML =
            '<button class="btn btn-green btn-full" onclick="location.reload()">&#x2705; Done &#8212; Open Dashboard</button>';
        } else {
          document.getElementById('wizAct').innerHTML =
            '<button class="btn btn-red btn-full" onclick="startSetup()">&#x21BA; Retry</button>';
        }
      }
    } catch(e) {}
  }, 700);
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function renderDash(bots) {
  var app = document.getElementById('app');

  if (!document.getElementById('dashHdr')) {
    app.innerHTML =
      '<div class="dash-hdr" id="dashHdr">'
      + '<div><div class="dash-title">Your Bots</div>'
      + '<div class="dash-hint">Start a bot below, or drop a config file to add one.</div></div>'
      + '</div>'
      + '<div class="drop-zone" id="dz"'
      + ' ondragover="event.preventDefault();this.classList.add(\'over\')"'
      + ' ondragleave="this.classList.remove(\'over\')"'
      + ' ondrop="handleDrop(event)">'
      + '&#xFF0B; Drop a <code style="background:#40444b;padding:1px 5px;border-radius:3px">config_xxx.json</code> here'
      + ' &nbsp;&middot;&nbsp; or <label style="color:#7289da;cursor:pointer">browse'
      + '<input type="file" accept=".json" style="display:none" onchange="handleFile(this.files[0])"></label>'
      + '</div>'
      + '<div class="bot-grid" id="botGrid"></div>';
  }

  var grid = document.getElementById('botGrid');
  if (!grid) return;

  if (bots.length === 0) {
    grid.innerHTML = '<div class="empty" style="grid-column:1/-1">'
      + '<div class="empty-icon">🤖</div>'
      + '<div>No bots yet — drop a config file above to add one.</div></div>';
    return;
  }

  bots.forEach(function(bot) {
    var cid = 'bc_' + bot.name.replace(/[^a-z0-9]/gi, '_');
    var st  = bot.status || 'stopped';
    var bdg = {running:'badge-running',starting:'badge-starting',stopped:'badge-stopped',error:'badge-error'}[st] || 'badge-stopped';
    var lbl = {running:'&#9679; Running',starting:'&#9681; Starting&#8230;',stopped:'&#9675; Stopped',error:'&#10005; Error'}[st] || '&#9675; Stopped';
    var ini = esc((bot.name[0] || 'B').toUpperCase());
    var upt = bot.uptime ? '<div class="bot-uptime">Up ' + esc(bot.uptime) + '</div>' : '';
    var sDis = (st === 'running' || st === 'starting') ? 'disabled' : '';
    var pDis = (st === 'stopped' || st === 'error')    ? 'disabled' : '';
    var cnt  = bot.logs ? bot.logs.length : 0;
    var cntLbl = cnt ? ' <span style="color:#72767d;font-weight:400;text-transform:none;margin-left:4px">(' + cnt + ' lines)</span>' : '';
    var isOpen = _logOpen[bot.name];
    var sn = esc(bot.name);

    var el = document.getElementById(cid);
    if (!el) {
      el = document.createElement('div');
      el.className = 'bot-card';
      el.id = cid;
      grid.appendChild(el);
    }

    el.innerHTML =
      '<div class="bc-top">'
      + '<div class="bot-avatar">' + ini + '</div>'
      + '<div style="flex:1;min-width:0">'
      + '<div class="bot-name">' + sn + '</div>'
      + '<div class="bot-cfg">' + esc(bot.config) + '</div>'
      + '<div style="margin-top:5px"><span class="badge ' + bdg + '">' + lbl + '</span></div>'
      + upt
      + '</div></div>'
      + '<div class="bc-actions">'
      + '<button class="btn btn-green btn-sm" onclick="botAction(\'' + sn + '\',\'start\')" ' + sDis + '>&#9654; Start</button>'
      + '<button class="btn btn-red btn-sm"   onclick="botAction(\'' + sn + '\',\'stop\')"  ' + pDis + '>&#9209; Stop</button>'
      + '<button class="btn btn-ghost btn-sm" onclick="botAction(\'' + sn + '\',\'restart\')">&#x21BA; Restart</button>'
      + '<button class="btn btn-ghost btn-sm" onclick="openVars(\'' + sn + '\')">&#9881; Vars</button>'
      + '</div>'
      + '<div class="bc-log-hdr">'
      + '<button class="log-toggle" onclick="toggleLog(\'' + sn + '\')">'
      + '<span id="larr_' + sn + '">' + (isOpen ? '&#9660;' : '&#9658;') + '</span> Logs' + cntLbl
      + '</button>'
      + '<div class="log-box' + (isOpen ? ' open' : '') + '" id="lbox_' + sn + '">'
      + (cnt ? bot.logs.map(colorLine).join('<br>') : '<span style="color:#72767d;font-style:italic">No output yet.</span>')
      + '</div></div>';

    if (isOpen) {
      var lb = document.getElementById('lbox_' + bot.name);
      if (lb) lb.scrollTop = lb.scrollHeight;
    }
    if (st === 'running'  && !_sseConns[bot.name]) startSSE(bot.name);
    if (st !== 'running'  &&  _sseConns[bot.name]) { _sseConns[bot.name].close(); delete _sseConns[bot.name]; }
  });
}

function toggleLog(name) {
  _logOpen[name] = !_logOpen[name];
  var lb  = document.getElementById('lbox_' + name);
  var arr = document.getElementById('larr_' + name);
  if (lb)  { lb.classList.toggle('open', _logOpen[name]); if (_logOpen[name]) lb.scrollTop = lb.scrollHeight; }
  if (arr) arr.innerHTML = _logOpen[name] ? '&#9660;' : '&#9658;';
}

function startSSE(name) {
  if (_sseConns[name]) return;
  var es = new EventSource('/api/bot/' + encodeURIComponent(name) + '/stream');
  es.onmessage = function(ev) {
    var lb = document.getElementById('lbox_' + name);
    if (!lb) return;
    var br = document.createElement('br');
    var sp = document.createElement('span');
    sp.innerHTML = colorLine(ev.data);
    lb.appendChild(br);
    lb.appendChild(sp);
    if (_logOpen[name]) lb.scrollTop = lb.scrollHeight;
  };
  es.onerror = function() { es.close(); delete _sseConns[name]; };
  _sseConns[name] = es;
}

async function botAction(name, action) {
  var el = document.getElementById('bc_' + name.replace(/[^a-z0-9]/gi, '_'));
  if (el) el.querySelectorAll('button').forEach(function(b) { b.disabled = true; });
  try { await api('POST', '/api/bot/' + encodeURIComponent(name) + '/' + action); }
  catch(e) { toast('Error: ' + e.message, '#f04747'); }
  await poll();
}

// ── Config upload ─────────────────────────────────────────────────────────────
function handleDrop(e) {
  e.preventDefault();
  var dz = document.getElementById('dz');
  if (dz) dz.classList.remove('over');
  if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
}

async function handleFile(file) {
  if (!file || !file.name.endsWith('.json')) { toast('Drop a .json config file', '#f04747'); return; }
  var reader = new FileReader();
  reader.onload = async function(ev) {
    var data;
    try { data = JSON.parse(ev.target.result); }
    catch(e) { toast('Invalid JSON', '#f04747'); return; }
    if (!data.bot_token || !data.bot_name) { toast('Missing bot_token or bot_name', '#f04747'); return; }
    try {
      var r = await api('POST', '/api/upload-config', data);
      if (r.ok) { toast('Added: ' + r.name); await poll(); }
      else toast('Error: ' + (r.error || 'unknown'), '#f04747');
    } catch(e) { toast('Upload failed: ' + e.message, '#f04747'); }
  };
  reader.readAsText(file);
}

// ── Script variable editor ────────────────────────────────────────────────────
var _varsBot = null;

async function openVars(name) {
  _varsBot = name;
  document.getElementById('varsMTitle').textContent = '⚙ Script Variables — ' + name;
  var body = document.getElementById('varsMBody');
  body.innerHTML = '<div style="text-align:center;padding:30px"><div class="spin" style="width:22px;height:22px;border-width:3px;display:inline-block"></div></div>';
  document.getElementById('varsModal').style.display = 'flex';
  try {
    var r = await api('GET', '/api/bot/' + encodeURIComponent(name) + '/vars');
    renderVarsModal(r.scripts || {});
  } catch(e) {
    body.innerHTML = '<div style="color:#f04747;padding:20px">Failed to load: ' + e.message + '</div>';
  }
}

function humanLabel(key) {
  return key.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, function(c) { return c.toUpperCase(); });
}
function typeBadge(t) {
  var cls = {int:'vs-badge-int', float:'vs-badge-float', str:'vs-badge-str', bool:'vs-badge-bool'}[t] || 'vs-badge-str';
  return '<span class="vs-badge ' + cls + '">' + t + '</span>';
}

function renderVarsModal(scripts) {
  var body = document.getElementById('varsMBody');
  var keys = Object.keys(scripts);
  if (!keys.length) {
    body.innerHTML = '<div class="vs-empty"><div class="vs-empty-ico">&#128230;</div><div>No editable variables found.<br><span style="font-size:12px;">Install scripts first via the web app.</span></div></div>';
    return;
  }
  var html = '';
  keys.forEach(function(script) {
    var vars = scripts[script];
    html += '<div class="vs-sec">'
      + '<div class="vs-sec-hdr"><span style="font-size:16px;">&#128230;</span>'
      + '<span class="vs-sec-name">' + esc(script.replace(/_/g,' ')) + '</span>'
      + '<span class="vs-sec-count">' + vars.length + ' variable' + (vars.length !== 1 ? 's' : '') + '</span></div>';
    vars.forEach(function(v) {
      html += '<div class="vs-row"><div class="vs-lbl-wrap"><div class="vs-lbl">' + esc(humanLabel(v.key)) + '</div>'
        + '<div class="vs-raw">' + esc(v.key) + '</div></div>'
        + typeBadge(v.type);
      if (v.type === 'bool') {
        html += '<label class="vs-tog"><input type="checkbox" class="var-inp" data-script="' + esc(script)
          + '" data-key="' + esc(v.key) + '" data-type="bool"' + (v.value ? ' checked' : '') + '>'
          + '<span class="vs-track"></span></label>';
      } else {
        var itype = (v.type === 'int' || v.type === 'float') ? 'number' : 'text';
        html += '<input type="' + itype + '" class="vs-inp var-inp"'
          + ' data-script="' + esc(script) + '" data-key="' + esc(v.key) + '" data-type="' + v.type + '"'
          + (v.type === 'float' ? ' step="any"' : '')
          + ' value="' + esc(String(v.value)) + '">';
      }
      html += '</div>';
    });
    html += '</div>';
  });
  body.innerHTML = html;
}

function closeVars() {
  document.getElementById('varsModal').style.display = 'none';
  _varsBot = null;
}

async function saveVars() {
  if (!_varsBot) return;
  var inputs = document.querySelectorAll('#varsMBody .var-inp');
  var byScript = {};
  inputs.forEach(function(inp) {
    var script = inp.dataset.script, key = inp.dataset.key, type = inp.dataset.type, val;
    if (type === 'bool')        val = inp.checked;
    else if (type === 'int')    val = parseInt(inp.value, 10);
    else if (type === 'float')  val = parseFloat(inp.value);
    else                        val = inp.value;
    if (!byScript[script]) byScript[script] = {};
    byScript[script][key] = val;
  });
  var btn = document.getElementById('varsSaveBtn');
  var msg = document.getElementById('varsSaveMsg');
  btn.disabled = true; btn.innerHTML = '<span class="spin" style="width:12px;height:12px;border-width:2px;display:inline-block;vertical-align:middle;margin-right:6px"></span>Saving…';
  msg.textContent = '';
  var errors = [];
  for (var script of Object.keys(byScript)) {
    try {
      var r = await api('POST', '/api/bot/' + encodeURIComponent(_varsBot) + '/vars',
        {script: script, updates: byScript[script]});
      if (!r.ok) errors.push(script + ': ' + r.msg);
    } catch(e) { errors.push(script + ': ' + e.message); }
  }
  btn.disabled = false; btn.innerHTML = '&#128190; Save changes';
  if (errors.length) {
    msg.style.color = '#f04747';
    msg.textContent = '⚠ ' + errors.join('; ');
  } else {
    toast('Variables saved — restart the bot to apply.');
    closeVars();
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
poll();
startPoll();
</script>
</body>
</html>"""


# ── Entry ─────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'  Discord Bot Manager  (debug={DEBUG})')
    print(f'  Python {sys.version}')
    print(f'  Base dir: {BASE_DIR}')
    print()

    if REQS.exists():
        print(f'  requirements.txt found')
    else:
        print(f'  WARNING: requirements.txt not found at {REQS}')
    print(f'  Setup done (.setup_done exists): {SETUP_F.exists()}')
    print()

    _discover()

    with _bots_lock:
        if _bots:
            print(f'  Found {len(_bots)} bot config(s):')
            for n in _bots:
                print(f'    - {n}  ({_bots[n].config_path})')
        else:
            cfg_files = list(BASE_DIR.glob('config*.json'))
            if cfg_files:
                print(f'  WARNING: found {len(cfg_files)} config file(s) but none loaded')
            else:
                print(f'  No config*.json files found in {BASE_DIR}')
    print()

    try:
        _server = _ThreadingServer(('0.0.0.0', PORT), _Handler)
    except OSError as e:
        print(f'  ERROR: Cannot bind to port {PORT}: {e}')
        print(f'  Is another instance already running?')
        input('\nPress Enter to exit...')
        sys.exit(1)

    print(f'  Running at http://127.0.0.1:{PORT}')
    if DEBUG:
        print(f'  Debug endpoint: http://127.0.0.1:{PORT}/api/debug')
    print(f'  Opening browser...')
    print()

    threading.Thread(target=lambda: (time.sleep(1.2), webbrowser.open(f'http://127.0.0.1:{PORT}')), daemon=True).start()

    try:
        _server.serve_forever()
    except KeyboardInterrupt:
        pass

    print('\nShutting down...')
    with _bots_lock:
        for b in _bots.values():
            if b._is_alive():
                b.stop()
    print('Done.')
'''


def _make_bot_config(server_id, bot_id, config, server):
    """Build the config dict for a local bot and return (bot_config, safe_name)."""
    bot_cfg = _find_bot_by_id(config, bot_id)
    if not bot_cfg:
        return None, None
    bot_name  = bot_cfg['name']
    bot_token = bot_cfg['token']
    safe_name = ''.join(c if c.isalnum() or c in '-_' else '_' for c in bot_name)

    username = session['user_id']
    users = load_users()
    _local_tokens = users.get(username, {}).setdefault('local_bot_tokens', {})
    token_key = f"{server_id}:{bot_id}"
    if token_key not in _local_tokens:
        _local_tokens[token_key] = secrets.token_urlsafe(32)
        save_users(users)
    local_api_token = _local_tokens[token_key]

    config.setdefault('local_bot_tokens', {})[token_key] = local_api_token
    install_dir = server.get('install_dir', '')
    repo_dir    = os.path.join(install_dir, 'discord-server-setup')
    _lbt_config_path = os.path.join(repo_dir, 'config.json')
    if os.path.exists(_lbt_config_path):
        try:
            save_server_config(_lbt_config_path, config)
        except Exception as _e:
            print(f'[WARN] _make_bot_config: failed to save config to {_lbt_config_path}: {_e}')

    bot_config = {
        'bot_token':  bot_token,
        'bot_name':   bot_name,
        'prefix':     '!',
        'server':     config.get('server', {}),
        'server_id':  server_id,
        'bot_id':     bot_id,
        'api_url':    request.host_url.rstrip('/'),
        'api_token':  local_api_token,
    }
    return bot_config, safe_name


@app.route('/api/bots/config-json/<server_id>/<bot_id>')
@login_required
def bot_config_json(server_id, bot_id):
    """Return the bot config as JSON so the browser can push it to a running local manager."""
    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404
    bot_config, _ = _make_bot_config(server_id, bot_id, config, server)
    if bot_config is None:
        return jsonify({'error': 'Bot not found'}), 404
    return jsonify(bot_config)


@app.route('/api/bots/download-manager')
@login_required
def download_bot_manager():
    """Download just the Bot Manager infrastructure — no bot config included."""
    launch_vbs = (
        'Option Explicit\r\n'
        'Dim WshShell, fso, sDir, result\r\n'
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        'Set fso      = CreateObject("Scripting.FileSystemObject")\r\n'
        'sDir = fso.GetParentFolderName(WScript.ScriptFullName)\r\n\r\n'
        'Sub NoPython()\r\n'
        '    MsgBox "Python 3.9+ is required but was not found." & vbCrLf & vbCrLf & _\r\n'
        '           "Download it from: https://python.org" & vbCrLf & _\r\n'
        "           \"During installation, tick 'Add Python to PATH'.\" & vbCrLf & vbCrLf & _\r\n"
        '           "After installing Python, double-click Launch.vbs again.", _\r\n'
        '           vbCritical, "Discord Bot Manager"\r\n'
        '    WScript.Quit 1\r\n'
        'End Sub\r\n\r\n'
        'result = WshShell.Run("py --version", 0, True)\r\n'
        'If result = 0 Then\r\n'
        '    WshShell.Run "py """ & sDir & "\\bot_manager.py""", 0, False\r\n'
        '    WScript.Quit 0\r\n'
        'End If\r\n\r\n'
        'result = WshShell.Run("python --version", 0, True)\r\n'
        'If result = 0 Then\r\n'
        '    WshShell.Run "python """ & sDir & "\\bot_manager.py""", 0, False\r\n'
        '    WScript.Quit 0\r\n'
        'End If\r\n\r\n'
        'NoPython()\r\n'
    )
    launch_bat = (
        '@echo off\r\n'
        'title Discord Bot Manager — DEBUG\r\n'
        'echo =========================================\r\n'
        'echo  Discord Bot Manager  [DEBUG MODE]\r\n'
        'echo  All server output will appear here.\r\n'
        'echo  Keep this window open while using the\r\n'
        'echo  manager at http://localhost:5001\r\n'
        'echo =========================================\r\n'
        'echo.\r\n'
        'py --version >nul 2>&1\r\n'
        'if %errorlevel% equ 0 (\r\n'
        '    py bot_manager.py --debug\r\n'
        '    goto :done\r\n'
        ')\r\n'
        'python --version >nul 2>&1\r\n'
        'if %errorlevel% equ 0 (\r\n'
        '    python bot_manager.py --debug\r\n'
        '    goto :done\r\n'
        ')\r\n'
        'echo.\r\n'
        'echo ERROR: Python 3.9+ was not found.\r\n'
        'echo Download it from: https://python.org\r\n'
        'echo During installation tick "Add Python to PATH".\r\n'
        ':done\r\n'
        'echo.\r\n'
        'echo Bot manager stopped. Press any key to close...\r\n'
        'pause >nul\r\n'
    )
    launch_sh  = '#!/bin/bash\npython3 bot_manager.py || python bot_manager.py\n'
    readme = (
        '# Discord Bot Manager\n'
        '=' * 36 + '\n\n'
        'QUICK START\n'
        '-----------\n'
        '1. Install Python 3.9+ from https://python.org\n'
        '   (tick "Add Python to PATH" during installation)\n'
        '2. Double-click  Launch.vbs  (Windows)\n'
        '   or run:  bash launch.sh  (Mac/Linux)\n'
        '3. A browser opens at http://localhost:5001\n'
        '4. Go back to the web dashboard and click "Add to Manager"\n'
        '   next to each bot — it will appear here automatically.\n\n'
        'ADDING BOTS MANUALLY\n'
        '--------------------\n'
        'You can also drag and drop a config_xxx.json file directly\n'
        'onto the drop zone in the manager\'s browser UI.\n\n'
        'Generated by Discord Server Setup\n'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('bot_manager_v2/bot_manager.py',   _BOT_MANAGER_PY)
        zf.writestr('bot_manager_v2/bot.py',           _LOCAL_BOT_PY)
        zf.writestr('bot_manager_v2/requirements.txt', _LOCAL_REQUIREMENTS)
        zf.writestr('bot_manager_v2/Launch.vbs',       launch_vbs)
        zf.writestr('bot_manager_v2/launch_debug.bat', launch_bat)
        zf.writestr('bot_manager_v2/launch.sh',        launch_sh)
        zf.writestr('bot_manager_v2/README.txt',       readme)
        zf.writestr('bot_manager_v2/cogs/member_sync/__init__.py', '')
        zf.writestr('bot_manager_v2/cogs/member_sync/member_sync.py', _LOCAL_MEMBER_SYNC_PY)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name='bot_manager_v2.zip')


@app.route('/api/bots/download-botpy')
@login_required
def download_botpy():
    """Download just the latest bot.py — use to update an existing bot_manager folder."""
    buf = io.BytesIO(_LOCAL_BOT_PY.encode('utf-8'))
    buf.seek(0)
    return send_file(buf, mimetype='text/x-python', as_attachment=True,
                     download_name='bot.py')


@app.route('/api/bots/download-local/<server_id>/<bot_id>')
@login_required
def download_local_bot(server_id, bot_id):
    """First-time ZIP: Bot Manager + this bot's config bundled together."""
    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    bot_config, safe_name = _make_bot_config(server_id, bot_id, config, server)
    if bot_config is None:
        return jsonify({'error': 'Bot not found'}), 404

    install_dir = server.get('install_dir', '')
    cogs_dir    = os.path.join(install_dir, 'discord-server-setup', 'cogs')
    folder      = 'bot_manager_v2'

    launch_vbs = (
        'Option Explicit\r\n'
        'Dim WshShell, fso, sDir, result\r\n'
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        'Set fso      = CreateObject("Scripting.FileSystemObject")\r\n'
        'sDir = fso.GetParentFolderName(WScript.ScriptFullName)\r\n\r\n'
        'Sub NoPython()\r\n'
        '    MsgBox "Python 3.9+ is required but was not found." & vbCrLf & vbCrLf & _\r\n'
        '           "Download it from: https://python.org" & vbCrLf & _\r\n'
        "           \"During installation, tick 'Add Python to PATH'.\" & vbCrLf & vbCrLf & _\r\n"
        '           "After installing Python, double-click Launch.vbs again.", _\r\n'
        '           vbCritical, "Discord Bot Manager"\r\n'
        '    WScript.Quit 1\r\n'
        'End Sub\r\n\r\n'
        'result = WshShell.Run("py --version", 0, True)\r\n'
        'If result = 0 Then\r\n'
        '    WshShell.Run "py """ & sDir & "\\bot_manager.py""", 0, False\r\n'
        '    WScript.Quit 0\r\n'
        'End If\r\n\r\n'
        'result = WshShell.Run("python --version", 0, True)\r\n'
        'If result = 0 Then\r\n'
        '    WshShell.Run "python """ & sDir & "\\bot_manager.py""", 0, False\r\n'
        '    WScript.Quit 0\r\n'
        'End If\r\n\r\n'
        'NoPython()\r\n'
    )
    launch_bat = (
        '@echo off\r\n'
        'title Discord Bot Manager — DEBUG\r\n'
        'echo =========================================\r\n'
        'echo  Discord Bot Manager  [DEBUG MODE]\r\n'
        'echo  All server output will appear here.\r\n'
        'echo  Keep this window open while using the\r\n'
        'echo  manager at http://localhost:5001\r\n'
        'echo =========================================\r\n'
        'echo.\r\n'
        'py --version >nul 2>&1\r\n'
        'if %errorlevel% equ 0 (\r\n'
        '    py bot_manager.py --debug\r\n'
        '    goto :done\r\n'
        ')\r\n'
        'python --version >nul 2>&1\r\n'
        'if %errorlevel% equ 0 (\r\n'
        '    python bot_manager.py --debug\r\n'
        '    goto :done\r\n'
        ')\r\n'
        'echo.\r\n'
        'echo ERROR: Python 3.9+ was not found.\r\n'
        'echo Download it from: https://python.org\r\n'
        'echo During installation tick "Add Python to PATH".\r\n'
        ':done\r\n'
        'echo.\r\n'
        'echo Bot manager stopped. Press any key to close...\r\n'
        'pause >nul\r\n'
    )
    launch_sh  = '#!/bin/bash\npython3 bot_manager.py || python bot_manager.py\n'
    readme = (
        f'# Discord Bot Manager\n'
        f'{"=" * 36}\n\n'
        f'QUICK START\n'
        f'-----------\n'
        f'1. Install Python 3.9+ from https://python.org\n'
        f'   (tick "Add Python to PATH" during installation)\n'
        f'2. Double-click  Launch.vbs  (Windows)\n'
        f'   or run:  bash launch.sh  (Mac/Linux)\n'
        f'3. A browser opens at http://localhost:5001\n'
        f'4. To add more bots, click "Add to Manager" in the web dashboard\n'
        f'   or drag-and-drop a config_xxx.json file into the manager UI.\n\n'
        f'Generated by Discord Server Setup\n'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f'{folder}/config_{safe_name}.json', json.dumps(bot_config, indent=2))
        zf.writestr(f'{folder}/bot_manager.py',          _BOT_MANAGER_PY)
        zf.writestr(f'{folder}/bot.py',                  _LOCAL_BOT_PY)
        zf.writestr(f'{folder}/requirements.txt',        _LOCAL_REQUIREMENTS)
        zf.writestr(f'{folder}/Launch.vbs',              launch_vbs)
        zf.writestr(f'{folder}/launch_debug.bat',        launch_bat)
        zf.writestr(f'{folder}/launch.sh',               launch_sh)
        zf.writestr(f'{folder}/README.txt',              readme)
        zf.writestr(f'{folder}/cogs/member_sync/__init__.py', '')
        zf.writestr(f'{folder}/cogs/member_sync/member_sync.py', _LOCAL_MEMBER_SYNC_PY)
        if os.path.isdir(cogs_dir):
            for root, dirs, files in os.walk(cogs_dir):
                dirs[:] = [d for d in dirs if d != '__pycache__']
                for fname in files:
                    if fname.endswith('.pyc'): continue
                    fpath   = os.path.join(root, fname)
                    arcname = os.path.join(folder, 'cogs', os.path.relpath(fpath, cogs_dir))
                    zf.write(fpath, arcname)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True,
                     download_name='bot_manager_v2.zip')


@app.route('/api/bots/restart', methods=['POST'])
@login_required
def restart_bot():
    data      = request.json
    server_id = data.get('server_id')
    bot_id    = data.get('bot_id')

    if not all([server_id, bot_id]):
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if config is None:
        return jsonify({'error': 'Server not found, not authorized, or config missing'}), 404

    bot_cfg = _find_bot_by_id(config, bot_id)
    if not bot_cfg:
        return jsonify({'error': 'Bot not found in config'}), 404

    bot_name  = bot_cfg['name']
    bot_token = bot_cfg['token']
    guild_id  = server['guild_id']

    import bot_docker as _bd
    if _bd.is_docker_mode():
        single_config = dict(config)
        single_config['discord_bots'] = [bot_cfg]
        threading.Thread(
            target=_send_bot_log,
            args=(guild_id, bot_name, 'restarting', '', bot_token),
            daemon=True
        ).start()
        ok, msg = _bd.restart(server_id, bot_name, bot_token, single_config)
        if not ok:
            return jsonify({'error': msg}), 500
        threading.Thread(
            target=_send_bot_log,
            args=(guild_id, bot_name, 'online', 'container restarted', bot_token),
            daemon=True
        ).start()
        return jsonify({'success': True, 'message': f'Bot {bot_name} restarted.'})

    return jsonify({'error': 'Restart is only available in Docker mode. Use your bot_manager package.'}), 400


# ============================================
# LOCAL BOT LINK-BACK API
# ============================================

_BOT_OFFLINE_THRESHOLD = 300  # seconds before a bot is considered offline


def _check_bots_offline(owner, server_id, cfg, srv_name):
    """Mark stale local bots offline and fire events/notifications. Returns True if cfg changed."""
    changed = False
    for b in cfg.get('discord_bots', []):
        last_seen = b.get('local_last_seen')
        if not last_seen:
            continue
        try:
            dt = datetime.fromisoformat(last_seen)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            stale = (datetime.now(timezone.utc) - dt).total_seconds() > _BOT_OFFLINE_THRESHOLD
        except Exception:
            continue
        if stale and b.get('local_status') != 'offline':
            b['local_status'] = 'offline'
            changed = True
            bot_name = b.get('name', b.get('id', '?'))
            append_event(owner, server_id, srv_name, 'bot_offline',
                         f'Bot "{bot_name}" went offline')
            fire_notification_webhooks(owner, server_id, 'bot_offline',
                                       f'🔴 Bot **{bot_name}** went offline on server **{srv_name}**',
                                       {'bot_name': bot_name, 'server_name': srv_name})
    return changed


def _validate_local_bot_token(server_id, bot_id, token):
    """Return True if the token matches the one stored for this server+bot."""
    users_data = load_users()
    for uname, udata in users_data.items():
        tk = udata.get('local_bot_tokens', {}).get(f'{server_id}:{bot_id}')
        if tk and tk == token:
            return uname
    return None


@app.route('/api/local-bot/heartbeat', methods=['POST'])
def local_bot_heartbeat():
    data      = request.get_json(silent=True) or {}
    server_id = data.get('server_id', '')
    bot_id    = data.get('bot_id', '')
    status    = data.get('status', 'online')
    log_tail  = data.get('log_tail', [])
    ping_ms   = data.get('ping_ms')
    uptime    = data.get('uptime')
    token     = request.headers.get('X-Bot-Token', '')
    owner     = _validate_local_bot_token(server_id, bot_id, token)
    if not owner:
        return jsonify({'error': 'Unauthorized'}), 401
    servers_data = load_servers()
    srv_name = (servers_data.get(server_id) or {}).get('server_name', server_id)
    if server_id in servers_data:
        cfg_path = servers_data[server_id].get('config_path', '')
        if cfg_path and os.path.exists(cfg_path):
            cfg = load_server_config(cfg_path) or {}
            for b in cfg.get('discord_bots', []):
                if b.get('id') == bot_id:
                    prev_seen = b.get('local_last_seen')
                    was_online = False
                    if prev_seen:
                        try:
                            dt = datetime.fromisoformat(prev_seen)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            was_online = (datetime.now(timezone.utc) - dt).total_seconds() < 180
                        except Exception:
                            pass
                    b['local_status'] = status
                    b['local_last_seen'] = datetime.now(timezone.utc).isoformat()
                    if ping_ms is not None:
                        b['local_ping_ms'] = int(ping_ms)
                    if uptime is not None:
                        b['local_uptime'] = str(uptime)
                    save_server_config(cfg_path, cfg)
                    if log_tail:
                        logs_path = os.path.join(USERS_DATA_DIR,owner, 'servers',
                                                  server_id, f'bot_logs_{bot_id}.json')
                        os.makedirs(os.path.dirname(logs_path), exist_ok=True)
                        save_json(logs_path, {
                            'lines':      log_tail,
                            'updated_at': datetime.now(timezone.utc).isoformat(),
                        })
                    if not was_online:
                        bot_name = b.get('name', bot_id)
                        msg = f'🟢 Bot **{bot_name}** came online on server **{srv_name}**'
                        append_event(owner, server_id, srv_name, 'bot_online',
                                     f'Bot "{bot_name}" came online')
                        fire_notification_webhooks(owner, server_id, 'bot_online', msg,
                                                   {'bot_name': bot_name, 'server_name': srv_name})
                    break
    return jsonify({'ok': True})


@app.route('/api/local-bot/members', methods=['POST'])
def local_bot_members():
    data      = request.get_json(silent=True) or {}
    server_id = data.get('server_id', '')
    bot_id    = data.get('bot_id', '')
    members   = data.get('members', [])
    token     = request.headers.get('X-Bot-Token', '')
    owner     = _validate_local_bot_token(server_id, bot_id, token)
    if not owner:
        return jsonify({'error': 'Unauthorized'}), 401
    members_path = os.path.join(USERS_DATA_DIR,owner, 'servers', server_id)
    os.makedirs(members_path, exist_ok=True)
    save_json(os.path.join(members_path, 'members.json'), members)
    srv_name = (load_servers().get(server_id) or {}).get('server_name', server_id)
    count = len(members)
    append_event(owner, server_id, srv_name, 'member_sync',
                 f'Member list synced — {count} member{"s" if count != 1 else ""}')
    fire_notification_webhooks(owner, server_id, 'member_sync',
                               f'🔄 Member list synced on **{srv_name}** — {count} member{"s" if count != 1 else ""}',
                               {'server_name': srv_name, 'count': count})
    return jsonify({'ok': True, 'count': count})


@app.route('/api/local-bot/script-zip', methods=['GET'])
def local_bot_script_zip():
    """Serve a single cog folder as a flat zip so the local bot can sync it."""
    server_id   = request.args.get('server_id', '')
    script_name = request.args.get('script', '')
    token       = request.headers.get('X-Bot-Token', '')
    if not server_id or not script_name:
        return jsonify({'error': 'Missing server_id or script'}), 400
    owner = _validate_local_bot_token(server_id, request.args.get('bot_id', ''), token)
    # Also accept any valid token for this server (bot_id may not be in query params)
    if not owner:
        for bid in ['']:
            owner = _validate_local_bot_token(server_id, bid, token)
            if owner:
                break
    if not owner:
        # Try all bots on this server
        servers_data = load_servers()
        srv = servers_data.get(server_id, {})
        cfg_path = srv.get('config_path', '')
        if cfg_path and os.path.exists(cfg_path):
            cfg = load_server_config(cfg_path) or {}
            for b in cfg.get('discord_bots', []):
                o = _validate_local_bot_token(server_id, b.get('id', ''), token)
                if o:
                    owner = o
                    break
    if not owner:
        return jsonify({'error': 'Unauthorized'}), 401
    servers_data = load_servers()
    srv = servers_data.get(server_id, {})
    install_dir = srv.get('install_dir', '')
    cog_folder  = os.path.join(install_dir, 'discord-server-setup', 'cogs', script_name)
    cogs_root   = os.path.realpath(os.path.join(install_dir, 'discord-server-setup', 'cogs'))
    if not os.path.realpath(cog_folder).startswith(cogs_root + os.sep):
        return jsonify({'error': 'Invalid script name'}), 400
    if not os.path.isdir(cog_folder):
        return jsonify({'error': f'Script "{script_name}" not found on server'}), 404
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(cog_folder):
            dirs[:] = [d for d in dirs if d != '__pycache__']
            for fname in files:
                if fname.endswith('.pyc'):
                    continue
                fpath   = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, cog_folder)
                zf.write(fpath, arcname)
    buf.seek(0)
    return send_file(buf, mimetype='application/zip',
                     download_name=f'{script_name}.zip')


@app.route('/api/local-bot/commands', methods=['GET'])
def local_bot_get_commands():
    server_id = request.args.get('server_id', '')
    bot_id    = request.args.get('bot_id', '')
    token     = request.headers.get('X-Bot-Token', '')
    owner     = _validate_local_bot_token(server_id, bot_id, token)
    if not owner:
        return jsonify({'error': 'Unauthorized'}), 401
    cmds_path = os.path.join(USERS_DATA_DIR,owner, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    pending = [c for c in cmds if c.get('status') == 'pending']
    return jsonify({'commands': pending})


@app.route('/api/local-bot/logs/<server_id>/<bot_id>')
@login_required
def local_bot_logs(server_id, bot_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    logs_path = os.path.join(USERS_DATA_DIR,username, 'servers',
                             server_id, f'bot_logs_{bot_id}.json')
    data = load_json(logs_path, {})
    return jsonify({
        'lines':      data.get('lines', []),
        'updated_at': data.get('updated_at'),
    })


@app.route('/api/local-bot/command-result', methods=['POST'])
def local_bot_command_result():
    data       = request.get_json(silent=True) or {}
    server_id  = data.get('server_id', '')
    bot_id     = data.get('bot_id', '')
    command_id = data.get('command_id', '')
    token      = request.headers.get('X-Bot-Token', '')
    owner      = _validate_local_bot_token(server_id, bot_id, token)
    if not owner:
        return jsonify({'error': 'Unauthorized'}), 401
    cmds_path = os.path.join(USERS_DATA_DIR,owner, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    matched_cmd = None
    for c in cmds:
        if c.get('id') == command_id:
            c['status'] = 'done' if data.get('success') else 'failed'
            c['error'] = data.get('error', '')
            c['completed_at'] = datetime.now(timezone.utc).isoformat()
            matched_cmd = c
            break
    save_json(cmds_path, cmds)
    if matched_cmd:
        srv_name = (load_servers().get(server_id) or {}).get('server_name', server_id)
        status = 'succeeded' if data.get('success') else f'failed: {data.get("error","")[:60]}'
        ctype = matched_cmd.get('type', 'action')
        uid = matched_cmd.get('user_id', '?')
        desc = f'{ctype.replace("_"," ").title()} on user {uid} — {status}'
        append_event(owner, server_id, srv_name, 'command', desc)
        fire_notification_webhooks(owner, server_id, 'command',
                                   f'⚡ Command on **{srv_name}**: {desc}',
                                   {'server_name': srv_name, 'description': desc})
    return jsonify({'ok': True})


@app.route('/members/<server_id>')
@login_required
def members_page(server_id):
    username = session['user_id']
    servers_data, server = get_server_or_404(server_id, username)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('dashboard'))
    members_file = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'members.json')
    members = load_json(members_file, [])

    role_names = []
    local_bot_online = False
    cfg_path = server.get('config_path', '')
    if cfg_path:
        cfg = load_server_config(cfg_path) or {}
        srv_name = server.get('server_name', server_id)
        if _check_bots_offline(username, server_id, cfg, srv_name):
            save_server_config(cfg_path, cfg)
        role_names = [r.get('name', '') for r in cfg.get('roles', []) if r.get('name')]
        for b in cfg.get('discord_bots', []):
            last_seen = b.get('local_last_seen', '')
            if last_seen:
                try:
                    seen_dt = datetime.fromisoformat(last_seen)
                    if seen_dt.tzinfo is None:
                        seen_dt = seen_dt.replace(tzinfo=timezone.utc)
                    if (datetime.now(timezone.utc) - seen_dt).total_seconds() < 180:
                        local_bot_online = True
                        break
                except Exception:
                    pass

    return redirect('/app/')  # React MembersPage


@app.route('/api/members/<server_id>', methods=['GET'])
@login_required
def get_members(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    members_file = os.path.join(USERS_DATA_DIR, username, 'servers', server_id, 'members.json')
    members = load_json(members_file, [])
    role_names = []
    cfg_path = server.get('config_path', '')
    if cfg_path:
        cfg = load_server_config(cfg_path) or {}
        role_names = [r.get('name', '') for r in cfg.get('roles', []) if r.get('name')]
    return jsonify({'members': members, 'role_names': role_names})


@app.route('/api/members/<server_id>/action', methods=['POST'])
@login_required
def member_action(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username, require_permission='edit_server')
    if not server:
        return jsonify({'error': 'Not found or insufficient permissions'}), 404
    data = request.get_json(silent=True) or {}
    action_type = data.get('type', '')
    if action_type not in ('kick', 'ban', 'assign_role', 'remove_role'):
        return jsonify({'error': 'Invalid action'}), 400
    cmd = {
        'id': str(uuid.uuid4()),
        'type': action_type,
        'user_id': str(data.get('user_id', '')),
        'role_name': data.get('role_name', ''),
        'reason': data.get('reason', ''),
        'status': 'pending',
        'error': '',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'completed_at': None,
    }
    cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    cmds.append(cmd)
    if len(cmds) > 200:
        cmds = cmds[-200:]
    save_json(cmds_path, cmds)
    return jsonify({'ok': True, 'command_id': cmd['id']})


@app.route('/commands/<server_id>')
@login_required
def commands_page(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('dashboard'))
    cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    cmds.sort(key=lambda c: c.get('created_at', ''), reverse=True)
    return redirect('/app/')  # React (no dedicated commands page yet)


@app.route('/api/commands/<server_id>/clear', methods=['POST'])
@login_required
def commands_clear(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    kept = [c for c in cmds if c.get('status') == 'pending']
    save_json(cmds_path, kept)
    return jsonify({'ok': True, 'removed': len(cmds) - len(kept)})


@app.route('/api/local-bot/queue-restart', methods=['POST'])
@login_required
def queue_local_bot_restart():
    data      = request.get_json(silent=True) or {}
    server_id = data.get('server_id', '')
    bot_id    = data.get('bot_id', '')
    username  = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    cmd = {
        'id':           str(uuid.uuid4()),
        'type':         'restart',
        'bot_id':       bot_id,
        'status':       'pending',
        'error':        '',
        'created_at':   datetime.now(timezone.utc).isoformat(),
        'completed_at': None,
    }
    cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    cmds.append(cmd)
    if len(cmds) > 200:
        cmds = cmds[-200:]
    save_json(cmds_path, cmds)
    return jsonify({'ok': True, 'command_id': cmd['id']})


# ============================================
# ROLE MANAGER
# ============================================

def _cfg_roles(cfg):
    return cfg.setdefault('roles', cfg.pop('custom_roles', []))


@app.route('/roles/<server_id>')
@login_required
def roles_page(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('dashboard'))
    cfg = load_server_config(server.get('config_path', '')) or {}
    roles = _cfg_roles(cfg)
    cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
    pending_sync = any(
        c.get('type') == 'sync_roles' and c.get('status') == 'pending'
        for c in load_json(cmds_path, [])
    )
    # determine if a local bot is online
    bots = cfg.get('discord_bots', [])
    now = datetime.now(timezone.utc)
    bot_online = False
    for b in bots:
        ls = b.get('local_last_seen', '')
        if ls:
            try:
                dt = datetime.fromisoformat(ls)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if (now - dt).total_seconds() < 180:
                    bot_online = True
                    break
            except Exception:
                pass
    return redirect('/app/')  # React ServerPage roles tab


@app.route('/api/roles/<server_id>', methods=['POST'])
@login_required
def api_role_add(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    cfg_path = server.get('config_path', '')
    cfg = load_server_config(cfg_path) or {}
    roles = _cfg_roles(cfg)
    body = request.get_json(force=True) or {}
    name = body.get('name', '').strip()
    if not name:
        return jsonify({'error': 'Name required'}), 400
    color       = body.get('color', '#99aab5')
    hoist       = bool(body.get('hoist', False))
    permissions = body.get('permissions', [])
    role = {'name': name, 'color': color, 'hoist': hoist, 'permissions': permissions}
    existing_idx = next((i for i, r in enumerate(roles) if r.get('name') == name), None)
    if existing_idx is not None:
        roles[existing_idx] = role  # update existing
    else:
        roles.append(role)          # create new
    save_server_config(cfg_path, cfg)
    return jsonify({'ok': True, 'role': role})


@app.route('/api/roles/<server_id>/<path:role_name>', methods=['DELETE'])
@login_required
def api_role_delete(server_id, role_name):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    cfg_path = server.get('config_path', '')
    cfg = load_server_config(cfg_path) or {}
    roles = _cfg_roles(cfg)
    before = len(roles)
    cfg['roles'] = [r for r in roles if r.get('name') != role_name]
    if len(cfg['roles']) == before:
        return jsonify({'error': 'Role not found'}), 404
    save_server_config(cfg_path, cfg)
    return jsonify({'ok': True})


@app.route('/api/roles/<server_id>/sync', methods=['POST'])
@login_required
def api_roles_sync(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    cfg = load_server_config(server.get('config_path', '')) or {}
    roles = _cfg_roles(cfg)
    cmd = {
        'id':           str(uuid.uuid4()),
        'type':         'sync_roles',
        'roles':        roles,
        'status':       'pending',
        'error':        '',
        'created_at':   datetime.now(timezone.utc).isoformat(),
        'completed_at': None,
    }
    cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
    cmds = load_json(cmds_path, [])
    cmds.append(cmd)
    if len(cmds) > 200:
        cmds = cmds[-200:]
    save_json(cmds_path, cmds)
    return jsonify({'ok': True, 'command_id': cmd['id']})


# ============================================
# SERVER SETTINGS
# ============================================

@app.route('/settings/<server_id>')
@login_required
def server_settings(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('dashboard'))
    if server.get('owner') != username:
        flash('Only the server owner can access settings.', 'error')
        return redirect(url_for('servers_page'))
    return redirect('/app/')  # React SettingsPage


@app.route('/api/settings/<server_id>', methods=['POST'])
@login_required
def api_server_settings(server_id):
    username = session['user_id']
    servers_data, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner') != username:
        return jsonify({'error': 'Forbidden'}), 403
    body = request.get_json(force=True) or {}
    new_name = body.get('server_name', '').strip()
    new_guild = body.get('guild_id', '').strip()
    if new_name:
        servers_data[server_id]['server_name'] = new_name
        cfg_path = server.get('config_path', '')
        if cfg_path:
            cfg = load_server_config(cfg_path) or {}
            cfg['server_name'] = new_name
            save_server_config(cfg_path, cfg)
    if new_guild:
        servers_data[server_id]['guild_id'] = new_guild
        cfg_path = server.get('config_path', '')
        if cfg_path:
            cfg = load_server_config(cfg_path) or {}
            cfg['guild_id'] = new_guild
            save_server_config(cfg_path, cfg)
    save_servers(servers_data)
    return jsonify({'ok': True})


@app.route('/api/settings/<server_id>/icon', methods=['POST'])
@login_required
def api_server_icon(server_id):
    """Upload a new server icon and push it to Discord via PATCH guild."""
    username = session['user_id']
    servers_data, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    if server.get('owner') != username:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.get_json(force=True) or {}
    icon_data = data.get('icon_data', '').strip()   # data:image/...;base64,...
    if not icon_data:
        return jsonify({'error': 'icon_data required'}), 400

    guild_id = server.get('guild_id', '')
    cfg      = load_server_config(server.get('config_path', '')) or {}
    token    = (next((b['token'] for b in cfg.get('discord_bots',[]) if b.get('token')), None)
                or cfg.get('bot_token'))
    if not token:
        return jsonify({'error': 'No bot token configured'}), 400

    if not guild_id:
        return jsonify({'error': 'Guild ID not set for this server'}), 400

    try:
        resp = requests.patch(
            f"{DISCORD_API}/guilds/{guild_id}",
            headers={'Authorization': f'Bot {token}', 'Content-Type': 'application/json'},
            json={'icon': icon_data},
            timeout=15,
        )
        if resp.status_code in (200, 204):
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': f'Discord returned {resp.status_code}: {resp.text[:200]}'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============================================
# INTEGRATIONS (WEBHOOKS)
# ============================================

def _integrations_path(username, server_id):
    return os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'integrations.json')


def _webhook_log_path(owner, server_id, webhook_id):
    return os.path.join(USERS_DATA_DIR,owner, 'servers', server_id, f'whlog_{webhook_id}.json')


def _fire_single_webhook(url: str, payload: dict, retries: int = 3) -> bool:
    """POST to a webhook URL with exponential backoff. Returns True on success."""
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=payload, timeout=5)
            if resp.status_code == 429:
                retry_after = float(resp.json().get('retry_after', 2))
                import time as _t; _t.sleep(retry_after)
                continue
            return resp.ok
        except Exception:
            if attempt < retries - 1:
                import time as _t; _t.sleep(2 ** attempt)
    return False


def fire_notification_webhooks(owner, server_id, event_type, message, context=None):
    """POST to all webhooks subscribed to event_type with retry + backoff. Never raises.
    context: optional dict for template variable substitution."""
    path = _integrations_path(owner, server_id)
    items = load_json(path, [])
    changed = False
    for hook in items:
        if event_type in hook.get('notify_events', []):
            tmpl = hook.get('message_templates', {}).get(event_type, '')
            if tmpl and context:
                try:
                    msg = tmpl.format(**context)
                except Exception:
                    msg = message
            else:
                msg = message
            ts = datetime.now(timezone.utc).isoformat()
            ok = _fire_single_webhook(hook['url'], {'content': msg})
            if ok:
                hook['last_used'] = ts
                changed = True
            # Append to per-webhook fire log (keep last 20)
            log_path = _webhook_log_path(owner, server_id, hook['id'])
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            log = load_json(log_path, [])
            log.append({'ts': ts, 'event': event_type, 'msg': msg[:200], 'ok': ok})
            if len(log) > 20:
                log = log[-20:]
            save_json(log_path, log)
    if changed:
        save_json(path, items)


def _botmgr_secret():
    try:
        with open(os.path.join(_APP_DIR, '.botmgr_secret'), 'r') as _f:
            return _f.read().strip()
    except OSError:
        return ''

@app.route('/api/internal/bot-crash-alert', methods=['POST'])
def internal_bot_crash_alert():
    """Receives crash notifications from the local bot_manager package and fires user webhooks."""
    if request.headers.get('X-Manager-Secret', '') != _botmgr_secret():
        return jsonify({'error': 'Unauthorized'}), 401
    data     = request.get_json(silent=True) or {}
    bot_name = data.get('bot_name', '?')
    message  = data.get('message', f'Bot "{bot_name}" crashed')
    servers  = load_servers()
    for server_id, srv in servers.items():
        owner = srv.get('owner', '')
        cfg_path = srv.get('config_path')
        if not cfg_path:
            continue
        cfg  = load_server_config(cfg_path) or {}
        bots = cfg.get('discord_bots', [])
        if any(b.get('name') == bot_name for b in bots):
            append_event(owner, server_id, srv.get('server_name', server_id),
                         'bot_offline', f'Bot "{bot_name}" crashed: {message}')
            fire_notification_webhooks(owner, server_id, 'bot_offline',
                                       f'🔴 **{bot_name}** crashed on **{srv.get("server_name", server_id)}**: {message}',
                                       {'bot_name': bot_name, 'server_name': srv.get('server_name', server_id)})
    return jsonify({'ok': True})


@app.route('/integrations/<server_id>')
@login_required
def integrations_page(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        flash('Server not found.', 'error')
        return redirect(url_for('dashboard'))
    integrations = load_json(_integrations_path(username, server_id), [])
    return redirect('/app/')  # React IntegrationsPage


@app.route('/api/integrations/<server_id>', methods=['GET'])
@login_required
def api_integrations_list(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(load_json(_integrations_path(username, server_id), []))


@app.route('/api/integrations/<server_id>', methods=['POST'])
@login_required
def api_integrations_create(server_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    data = request.get_json(silent=True) or {}
    url  = data.get('url', '').strip()
    name = data.get('name', '').strip() or 'Webhook'
    channel = data.get('channel', '').strip()
    if not url.startswith('https://'):
        return jsonify({'error': 'Invalid webhook URL'}), 400
    entry = {
        'id': str(uuid.uuid4()),
        'name': name[:80],
        'url': url,
        'channel': channel[:80],
        'created_at': datetime.now(timezone.utc).isoformat(),
        'last_used': None,
    }
    path = _integrations_path(username, server_id)
    items = load_json(path, [])
    items.append(entry)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    save_json(path, items)
    return jsonify({'ok': True, 'integration': entry})


@app.route('/api/integrations/<server_id>/<webhook_id>', methods=['DELETE'])
@login_required
def api_integrations_delete(server_id, webhook_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    path  = _integrations_path(username, server_id)
    items = load_json(path, [])
    items = [i for i in items if i.get('id') != webhook_id]
    save_json(path, items)
    return jsonify({'ok': True})


@app.route('/api/integrations/<server_id>/<webhook_id>', methods=['PATCH'])
@login_required
def api_integrations_update(server_id, webhook_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    path  = _integrations_path(username, server_id)
    items = load_json(path, [])
    hook  = next((i for i in items if i.get('id') == webhook_id), None)
    if not hook:
        return jsonify({'error': 'Not found'}), 404
    body = request.get_json(force=True) or {}
    _allowed_events = {'bot_online', 'bot_offline', 'member_sync', 'command'}
    if 'notify_events' in body:
        hook['notify_events'] = [e for e in body['notify_events'] if e in _allowed_events]
    if 'message_templates' in body:
        tmpl = body['message_templates']
        if isinstance(tmpl, dict):
            hook['message_templates'] = {k: str(v)[:500] for k, v in tmpl.items() if k in _allowed_events}
    save_json(path, items)
    return jsonify({'ok': True, 'integration': hook})


@app.route('/api/integrations/<server_id>/<webhook_id>/test', methods=['POST'])
@login_required
def api_integrations_test(server_id, webhook_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    path  = _integrations_path(username, server_id)
    items = load_json(path, [])
    hook  = next((i for i in items if i.get('id') == webhook_id), None)
    if not hook:
        return jsonify({'error': 'Not found'}), 404
    payload = {
        'content': f'Test message from **Discord Server Setup** — webhook "{hook["name"]}" is working.',
    }
    try:
        r = requests.post(hook['url'], json=payload, timeout=8)
        if r.status_code in (200, 204):
            hook['last_used'] = datetime.now(timezone.utc).isoformat()
            save_json(path, items)
            return jsonify({'ok': True})
        return jsonify({'error': f'Discord returned {r.status_code}'}), 502
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 502


@app.route('/api/integrations/<server_id>/<webhook_id>/log')
@login_required
def api_integrations_log(server_id, webhook_id):
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Not found'}), 404
    log = load_json(_webhook_log_path(username, server_id, webhook_id), [])
    log.reverse()
    return jsonify(log)


# ============================================
# DASHBOARD ACTIVITY FEED
# ============================================

@app.route('/api/dashboard/events')
@login_required
def dashboard_events():
    username = session['user_id']
    path = os.path.join(USERS_DATA_DIR,username, 'events.json')
    events = load_json(path, [])
    events.sort(key=lambda e: e.get('ts', ''), reverse=True)
    for e in events:
        e['icon'] = _EVENT_ICONS.get(e.get('type', ''), '📌')
    return jsonify(events[:50])


@app.route('/api/dashboard/events/export')
@login_required
def export_events():
    import csv as _csv
    username = session['user_id']
    path = os.path.join(USERS_DATA_DIR,username, 'events.json')
    events = load_json(path, [])
    events.sort(key=lambda e: e.get('ts', ''), reverse=True)
    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(['Timestamp (UTC)', 'Type', 'Server', 'Description'])
    for e in events:
        writer.writerow([
            e.get('ts', ''),
            e.get('type', ''),
            e.get('server_name', ''),
            e.get('description', ''),
        ])
    fname = f'activity_{datetime.now(timezone.utc).strftime("%Y%m%d")}.csv'
    return buf.getvalue(), 200, {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{fname}"',
    }


@app.route('/api/dashboard/server-health')
@login_required
def dashboard_server_health():
    username = session['user_id']
    users_data = load_users()
    servers_data = load_servers()
    user_server_ids = set(users_data.get(username, {}).get('servers', []))
    now = datetime.now(timezone.utc)
    result = []
    for sid in user_server_ids:
        srv = servers_data.get(sid)
        if not srv:
            continue
        cfg = load_server_config(srv.get('config_path', '')) or {}
        online = 0
        for b in cfg.get('discord_bots', []):
            ls = b.get('local_last_seen', '')
            if ls:
                try:
                    dt = datetime.fromisoformat(ls)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (now - dt).total_seconds() < 180:
                        online += 1
                except Exception:
                    pass
        members_file = os.path.join(USERS_DATA_DIR,username, 'servers', sid, 'members.json')
        members = load_json(members_file, [])
        last_sync = None
        if os.path.exists(members_file):
            try:
                mtime = os.path.getmtime(members_file)
                last_sync = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
            except Exception:
                pass
        cmds = load_json(os.path.join(USERS_DATA_DIR,username, 'servers', sid, 'commands.json'), [])
        result.append({
            'server_id':          sid,
            'server_name':        srv.get('server_name', sid),
            'setup_completed':    bool(srv.get('setup_completed')),
            'local_bots_total':   len(local_bots),
            'local_bots_online':  online,
            'member_count':       len(members),
            'last_sync':          last_sync,
            'pending_commands':   sum(1 for c in cmds if c.get('status') == 'pending'),
            'failed_commands':    sum(1 for c in cmds if c.get('status') == 'failed'),
        })
    result.sort(key=lambda x: x['server_name'].lower())
    return jsonify(result)


# In-memory cache for Discord live-status calls (5-min TTL per guild)
_live_status_cache: dict = {}   # { server_id: { 'data': {...}, 'expires': float } }
_LIVE_CACHE_TTL = 300           # seconds


def _count_config_channels(cfg):
    """Count total channel objects expected in Discord based on server config.

    Discord's channel list API returns categories (type 4) as channel objects too,
    so we count: 1 per category + text + voice + forum channels inside each.
    Mod template categories already present in custom_categories are not double-counted.
    """
    total = 0

    custom_cats = cfg.get('custom_categories', [])
    custom_cat_names = {c.get('name', '').upper() for c in custom_cats}

    # Custom categories: the category object itself + its child channels
    for cat in custom_cats:
        total += 1  # category is a channel object in Discord API (type 4)
        total += len(cat.get('text_channels', []))
        total += len(cat.get('voice_channels', []))
        total += len(cat.get('forum_channels', []))

    # Moderation template channels — skip if already in custom_categories (channels modal synced them)
    tmpl_dir = (cfg.get('paths') or {}).get('template_dir', '')
    if tmpl_dir:
        mod_tmpl = load_json(os.path.join(tmpl_dir, 'moderation_template.json'), None)
        if mod_tmpl:
            for cat in mod_tmpl.get('categories', []):
                if cat.get('name', '').upper() not in custom_cat_names:
                    total += 1  # the category itself
                    total += len(cat.get('text_channels', []))
                    total += len(cat.get('voice_channels', []))
        else:
            if 'MODERATION' not in custom_cat_names:
                total += 5  # default: 1 MODERATION category + 3 text + 1 voice
    else:
        if 'MODERATION' not in custom_cat_names:
            total += 5  # default: 1 MODERATION category + 3 text + 1 voice

    # Welcome template: creates uncategorized text channels (no category object)
    if cfg.get('use_welcome_template') in (True, 'yes', 1):
        if tmpl_dir:
            welcome_tmpl = load_json(os.path.join(tmpl_dir, 'welcome_template.json'), None)
            if welcome_tmpl:
                total += len(welcome_tmpl.get('text_channels', []))
            else:
                total += 3  # default: announcements + welcome + rules
        else:
            total += 3  # default: announcements + welcome + rules

    return total


@app.route('/api/dashboard/live-status')
@login_required
def dashboard_live_status():
    """
    Returns live Discord data for a single server (or all user servers).
    Results are cached per guild for _LIVE_CACHE_TTL seconds.
    Query params:
        server_id  — fetch a single server (optional; omit for all)
        refresh    — set to '1' to bypass cache
    """
    import time as _t
    username   = session['user_id']
    now_ts     = _t.time()
    force      = request.args.get('refresh') == '1'
    target_sid = request.args.get('server_id', '').strip() or None

    users_data   = load_users()
    servers_data = load_servers()
    user_sids    = set(users_data.get(username, {}).get('servers', []))
    for sid, srv in servers_data.items():
        if username in srv.get('collaborators', {}):
            user_sids.add(sid)

    if target_sid:
        if target_sid not in user_sids:
            return jsonify({'error': 'not found'}), 404
        sids = [target_sid]
    else:
        sids = list(user_sids)

    results = []
    for sid in sids:
        srv = servers_data.get(sid)
        if not srv:
            continue

        guild_id = (srv.get('guild_id') or '').strip()
        if not guild_id:
            results.append({'server_id': sid, 'ok': False, 'reason': 'no_guild_id'})
            continue

        # Cache hit?
        cached = _live_status_cache.get(sid)
        if not force and cached and cached['expires'] > now_ts:
            entry = dict(cached['data'])
            entry['cache_age_s'] = int(now_ts - cached['fetched_at'])
            entry['from_cache']  = True
            results.append(entry)
            continue

        # Resolve best bot token
        cfg   = load_server_config(srv.get('config_path', '')) or {}
        bots  = cfg.get('discord_bots', [])
        token = next((b['token'] for b in bots if b.get('maintenance') and b.get('token')), None)
        if not token:
            token = next((b['token'] for b in bots if b.get('token')), None)
        if not token:
            token = cfg.get('bot_token') or None

        # --- Live Discord calls ---
        ok_guild, guild_data, _ = _disc_get(token, f'/guilds/{guild_id}?with_counts=true')
        bot_in_guild = ok_guild and 'id' in guild_data

        live_channels = None
        live_roles    = None
        if bot_in_guild:
            ok_ch, ch_data, _ = _disc_get(token, f'/guilds/{guild_id}/channels')
            if ok_ch and isinstance(ch_data, list):
                live_channels = len(ch_data)

            ok_ro, ro_data, _ = _disc_get(token, f'/guilds/{guild_id}/roles')
            if ok_ro and isinstance(ro_data, list):
                # Exclude @everyone and bot-managed roles (auto-created by Discord bots)
                live_roles = len([r for r in ro_data
                                  if r['name'] != '@everyone' and not r.get('managed', False)])

        # Config-side counts for drift — must match what Setup_server.py actually creates:
        # custom_roles + mod template roles + welcome template roles + bots role
        cfg_channels = _count_config_channels(cfg)
        cfg_roles    = len(cfg.get('custom_roles', []))
        _tmpl_role_names = {cfg.get('bots_role_name', 'bots').lower()}
        _tmpl_dir = (cfg.get('paths') or {}).get('template_dir', '')
        if _tmpl_dir:
            for _tmpl in ('moderation_template.json', 'welcome_template.json'):
                _tp = os.path.join(_tmpl_dir, _tmpl)
                if os.path.exists(_tp):
                    try:
                        with open(_tp, 'r', encoding='utf-8') as _f:
                            for _r in json.load(_f).get('roles', []):
                                _n = (_r.get('name', '') if isinstance(_r, dict) else _r)
                                if _n:
                                    _tmpl_role_names.add(_n.lower())
                    except Exception:
                        pass
        cfg_roles += len(_tmpl_role_names)

        # Drift calculation
        if live_channels is not None and live_roles is not None:
            ch_diff   = abs(live_channels - cfg_channels)
            role_diff = abs(live_roles - cfg_roles)
            total_diff = ch_diff + role_diff
            if total_diff == 0:
                drift_status = 'sync'
            elif total_diff <= 3:
                drift_status = 'minor'
            else:
                drift_status = 'out_of_sync'
        else:
            ch_diff = role_diff = None
            drift_status = 'unknown'

        icon_hash      = guild_data.get('icon', '') if bot_in_guild else ''
        server_icon_url = (
            f'https://cdn.discordapp.com/icons/{guild_id}/{icon_hash}.png?size=64'
            if icon_hash else ''
        )
        entry = {
            'server_id':      sid,
            'ok':             bot_in_guild,
            'guild_name':     guild_data.get('name') if bot_in_guild else None,
            'member_count':   guild_data.get('approximate_member_count') or guild_data.get('member_count'),
            'online_count':   guild_data.get('approximate_presence_count') if bot_in_guild else None,
            'boost_tier':     int(guild_data.get('premium_tier', 0)) if bot_in_guild else None,
            'boost_count':    int(guild_data.get('premium_subscription_count') or 0) if bot_in_guild else None,
            'bot_in_guild':   bot_in_guild,
            'live_channels':  live_channels,
            'live_roles':     live_roles,
            'cfg_channels':   cfg_channels,
            'cfg_roles':      cfg_roles,
            'ch_diff':        ch_diff,
            'role_diff':      role_diff,
            'drift_status':   drift_status,
            'server_icon_url': server_icon_url,
            'cache_age_s':    0,
            'from_cache':     False,
        }
        _live_status_cache[sid] = {
            'data':       entry,
            'expires':    now_ts + _LIVE_CACHE_TTL,
            'fetched_at': now_ts,
        }
        results.append(entry)

    return jsonify(results)


# ============================================
# GITHUB COGS IMPORT
# ============================================

# Optional GitHub token — set GITHUB_TOKEN in .env to increase rate limit from 60 to 5000 req/hr
# Also required if discord-server-bot-scripts repo is private
_github_token = os.environ.get('GITHUB_TOKEN', '')
GITHUB_HEADERS = {
    "User-Agent":  "Python-Flask",
    "Accept":      "application/vnd.github.v3+json",
    **({"Authorization": f"Bearer {_github_token}"} if _github_token else {})
}

def fetch_cog_readme(folder_path):
    """Fetch description, author, version, and verified flag from a cog's README.md."""
    try:
        url = (
            f"https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/"
            f"{GITHUB_BOT_SCRIPTS_REPO}/contents/{folder_path}/README.md"
        )
        resp = requests.get(url, headers=GITHUB_HEADERS)
        if resp.status_code != 200:
            return None

        readme_url = resp.json().get('download_url')
        if not readme_url:
            return None

        text = requests.get(readme_url).text
        lines = text.split('\n')
        result = {}

        # Description: first non-heading paragraph after the title
        for i, line in enumerate(lines):
            if line.startswith('# '):
                for subsequent in lines[i + 1:]:
                    if subsequent.strip() and not subsequent.startswith('#'):
                        result['description'] = subsequent.strip()[:200]
                        break
                break

        # Author, Version, Verified — accepted as `**Field:** value` or `Field: value`
        for line in lines:
            stripped = line.strip()
            if not result.get('author'):
                m = re.search(r'\*\*Author\*\*\s*:\s*(.+)', stripped, re.IGNORECASE) \
                 or re.match(r'Author\s*:\s*(.+)', stripped, re.IGNORECASE)
                if m:
                    result['author'] = m.group(1).strip()[:60]
            if not result.get('version'):
                m = re.search(r'\*\*Version\*\*\s*:\s*(.+)', stripped, re.IGNORECASE) \
                 or re.match(r'Version\s*:\s*(.+)', stripped, re.IGNORECASE)
                if m:
                    result['version'] = m.group(1).strip()[:20]
            if not result.get('verified'):
                if re.search(r'\*\*Verified\*\*\s*:\s*true', stripped, re.IGNORECASE) \
                or re.match(r'Verified\s*:\s*true', stripped, re.IGNORECASE):
                    result['verified'] = True

        return result if result else None
    except Exception:
        return None


def download_github_folder(user, repo, branch, folder_path, dest_path):
    """Recursively download a folder from a GitHub repo."""
    try:
        os.makedirs(dest_path, exist_ok=True)
        url = f"https://api.github.com/repos/{user}/{repo}/contents/{folder_path}?ref={branch}"
        resp = requests.get(url, headers=GITHUB_HEADERS)
        resp.raise_for_status()

        for item in resp.json():
            item_dest = os.path.join(dest_path, item['name'])
            if item['type'] == 'file':
                file_resp = requests.get(item['download_url'])
                file_resp.raise_for_status()
                with open(item_dest, 'wb') as f:
                    f.write(file_resp.content)
            elif item['type'] == 'dir':
                download_github_folder(user, repo, branch, item['path'], item_dest)

        return True
    except Exception as e:
        print(f"Error downloading {folder_path}: {e}")
        return False


@app.route('/api/bots/available-cogs', methods=['GET'])
@login_required
def get_available_cogs():
    try:
        base_url = f"https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/{GITHUB_BOT_SCRIPTS_REPO}/contents"
        resp = requests.get(base_url, headers=GITHUB_HEADERS)
        resp.raise_for_status()

        folders = []
        for category in resp.json():
            if category['type'] != 'dir' or category['name'].startswith('.'):
                continue
            cat_resp = requests.get(f"{base_url}/{category['name']}", headers=GITHUB_HEADERS)
            if cat_resp.status_code != 200:
                continue
            for item in cat_resp.json():
                if item['type'] == 'dir' and not item['name'].startswith('.'):
                    info = {
                        'name':     item['name'],
                        'path':     item['path'],
                        'url':      item['html_url'],
                        'category': category['name'],
                    }
                    readme = fetch_cog_readme(item['path'])
                    if readme:
                        info.update(readme)
                    folders.append(info)

        return jsonify({'success': True, 'cogs': folders})
    except Exception as e:
        print(f"Error fetching cogs: {e}")
        return jsonify({'error': 'Failed to fetch cogs from GitHub'}), 500


@app.route('/api/bots/test-github')
@login_required
def test_github():
    """Debug: call from browser to see exactly what GitHub returns."""
    url = f'https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/{GITHUB_BOT_SCRIPTS_REPO}/contents'
    try:
        resp = requests.get(url, headers=GITHUB_HEADERS, timeout=10)
        return jsonify({
            'status_code': resp.status_code,
            'headers':     dict(resp.headers),
            'body':        resp.json() if resp.headers.get("content-type","").startswith("application/json") else resp.text[:500],
        })
    except Exception as e:
        return jsonify({'error': str(e)})


# In-memory cache — only hits GitHub once per Flask run, or on explicit refresh
_scripts_cache = {'data': None}

@app.route('/api/bots/available-scripts', methods=['GET'])
@login_required
def get_available_scripts():
    force = request.args.get('refresh') == '1'

    if not force and _scripts_cache['data'] is not None:
        return jsonify({'success': True, 'scripts': _scripts_cache['data'], 'cached': True})

    try:
        base_url = f'https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/{GITHUB_BOT_SCRIPTS_REPO}/contents'
        resp = requests.get(base_url, headers=GITHUB_HEADERS, timeout=8)
        resp.raise_for_status()

        scripts = []
        for category in resp.json():
            if category['type'] != 'dir' or category['name'].startswith('.'):
                continue
            cat_resp = requests.get(f"{base_url}/{category['name']}", headers=GITHUB_HEADERS, timeout=8)
            if cat_resp.status_code != 200:
                continue
            for item in cat_resp.json():
                if item['type'] == 'dir' and not item['name'].startswith('.'):
                    folder_path = item['path']  # e.g. Casino/blackjack
                    info = {
                        'id':          folder_path,
                        'name':        item['name'].replace('_', ' ').replace('-', ' ').title(),
                        'folder_name': item['name'],
                        'folder_path': folder_path,
                        'github_url':  item['html_url'],
                        'category':    category['name'],
                        'description': '',
                        'features':    [],
                        'icon':        '\U0001f4e6',
                    }
                    readme = fetch_cog_readme(folder_path)
                    if readme:
                        info['description'] = readme.get('description', '')
                        info['author']      = readme.get('author', '')
                        info['version']     = readme.get('version', '')
                        info['verified']    = readme.get('verified', False)
                    scripts.append(info)

        _scripts_cache['data'] = scripts
        return jsonify({'success': True, 'scripts': scripts, 'cached': False})
    except Exception as e:
        print(f'Error fetching scripts: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/api/bots/import-cogs', methods=['POST'])
@login_required
def import_cogs():
    data = request.json
    server_id = data.get('server_id')
    selected_cogs = data.get('cogs', [])

    if not server_id or not selected_cogs:
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    install_dir = server.get('install_dir')
    if not install_dir:
        return jsonify({'error': 'Installation directory not found'}), 404

    cogs_dir = os.path.join(install_dir, 'discord-server-setup', 'cogs')
    os.makedirs(cogs_dir, exist_ok=True)

    downloaded, failed = [], []
    for cog_path in selected_cogs:
        cog_name = os.path.basename(cog_path)  # e.g. Casino/blackjack → blackjack
        dest = os.path.join(cogs_dir, cog_name)
        ok = download_github_folder(
            GITHUB_BOT_SCRIPTS_USER, GITHUB_BOT_SCRIPTS_REPO,
            GITHUB_BOT_SCRIPTS_BRANCH, cog_path, dest
        )
        (downloaded if ok else failed).append(cog_name)

    # Queue sync_scripts for any local bots so they pull the new cogs automatically
    restarted = []
    synced_bots = []
    if downloaded and config:
        username = session['user_id']
        cmds_path = os.path.join(USERS_DATA_DIR,username, 'servers', server_id, 'commands.json')
        os.makedirs(os.path.dirname(cmds_path), exist_ok=True)
        cmds = load_json(cmds_path, [])
        for bot_cfg in config.get('discord_bots', []):
            cmds.append({
                'id':           str(uuid.uuid4()),
                'type':         'sync_scripts',
                'bot_id':       bot_cfg.get('id', ''),
                'scripts':      downloaded,
                'status':       'pending',
                'error':        '',
                'created_at':   datetime.now(timezone.utc).isoformat(),
                'completed_at': None,
            })
            synced_bots.append(bot_cfg.get('name', bot_cfg.get('id', '')))
        if len(cmds) > 200:
            cmds = cmds[-200:]
        save_json(cmds_path, cmds)

    return jsonify({
        'success': True,
        'downloaded': downloaded,
        'failed': failed,
        'restarted_bots': restarted,
        'synced_bots': synced_bots,
        'message': f'Downloaded {len(downloaded)} cog(s) to {cogs_dir}'
            + (f' — restarted {len(restarted)} bot(s)' if restarted else '')
            + (f' — sync queued for {len(synced_bots)} local bot(s)' if synced_bots else ''),
    })


@app.route('/api/bots/installed-cogs/<server_id>', methods=['GET'])
@login_required
def get_installed_cogs(server_id):
    _, server, _, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    install_dir = server.get('install_dir')
    if not install_dir:
        return jsonify({'cogs': []})

    cogs_dir = os.path.join(install_dir, 'discord-server-setup', 'cogs')
    if not os.path.exists(cogs_dir):
        return jsonify({'cogs': []})

    cogs = []
    for d in os.listdir(cogs_dir):
        if os.path.isdir(os.path.join(cogs_dir, d)) and not d.startswith('__'):
            version_file = os.path.join(cogs_dir, d, '.version')
            version = None
            if os.path.isfile(version_file):
                try:
                    with open(version_file, 'r') as vf:
                        version = vf.read().strip()
                except OSError:
                    pass
            cogs.append({'name': d, 'version': version})
    return jsonify({'cogs': cogs})


_VAR_RE = re.compile(
    r'^([A-Z][A-Z0-9_]+)\s*=\s*'
    r'(True|False|-?\d+(?:\.\d+)?|"[^"]*"|\'[^\']*\')'
    r'\s*(?:#.*)?$'
)

def _parse_variables_file(path):
    entries = []
    try:
        for line in open(path, encoding='utf-8', errors='replace'):
            m = _VAR_RE.match(line)
            if not m:
                continue
            key, raw = m.group(1), m.group(2)
            if raw in ('True', 'False'):
                typ, val = 'bool', raw == 'True'
            elif '.' in raw and not raw.startswith('"') and not raw.startswith("'"):
                typ, val = 'float', float(raw)
            elif raw.lstrip('-').isdigit():
                typ, val = 'int', int(raw)
            else:
                typ, val = 'str', raw[1:-1]
            entries.append({'key': key, 'type': typ, 'value': val})
    except OSError:
        pass
    return entries

def _save_variables_file(path, updates):
    try:
        lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    except OSError as e:
        return False, str(e)
    changed = 0
    for i, line in enumerate(lines):
        m = _VAR_RE.match(line)
        if not m:
            continue
        key, old_raw = m.group(1), m.group(2)
        if key not in updates:
            continue
        new_v = updates[key]
        if old_raw in ('True', 'False'):
            new_raw = 'True' if str(new_v).lower() in ('true', '1', 'yes') else 'False'
        elif old_raw.startswith('"'):
            new_raw = f'"{new_v}"'
        elif old_raw.startswith("'"):
            new_raw = f"'{new_v}'"
        else:
            new_raw = str(new_v)
        indent = line[:len(line) - len(line.lstrip())]
        cmt = re.search(r'\s*#.*$', line)
        lines[i] = f'{indent}{key} = {new_raw}' + (cmt.group(0) if cmt else '')
        changed += 1
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines) + '\n')
    except OSError as e:
        return False, str(e)
    return True, f'Updated {changed} variable(s)'


@app.route('/api/bots/script-vars/<server_id>', methods=['GET'])
@login_required
def get_script_vars(server_id):
    _, server, _, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Not found'}), 404
    install_dir = server.get('install_dir', '')
    cogs_dir    = os.path.join(install_dir, 'discord-server-setup', 'cogs')
    result = {}
    if os.path.isdir(cogs_dir):
        for folder in sorted(os.listdir(cogs_dir)):
            if folder.startswith('_') or not os.path.isdir(os.path.join(cogs_dir, folder)):
                continue
            vf = os.path.join(cogs_dir, folder, 'variables.py')
            if not os.path.exists(vf):
                continue
            entries = _parse_variables_file(vf)
            if entries:
                result[folder] = entries
    return jsonify({'scripts': result})


@app.route('/api/bots/script-vars/<server_id>', methods=['POST'])
@login_required
def save_script_vars(server_id):
    _, server, _, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Not found'}), 404
    data        = request.json or {}
    script_name = data.get('script', '')
    updates     = data.get('updates', {})
    install_dir = server.get('install_dir', '')
    vf        = os.path.join(install_dir, 'discord-server-setup', 'cogs', script_name, 'variables.py')
    cogs_root = os.path.realpath(os.path.join(install_dir, 'discord-server-setup', 'cogs'))
    if not os.path.realpath(vf).startswith(cogs_root + os.sep):
        return jsonify({'error': 'Invalid script name'}), 400
    if not os.path.exists(vf):
        return jsonify({'error': f'variables.py not found for {script_name}'}), 404
    ok, msg = _save_variables_file(vf, updates)
    return jsonify({'ok': ok, 'msg': msg})


@app.route('/scripts')
@login_required
def scripts_page():
    username = session['user_id']
    users = load_users()
    servers_data = load_servers()
    servers = [
        {'server_id': sid, 'server_name': servers_data[sid]['server_name']}
        for sid in users[username].get('servers', [])
        if sid in servers_data
    ]
    return redirect('/app/')  # React ScriptsPage


@app.route('/api/scripts/check-updates', methods=['POST'])
@login_required
def check_script_updates():
    """Compare each installed cog's .version SHA against the latest GitHub commit."""
    data      = request.get_json(silent=True) or {}
    server_id = data.get('server_id', '')
    _, server, _, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Not authorized'}), 404

    install_dir = server.get('install_dir', '')
    cogs_dir = os.path.join(install_dir, 'discord-server-setup', 'cogs') if install_dir else ''
    if not cogs_dir or not os.path.isdir(cogs_dir):
        return jsonify({'updates': {}})

    # Build map of cog_name → installed_sha
    installed = {}
    for d in os.listdir(cogs_dir):
        if os.path.isdir(os.path.join(cogs_dir, d)) and not d.startswith('__'):
            vf = os.path.join(cogs_dir, d, '.version')
            sha = None
            if os.path.isfile(vf):
                try:
                    with open(vf) as f:
                        sha = f.read().strip()
                except OSError:
                    pass
            installed[d] = sha

    if not installed:
        return jsonify({'updates': {}})

    # Fetch available scripts so we can map folder_name → folder_path
    scripts_resp = get_available_scripts()
    scripts_data = scripts_resp.get_json() if hasattr(scripts_resp, 'get_json') else {}
    all_scripts  = scripts_data.get('scripts', []) if isinstance(scripts_data, dict) else []
    path_map     = {s['folder_name']: s['folder_path'] for s in all_scripts}

    updates = {}
    for cog_name, installed_sha in installed.items():
        folder_path = path_map.get(cog_name)
        if not folder_path:
            updates[cog_name] = {'has_update': False, 'reason': 'not_in_library'}
            continue
        try:
            url  = (f'https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/'
                    f'{GITHUB_BOT_SCRIPTS_REPO}/commits')
            resp = requests.get(url, headers=GITHUB_HEADERS,
                                params={'path': folder_path, 'per_page': 1}, timeout=8)
            if resp.status_code != 200:
                updates[cog_name] = {'has_update': False, 'reason': 'api_error'}
                continue
            commits = resp.json()
            if not commits:
                updates[cog_name] = {'has_update': False}
                continue
            latest_sha  = commits[0]['sha']
            latest_short = latest_sha[:7]
            has_update = (installed_sha is None) or (not latest_sha.startswith(installed_sha)
                                                      and installed_sha != latest_short)
            updates[cog_name] = {
                'has_update':    has_update,
                'installed_sha': installed_sha,
                'latest_sha':    latest_short,
                'latest_message': commits[0]['commit']['message'].split('\n')[0][:80],
            }
        except Exception:
            updates[cog_name] = {'has_update': False, 'reason': 'error'}

    return jsonify({'updates': updates})


@app.route('/api/scripts/versions')
@login_required
def get_script_versions():
    script_path = request.args.get('path', '').strip()
    if not script_path:
        return jsonify({'error': 'Missing path parameter'}), 400
    try:
        url = (f'https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/'
               f'{GITHUB_BOT_SCRIPTS_REPO}/commits')
        resp = requests.get(url, headers=GITHUB_HEADERS,
                            params={'path': script_path, 'per_page': 20}, timeout=10)
        resp.raise_for_status()
        versions = []
        for c in resp.json():
            versions.append({
                'sha':       c['sha'],
                'sha_short': c['sha'][:7],
                'message':   c['commit']['message'].split('\n')[0][:100],
                'author':    c['commit']['author']['name'],
                'date':      c['commit']['author']['date'],
                'url':       c['html_url'],
            })
        return jsonify({'versions': versions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/scripts/update', methods=['POST'])
@login_required
def update_script_version():
    data        = request.json
    server_id   = data.get('server_id')
    script_path = data.get('script_path')
    commit_sha  = data.get('commit_sha', GITHUB_BOT_SCRIPTS_BRANCH)

    if not server_id or not script_path:
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, _, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Not authorized'}), 404

    install_dir = server.get('install_dir')
    if not install_dir:
        return jsonify({'error': 'Installation directory not found'}), 404

    script_name = os.path.basename(script_path)
    dest = os.path.join(install_dir, 'discord-server-setup', 'cogs', script_name)

    if not os.path.isdir(dest):
        return jsonify({'error': f'{script_name} is not installed on this server'}), 404

    ok = download_github_folder(
        GITHUB_BOT_SCRIPTS_USER, GITHUB_BOT_SCRIPTS_REPO,
        commit_sha, script_path, dest
    )
    if not ok:
        return jsonify({'error': 'Download failed'}), 500

    # Persist the installed version SHA
    sha_short = commit_sha[:7] if len(commit_sha) > 7 else commit_sha
    try:
        with open(os.path.join(dest, '.version'), 'w') as vf:
            vf.write(sha_short)
    except OSError:
        pass

    return jsonify({'success': True, 'updated': script_name, 'version': sha_short})


@app.route('/api/bots/check-scripts/<server_id>', methods=['GET'])
@login_required
def check_scripts(server_id):
    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    install_dir = server.get('install_dir')
    if not install_dir:
        return jsonify({'error': 'Installation directory not found'}), 404

    repo_dir = os.path.join(install_dir, 'discord-server-setup')
    cogs_dir = os.path.join(repo_dir, 'cogs')

    if not os.path.exists(cogs_dir):
        return jsonify({'cogs': {}, 'summary': {'total': 0, 'passing': 0, 'failing': 0}})

    cog_names = [
        d for d in os.listdir(cogs_dir)
        if os.path.isdir(os.path.join(cogs_dir, d)) and not d.startswith('__')
    ]

    results = {}
    for cog_name in cog_names:
        cog_dir = os.path.join(cogs_dir, cog_name)
        checks = []

        # Read all .py source files in the cog folder
        all_src = ''
        for fname in os.listdir(cog_dir):
            if fname.endswith('.py') and not fname.startswith('_'):
                try:
                    with open(os.path.join(cog_dir, fname), 'r', encoding='utf-8', errors='replace') as fh:
                        all_src += fh.read() + '\n'
                except Exception:
                    pass

        # 1. Loadable by launcher — needs async def setup(
        has_setup = 'async def setup(' in all_src
        checks.append({
            'name': 'Loadable by launcher',
            'ok': has_setup,
            'detail': '' if has_setup else 'No async def setup() found — launcher will skip this cog',
        })

        # 2. variables.py present (if imported)
        imports_variables = 'import variables' in all_src or 'from variables import' in all_src
        if imports_variables:
            vars_ok = os.path.isfile(os.path.join(cog_dir, 'variables.py'))
            checks.append({
                'name': 'variables.py present',
                'ok': vars_ok,
                'detail': '' if vars_ok else 'variables.py missing from cog folder',
            })

            # 3. Config has top-level guild_id (variables.py reads config['guild_id'])
            guild_ok = 'guild_id' in config
            checks.append({
                'name': "Config key 'guild_id'",
                'ok': guild_ok,
                'detail': '' if guild_ok else (
                    "variables.py reads config['guild_id'] but the config stores it under "
                    "server.guild_id — add a top-level \"guild_id\" key to config.json"
                ),
            })

            # 4. Config has top-level server_name (variables.py reads config['server_name'])
            sname_ok = 'server_name' in config
            checks.append({
                'name': "Config key 'server_name'",
                'ok': sname_ok,
                'detail': '' if sname_ok else (
                    "variables.py reads config['server_name'] but the config stores it under "
                    "server.name — add a top-level \"server_name\" key to config.json"
                ),
            })

        # 5. Database_management installed (if cog depends on it)
        needs_db = 'database_management' in all_src.lower() or 'DatabaseManager' in all_src
        if needs_db:
            db_mgmt_ok = os.path.isdir(os.path.join(cogs_dir, 'Database_management'))
            checks.append({
                'name': 'Database_management installed',
                'ok': db_mgmt_ok,
                'detail': '' if db_mgmt_ok else 'This cog imports DatabaseManager but Database_management is not installed',
            })

            # 6. Database file accessible
            db_path = config.get('paths', {}).get('database_file') or \
                      os.path.join(repo_dir, 'database', 'user_database.db')
            db_ok = os.path.isfile(db_path)
            checks.append({
                'name': 'Database file accessible',
                'ok': db_ok,
                'detail': '' if db_ok else f'Database file not found at {db_path}',
            })

        results[cog_name] = {
            'ok': all(c['ok'] for c in checks),
            'checks': checks,
        }

    passing = sum(1 for v in results.values() if v['ok'])
    return jsonify({
        'cogs': results,
        'summary': {
            'total': len(results),
            'passing': passing,
            'failing': len(results) - passing,
        },
    })


@app.route('/api/bots/remove-script', methods=['POST'])
@login_required
def remove_script():
    data = request.json
    server_id = data.get('server_id')
    script_id = data.get('script_id')

    if not server_id or not script_id:
        return jsonify({'error': 'Missing required fields'}), 400

    _, server, _, _ = _get_authorized_config(server_id, session['user_id'], permission='edit_bots')
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    install_dir = server.get('install_dir')
    if not install_dir:
        return jsonify({'error': 'Installation directory not found'}), 404

    if script_id == 'Database_management':
        return jsonify({'error': 'Database_management is required and cannot be removed'}), 400

    cog_path = os.path.join(install_dir, 'discord-server-setup', 'cogs', script_id)
    if not os.path.isdir(cog_path):
        return jsonify({'error': 'Script not found'}), 404

    # Prevent path traversal
    cogs_dir = os.path.realpath(os.path.join(install_dir, 'discord-server-setup', 'cogs'))
    if not os.path.realpath(cog_path).startswith(cogs_dir + os.sep):
        return jsonify({'error': 'Invalid script path'}), 400

    shutil.rmtree(cog_path)

    return jsonify({'success': True, 'removed': script_id})


# ============================================
# DEBUG — remove before production
# ============================================

@app.route('/api/setup/test-invite/<server_id>')
@login_required
def test_invite(server_id):
    """
    GET this URL in your browser to manually trigger generate_invite.py
    for an already-saved server. Useful for diagnosing browser-open issues.
    e.g. http://localhost:5000/api/setup/test-invite/beastyboy03_1492113607046201414
    """
    username = session['user_id']
    _, server = get_server_or_404(server_id, username)
    if not server:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    repo_dir = os.path.join(server['install_dir'], 'discord-server-setup')
    script = os.path.join(repo_dir, 'setup_cogs', 'generate_invite.py')

    # Run synchronously so we can capture output for debugging
    if not os.path.isfile(script):
        return jsonify({'error': f'Script not found at: {script}'}), 404

    try:
        result = subprocess.run(
            ['python', script],
            capture_output=True, text=True, cwd=repo_dir, timeout=20
        )
        return jsonify({
            'script': script,
            'returncode': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Script timed out after 20s'})
    except Exception as e:
        return jsonify({'error': str(e)})


# ============================================
# FUNCTION TESTS  (proxy — tokens stay server-side)
# ============================================

def _disc_get(token, path, timeout=10):
    """Call Discord REST API v10 with a bot token. Returns (ok, data, status_code)."""
    try:
        r = requests.get(
            f'https://discord.com/api/v10{path}',
            headers={'Authorization': f'Bot {token}', 'Content-Type': 'application/json'},
            timeout=timeout
        )
        try:
            data = r.json()
        except Exception:
            data = {'_raw': r.text[:500]}
        return r.ok, data, r.status_code
    except Exception as exc:
        return False, {'error': str(exc)}, 0


def _disc_post(token, path, payload=None, files=None, timeout=15):
    """POST to Discord REST API v10. Sends JSON unless files= is given (multipart)."""
    try:
        headers = {'Authorization': f'Bot {token}'}
        if files:
            r = requests.post(
                f'https://discord.com/api/v10{path}',
                headers=headers,
                data=payload or {},
                files=files,
                timeout=timeout
            )
        else:
            headers['Content-Type'] = 'application/json'
            r = requests.post(
                f'https://discord.com/api/v10{path}',
                headers=headers,
                json=payload or {},
                timeout=timeout
            )
        try:
            data = r.json()
        except Exception:
            data = {'_raw': r.text[:500]}
        return r.ok, data, r.status_code
    except Exception as exc:
        return False, {'error': str(exc)}, 0


def _disc_patch(token, path, payload=None, timeout=15):
    """PATCH to Discord REST API v10."""
    try:
        r = requests.patch(
            f'https://discord.com/api/v10{path}',
            headers={'Authorization': f'Bot {token}', 'Content-Type': 'application/json'},
            json=payload or {},
            timeout=timeout
        )
        try:
            data = r.json()
        except Exception:
            data = {'_raw': r.text[:500]}
        return r.ok, data, r.status_code
    except Exception as exc:
        return False, {'error': str(exc)}, 0


def _func_test_get_server(server_id):
    """Return (server, config) for an authorized server, or (None, None) on failure."""
    _, server, config, _ = _get_authorized_config(server_id, session['user_id'], permission='view_server')
    return server, config


def _first_bot_token(config):
    """Return the first bot token found in a server config, or None."""
    for bot in config.get('discord_bots', []):
        if bot.get('token'):
            return bot['token'], bot.get('name', 'unknown')
    return None, None


@app.route('/api/func-test/config/<server_id>')
@login_required
def func_test_config(server_id):
    """Return local config verification for a server — no Discord call needed."""
    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    bots = []
    for bot in config.get('discord_bots', []):
        # Count installed cogs from filesystem
        cogs_dir = os.path.join(server.get('install_dir', ''), 'discord-server-setup', 'cogs')
        cog_count = 0
        if os.path.exists(cogs_dir):
            cog_count = sum(
                1 for d in os.listdir(cogs_dir)
                if os.path.isdir(os.path.join(cogs_dir, d)) and not d.startswith('__')
            )
        bots.append({
            'name': bot.get('name', '?'),
            'has_token': bool(bot.get('token')),
            'has_app_id': False,   # not a stored field; derived at runtime
            'cogs_count': cog_count,
            'scripts_count': 0,
            'repo_ready': bool(server.get('install_dir') and os.path.isdir(server.get('install_dir', ''))),
        })

    return jsonify({
        'server_id': server_id,
        'server_name': server.get('server_name', server_id),
        'has_guild_id': bool(server.get('guild_id')),
        'guild_id': server.get('guild_id', ''),
        'has_invite': bool(server.get('invite_url') or server.get('invite')),
        'bots': bots,
        'template': server.get('template', ''),
        'created_at': server.get('created_at', ''),
    })


@app.route('/api/func-test/guild/<server_id>')
@login_required
def func_test_guild(server_id):
    """Check that the bot can reach its Discord guild."""
    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured for this server'}), 400

    token, bot_name = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    ok, data, status = _disc_get(token, f'/guilds/{guild_id}?with_counts=true')
    return jsonify({
        'guild_id': guild_id,
        'bot_used': bot_name,
        'discord_status': status,
        'ok': ok,
        'guild': data if ok else None,
        'guild_name': data.get('name') if ok else None,
        'member_count': data.get('approximate_member_count') if ok else None,
        'icon': data.get('icon') if ok else None,
        'error': data.get('message') if not ok else None,
    })


@app.route('/api/func-test/automod/<server_id>')
@login_required
def func_test_automod(server_id):
    """Return live AutoMod rules from Discord for a server."""
    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured'}), 400

    token, bot_name = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured'}), 400

    ok, data, status = _disc_get(token, f'/guilds/{guild_id}/auto-moderation/rules')
    if not ok:
        return jsonify({'error': data.get('message', 'Discord API error'), 'discord_status': status}), 502

    rules = data if isinstance(data, list) else []
    return jsonify({'rules': rules, 'bot_used': bot_name, 'guild_id': guild_id})


@app.route('/api/func-test/channels/<server_id>')
@login_required
def func_test_channels(server_id):
    """Fetch live channels and compare against the server setup configuration."""
    CHANNEL_TYPES = {0: 'text', 2: 'voice', 4: 'category', 5: 'announcement',
                     13: 'stage', 15: 'forum', 16: 'media'}

    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured for this server'}), 400

    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    # Build the full planned channel list.
    # Two storage formats exist depending on code path:
    #   config.json  → 'custom_categories': [{text_channels, voice_channels, forum_channels}]
    #   servers_data → 'categories':        [{textChannels,  voiceChannels,  forumChannels}]
    # Use whichever has data; prefer config.json translated format first.
    raw_cats    = config.get('custom_categories') or server.get('categories', [])
    translated  = bool(config.get('custom_categories'))  # True = underscore keys

    configured = []

    # Include channels from moderation template and welcome template so they
    # are never flagged as "manually added" — they are always deployed.
    def _add_template_channels(tmpl):
        for cat in (tmpl or {}).get('categories', []):
            cat_name = cat.get('name', '')
            configured.append({'category': cat_name, 'name': cat_name, 'type': 'category'})
            for ch in cat.get('text_channels', []):
                n = ch.get('name', ch) if isinstance(ch, dict) else ch
                configured.append({'category': cat_name, 'name': n, 'type': 'text'})
            for ch in cat.get('voice_channels', []):
                n = ch.get('name', ch) if isinstance(ch, dict) else ch
                configured.append({'category': cat_name, 'name': n, 'type': 'voice'})
        for ch in (tmpl or {}).get('text_channels', []):  # top-level (welcome template)
            n = ch.get('name', ch) if isinstance(ch, dict) else ch
            configured.append({'category': '', 'name': n, 'type': 'text'})

    tmpl_dir = (config.get('paths') or {}).get('template_dir', '')
    if tmpl_dir:
        mod_tmpl_path = os.path.join(tmpl_dir, 'moderation_template.json')
        if os.path.exists(mod_tmpl_path):
            try:
                with open(mod_tmpl_path, 'r', encoding='utf-8') as _f:
                    _add_template_channels(json.load(_f))
            except Exception:
                pass
        if config.get('use_welcome_template'):
            wel_tmpl_path = os.path.join(tmpl_dir, 'welcome_template.json')
            if os.path.exists(wel_tmpl_path):
                try:
                    with open(wel_tmpl_path, 'r', encoding='utf-8') as _f:
                        _add_template_channels(json.load(_f))
                except Exception:
                    pass

    for cat in raw_cats:
        cat_name = cat.get('name', '')
        configured.append({'category': cat_name, 'name': cat_name, 'type': 'category'})
        if translated:
            text_chs  = cat.get('text_channels',  [])
            voice_chs = cat.get('voice_channels', [])
            forum_chs = cat.get('forum_channels', [])
        else:
            text_chs  = cat.get('textChannels',  [])
            voice_chs = cat.get('voiceChannels', [])
            forum_chs = cat.get('forumChannels', [])
        for ch in text_chs:
            configured.append({'category': cat_name, 'name': ch.get('name', ch) if isinstance(ch, dict) else ch, 'type': 'text'})
        for ch in voice_chs:
            configured.append({'category': cat_name, 'name': ch.get('name', ch) if isinstance(ch, dict) else ch, 'type': 'voice'})
        for ch in forum_chs:
            configured.append({'category': cat_name, 'name': ch.get('name', ch) if isinstance(ch, dict) else ch, 'type': 'forum'})

    # Fetch live channels from Discord
    ok, data, status = _disc_get(token, f'/guilds/{guild_id}/channels')
    if not ok:
        return jsonify({'discord_status': status, 'ok': False,
                        'error': data.get('message', 'Discord error')}), 502

    channels = []
    for ch in (data if isinstance(data, list) else []):
        channels.append({
            'id': ch.get('id'),
            'name': ch.get('name'),
            'type': ch.get('type'),
            'type_name': CHANNEL_TYPES.get(ch.get('type'), f"type_{ch.get('type')}"),
            'parent_id': ch.get('parent_id'),
            'position': ch.get('position', 0),
        })

    channels.sort(key=lambda c: c['position'])

    # Match configured → live. Normalize both sides the way Discord does:
    # lowercase, strip leading #, spaces→hyphens, then remove any char Discord
    # strips from channel names (apostrophes, punctuation, etc.).
    def _norm(n): return re.sub(r"[^a-z0-9\-_]", "", n.lower().lstrip('#').replace(' ', '-'))
    live_names = {_norm(ch['name']) for ch in channels}
    for item in configured:
        item['live'] = _norm(item['name']) in live_names

    type_counts = {}
    for ch in channels:
        t = ch['type_name']
        type_counts[t] = type_counts.get(t, 0) + 1

    missing = [c for c in configured if not c['live']]

    # Find channels on Discord not in config (manually added)
    cat_id_to_name = {ch['id']: ch['name'] for ch in channels if ch['type'] == 4}
    configured_names = {_norm(c['name']) for c in configured if c['type'] != 'category'}
    extra = []
    for ch in channels:
        if ch['type'] not in (0, 2, 15):  # text, voice, forum only
            continue
        if _norm(ch['name']) in configured_names:
            continue
        cat_name = cat_id_to_name.get(ch['parent_id'], '') if ch['parent_id'] else ''
        extra.append({
            'name': ch['name'],
            'type': ch['type_name'],
            'category': cat_name,
            'id': ch['id'],
        })

    return jsonify({
        'ok': True,
        'discord_status': status,
        'total': len(channels),
        'type_counts': type_counts,
        'channels': channels,
        'configured': configured,
        'configured_count': len(configured),
        'missing_count': len(missing),
        'missing': missing,
        'extra': extra,
        'extra_count': len(extra),
    })


@app.route('/api/func-test/permissions/<server_id>')
@login_required
def func_test_permissions(server_id):
    """Check the bot's computed guild permissions."""
    PERM_BITS = {
        'ADMINISTRATOR':            1 << 3,
        'VIEW_CHANNEL':             1 << 10,
        'SEND_MESSAGES':            1 << 11,
        'MANAGE_MESSAGES':          1 << 13,
        'EMBED_LINKS':              1 << 14,
        'READ_MESSAGE_HISTORY':     1 << 16,
        'USE_APPLICATION_COMMANDS': 1 << 31,
        'MANAGE_ROLES':             1 << 28,
        'MANAGE_CHANNELS':          1 << 4,
        'KICK_MEMBERS':             1 << 1,
        'BAN_MEMBERS':              1 << 2,
    }

    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured for this server'}), 400

    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    ok_me, me, _ = _disc_get(token, '/users/@me')
    if not ok_me:
        return jsonify({'error': 'Cannot identify bot user via Discord API', 'ok': False}), 502

    bot_id = me.get('id')

    ok_m, member, status_m = _disc_get(token, f'/guilds/{guild_id}/members/{bot_id}')
    if not ok_m:
        return jsonify({'discord_status': status_m, 'ok': False,
                        'error': member.get('message', 'Bot is not a member of this guild')}), 502

    ok_r, roles_data, _ = _disc_get(token, f'/guilds/{guild_id}/roles')
    if not ok_r or not isinstance(roles_data, list):
        return jsonify({'error': 'Cannot fetch guild roles', 'ok': False}), 502

    role_map = {r['id']: int(r.get('permissions', 0)) for r in roles_data}
    member_role_ids = member.get('roles', [])

    everyone_perms = role_map.get(guild_id, 0)
    computed = everyone_perms
    for rid in member_role_ids:
        computed |= role_map.get(rid, 0)

    is_admin = bool(computed & PERM_BITS['ADMINISTRATOR'])
    perms = {name: (is_admin or bool(computed & bit)) for name, bit in PERM_BITS.items()}

    discriminator = me.get('discriminator', '0')
    bot_tag = me.get('username', '?') + (f'#{discriminator}' if discriminator and discriminator != '0' else '')

    return jsonify({
        'ok': True,
        'bot_id': bot_id,
        'bot_tag': bot_tag,
        'computed_permissions': computed,
        'is_administrator': is_admin,
        'permissions': perms,
    })


@app.route('/api/func-test/commands/<server_id>')
@login_required
def func_test_commands(server_id):
    """List slash commands registered for this guild via the Discord API."""
    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured for this server'}), 400

    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    # The application_id equals the bot's user ID — fetch it via /users/@me
    ok_me, me, _ = _disc_get(token, '/users/@me')
    if not ok_me:
        return jsonify({'error': 'Cannot identify bot application via Discord API', 'ok': False}), 502

    app_id = me.get('id')

    ok, data, status = _disc_get(token, f'/applications/{app_id}/guilds/{guild_id}/commands')
    if not ok:
        return jsonify({'discord_status': status, 'ok': False,
                        'error': data.get('message', 'Discord error')}), 502

    commands = []
    for cmd in (data if isinstance(data, list) else []):
        commands.append({
            'id': cmd.get('id'),
            'name': cmd.get('name'),
            'description': cmd.get('description', ''),
            'type': cmd.get('type', 1),
            'options_count': len(cmd.get('options', [])),
        })

    return jsonify({'ok': True, 'discord_status': status,
                    'total': len(commands), 'commands': commands})


@app.route('/api/func-test/fix-channels/<server_id>', methods=['POST'])
@login_required
def func_test_fix_channels(server_id):
    """Create any configured channels that are missing from the Discord guild."""
    import time

    TYPE_MAP = {'text': 0, 'voice': 2, 'forum': 15, 'announcement': 5, 'stage': 13, 'media': 16}

    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured'}), 400

    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured'}), 400

    # Fetch live channels and roles
    ok_ch, live_data, _ = _disc_get(token, f'/guilds/{guild_id}/channels')
    if not ok_ch:
        return jsonify({'error': 'Cannot fetch live channels', 'ok': False}), 502

    def _norm_ch(n): return re.sub(r"[^a-z0-9\-_]", "", n.lower().replace(' ', '-'))
    live_channels = live_data if isinstance(live_data, list) else []
    live_names    = {_norm_ch(ch['name']) for ch in live_channels}
    cat_id_map    = {ch['name'].lower(): ch['id'] for ch in live_channels if ch.get('type') == 4}

    ok_r, roles_data, _ = _disc_get(token, f'/guilds/{guild_id}/roles')
    role_id_map = {}
    if ok_r and isinstance(roles_data, list):
        role_id_map = {r['name'].lower(): r['id'] for r in roles_data}

    # Resolve configured categories (handles both storage formats)
    raw_cats   = config.get('custom_categories') or server.get('categories', [])
    translated = bool(config.get('custom_categories'))

    created, failed, skipped = [], [], []

    for cat in raw_cats:
        cat_name    = cat.get('name', '')
        cat_private = cat.get('private', False)
        cat_roles   = cat.get('roles', [])

        # Create the category itself if missing
        if cat_name.lower() not in cat_id_map:
            cat_payload = {'name': cat_name, 'type': 4}
            if cat_private:
                # Deny @everyone, allow Admin/Moderator + any configured roles
                everyone_id = guild_id  # @everyone role ID == guild ID in Discord
                overwrites = [{'id': everyone_id, 'type': 0, 'deny': str(1 << 10)}]  # VIEW_CHANNEL
                allow_roles = ['Admin', 'Moderator'] + list(cat_roles)
                seen = set()
                for rname in allow_roles:
                    rid = role_id_map.get(rname.lower())
                    if rid and rid not in seen:
                        overwrites.append({'id': rid, 'type': 0, 'allow': str(1 << 10)})
                        seen.add(rid)
                cat_payload['permission_overwrites'] = overwrites
            ok_c, res, _ = _disc_post(token, f'/guilds/{guild_id}/channels', cat_payload)
            if ok_c:
                cat_id_map[cat_name.lower()] = res['id']
                live_names.add(cat_name.lower())
                created.append({'name': cat_name, 'type': 'category', 'id': res['id']})
            else:
                failed.append({'name': cat_name, 'type': 'category',
                               'error': res.get('message', 'unknown')})
            time.sleep(0.3)  # respect Discord rate limits

        cat_discord_id = cat_id_map.get(cat_name.lower())

        if translated:
            ch_groups = [('text', cat.get('text_channels', [])),
                         ('voice', cat.get('voice_channels', [])),
                         ('forum', cat.get('forum_channels', []))]
        else:
            ch_groups = [('text', cat.get('textChannels', [])),
                         ('voice', cat.get('voiceChannels', [])),
                         ('forum', cat.get('forumChannels', []))]

        for ch_type, ch_list in ch_groups:
            for ch in ch_list:
                ch_name  = ch.get('name', ch) if isinstance(ch, dict) else ch
                ch_perms = ch.get('permissions') if isinstance(ch, dict) else None

                if ch_name.lower() in live_names:
                    skipped.append({'name': ch_name, 'reason': 'already exists'})
                    continue

                payload = {'name': ch_name, 'type': TYPE_MAP.get(ch_type, 0)}
                if cat_discord_id:
                    payload['parent_id'] = cat_discord_id

                if ch_perms:
                    overwrites = []
                    if '@everyone' in ch_perms.get('deny', []):
                        overwrites.append({'id': guild_id, 'type': 0,
                                           'deny': str(1 << 10)})   # VIEW_CHANNEL
                    for role_name in ch_perms.get('view', []):
                        rid = role_id_map.get(role_name.lower())
                        if rid:
                            overwrites.append({'id': rid, 'type': 0,
                                               'allow': str(1 << 10)})
                    if overwrites:
                        payload['permission_overwrites'] = overwrites

                ok_c, res, status = _disc_post(token, f'/guilds/{guild_id}/channels', payload)
                if ok_c:
                    created.append({'name': ch_name, 'type': ch_type, 'id': res.get('id')})
                    live_names.add(ch_name.lower())
                else:
                    failed.append({'name': ch_name, 'type': ch_type,
                                   'error': res.get('message', f'HTTP {status}')})
                time.sleep(0.3)

    if created:
        _live_status_cache.pop(server_id, None)

    return jsonify({
        'ok': True,
        'created_count': len(created),
        'failed_count':  len(failed),
        'skipped_count': len(skipped),
        'created': created,
        'failed':  failed,
        'skipped': skipped,
    })


@app.route('/api/func-test/add-to-config/<server_id>', methods=['POST'])
@login_required
def func_test_add_to_config(server_id):
    """Add a manually-created Discord channel into the webapp config so it's tracked."""
    body = request.get_json(silent=True) or {}
    ch_name   = (body.get('channel_name') or '').strip()
    ch_type   = (body.get('channel_type') or 'text').strip()   # 'text' | 'voice' | 'forum'
    cat_name  = (body.get('category_name') or '').strip()

    if not ch_name:
        return jsonify({'error': 'channel_name is required'}), 400
    if ch_type not in ('text', 'voice', 'forum'):
        return jsonify({'error': 'channel_type must be text, voice, or forum'}), 400

    servers_data, server, config, config_path = _get_authorized_config(
        server_id, session['user_id'], permission='edit_server')
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    # ── 1. Update config.json (custom_categories, underscore-key format) ──────
    custom_cats = config.get('custom_categories', [])
    type_key_cfg = {'text': 'text_channels', 'voice': 'voice_channels', 'forum': 'forum_channels'}[ch_type]

    target_cat_cfg = next((c for c in custom_cats if c.get('name') == cat_name), None)
    if target_cat_cfg is None:
        # Category doesn't exist in config — create it
        target_cat_cfg = {'name': cat_name, 'private': False,
                          'text_channels': [], 'voice_channels': [], 'forum_channels': []}
        custom_cats.append(target_cat_cfg)
        config['custom_categories'] = custom_cats

    ch_list_cfg = target_cat_cfg.setdefault(type_key_cfg, [])
    existing_names_cfg = {(c.get('name', c) if isinstance(c, dict) else c).lower() for c in ch_list_cfg}
    if ch_name.lower() not in existing_names_cfg:
        ch_list_cfg.append({'name': ch_name})

    save_server_config(config_path, config)

    # ── 2. Update servers.json (categories, camelCase format) ─────────────────
    type_key_srv = {'text': 'textChannels', 'voice': 'voiceChannels', 'forum': 'forumChannels'}[ch_type]
    sd = load_servers()
    srv_entry = sd.get(server_id, {})
    srv_cats = srv_entry.get('categories', [])

    target_cat_srv = next((c for c in srv_cats if c.get('name') == cat_name), None)
    if target_cat_srv is None:
        target_cat_srv = {'name': cat_name, 'private': False,
                          'textChannels': [], 'voiceChannels': [], 'forumChannels': []}
        srv_cats.append(target_cat_srv)
        srv_entry['categories'] = srv_cats
        sd[server_id] = srv_entry

    ch_list_srv = target_cat_srv.setdefault(type_key_srv, [])
    existing_names_srv = {(c.get('name', c) if isinstance(c, dict) else c).lower() for c in ch_list_srv}
    if ch_name.lower() not in existing_names_srv:
        ch_list_srv.append({'name': ch_name})

    save_servers(sd)

    # Bust the live-status cache so the dashboard drift count updates on next fetch
    _live_status_cache.pop(server_id, None)

    return jsonify({'ok': True, 'added': ch_name, 'category': cat_name, 'type': ch_type})


@app.route('/api/func-test/fix-assets/<server_id>', methods=['POST'])
@login_required
def func_test_fix_assets(server_id):
    """Upload any configured assets (emojis, stickers, soundboard) missing from the guild."""
    import base64 as _b64
    import time

    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured'}), 400

    configured = server.get('server_assets') or config.get('server_assets', {})

    ok_e,  live_emojis,   _ = _disc_get(token, f'/guilds/{guild_id}/emojis')
    ok_s,  live_stickers, _ = _disc_get(token, f'/guilds/{guild_id}/stickers')
    ok_sb, live_sounds,   _ = _disc_get(token, f'/guilds/{guild_id}/soundboard-sounds')

    live_emoji_names   = {e['name'].lower() for e in (live_emojis   if ok_e  and isinstance(live_emojis,   list) else [])}
    live_sticker_names = {s['name'].lower() for s in (live_stickers if ok_s  and isinstance(live_stickers, list) else [])}
    sb_items           = (live_sounds.get('items', []) if isinstance(live_sounds, dict) else live_sounds) if ok_sb else []
    live_sound_names   = {s['name'].lower() for s in (sb_items if isinstance(sb_items, list) else [])}

    created, failed, skipped = [], [], []

    def _strip_data_url(data):
        """If data is a full data URL (data:mime;base64,...) return just the base64 part."""
        if data and data.startswith('data:'):
            return data.split(',', 1)[1] if ',' in data else data
        return data

    def _ensure_data_url(data, mime):
        """Return a proper data URL, stripping any existing prefix first."""
        raw = _strip_data_url(data)
        return f'data:{mime};base64,{raw}'

    # ── Emojis ──────────────────────────────────────────────────────────────
    for emoji in configured.get('emoji', []):
        name      = emoji.get('name', '')
        file_data = emoji.get('file_data')
        if name.lower() in live_emoji_names:
            skipped.append({'type': 'emoji', 'name': name, 'reason': 'already exists'}); continue
        if not file_data:
            failed.append({'type': 'emoji', 'name': name, 'error': 'No image data stored'}); continue
        ext  = (emoji.get('file_name') or 'emoji.png').rsplit('.', 1)[-1].lower()
        mime = {'png':'image/png','jpg':'image/jpeg','jpeg':'image/jpeg',
                'gif':'image/gif','webp':'image/webp'}.get(ext, 'image/png')
        ok_c, res, status = _disc_post(token, f'/guilds/{guild_id}/emojis',
                                       {'name': name, 'image': _ensure_data_url(file_data, mime)})
        if ok_c:
            created.append({'type': 'emoji', 'name': name, 'id': res.get('id')})
            live_emoji_names.add(name.lower())
        else:
            failed.append({'type': 'emoji', 'name': name,
                           'error': res.get('message', f'HTTP {status}')})
        time.sleep(0.3)

    # ── Stickers ─────────────────────────────────────────────────────────────
    for sticker in configured.get('stickers', []):
        name      = sticker.get('name', '')
        file_data = sticker.get('file_data')
        if name.lower() in live_sticker_names:
            skipped.append({'type': 'sticker', 'name': name, 'reason': 'already exists'}); continue
        if not file_data:
            failed.append({'type': 'sticker', 'name': name, 'error': 'No image data stored'}); continue
        file_name = sticker.get('file_name') or 'sticker.png'
        ext       = file_name.rsplit('.', 1)[-1].lower()
        mime      = {'png':'image/png','gif':'image/gif','json':'application/json'}.get(ext, 'image/png')
        file_bytes = _b64.b64decode(_strip_data_url(file_data))
        ok_c, res, status = _disc_post(
            token, f'/guilds/{guild_id}/stickers',
            payload={'name': name, 'description': sticker.get('description', name), 'tags': '⭐'},
            files={'file': (file_name, file_bytes, mime)}
        )
        if ok_c:
            created.append({'type': 'sticker', 'name': name, 'id': res.get('id')})
            live_sticker_names.add(name.lower())
        else:
            failed.append({'type': 'sticker', 'name': name,
                           'error': res.get('message', f'HTTP {status}')})
        time.sleep(0.5)

    # ── Soundboard ───────────────────────────────────────────────────────────
    for sound in configured.get('soundboard', []):
        name       = sound.get('name', '')
        file_data  = sound.get('file_data')
        emoji_name = sound.get('emoji_name') or None
        if name.lower() in live_sound_names:
            skipped.append({'type': 'sound', 'name': name, 'reason': 'already exists'}); continue
        if not file_data:
            failed.append({'type': 'sound', 'name': name, 'error': 'No audio data stored'}); continue
        file_name  = sound.get('file_name') or 'sound.mp3'
        ext        = file_name.rsplit('.', 1)[-1].lower()
        audio_mime = {'mp3':'audio/mpeg','ogg':'audio/ogg','wav':'audio/wav'}.get(ext, 'audio/mpeg')
        sb_payload = {'name': name, 'sound': _ensure_data_url(file_data, audio_mime), 'volume': 1.0}
        if emoji_name:
            sb_payload['emoji_name'] = emoji_name
        ok_c, res, status = _disc_post(
            token, f'/guilds/{guild_id}/soundboard-sounds', sb_payload
        )
        if ok_c:
            created.append({'type': 'sound', 'name': name,
                            'id': res.get('id') or res.get('sound_id')})
            live_sound_names.add(name.lower())
        else:
            failed.append({'type': 'sound', 'name': name,
                           'error': res.get('message', f'HTTP {status}')})
        time.sleep(0.5)

    return jsonify({
        'ok': True,
        'created_count': len(created),
        'failed_count':  len(failed),
        'skipped_count': len(skipped),
        'created': created,
        'failed':  failed,
        'skipped': skipped,
    })


@app.route('/api/func-test/assets/<server_id>')
@login_required
def func_test_assets(server_id):
    """Compare configured assets (emoji, stickers, soundboard) against live Discord guild."""
    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured for this server'}), 400

    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    # Configured assets come from the metadata store (server) or fall back to config
    configured = server.get('server_assets') or config.get('server_assets', {})
    cfg_emoji     = configured.get('emoji', [])
    cfg_stickers  = configured.get('stickers', [])
    cfg_soundboard = configured.get('soundboard', [])

    # Fetch live assets from Discord (best-effort; failures surfaced per-category)
    ok_e,  live_emojis,   _ = _disc_get(token, f'/guilds/{guild_id}/emojis')
    ok_s,  live_stickers, _ = _disc_get(token, f'/guilds/{guild_id}/stickers')
    ok_sb, live_sounds,   _ = _disc_get(token, f'/guilds/{guild_id}/soundboard-sounds')

    def _match(cfg_list, live_list):
        live_names = {str(i.get('name', '')).lower() for i in live_list}
        return [{'name': i.get('name', ''), 'live': i.get('name', '').lower() in live_names}
                for i in cfg_list]

    def _extra(cfg_list, live_list):
        cfg_names = {str(i.get('name', '')).lower() for i in cfg_list}
        return [{'name': i.get('name', ''), 'id': i.get('id', ''), 'animated': i.get('animated', False)}
                for i in live_list if str(i.get('name', '')).lower() not in cfg_names]

    live_e  = live_emojis  if ok_e  and isinstance(live_emojis,  list) else []
    live_s  = live_stickers if ok_s and isinstance(live_stickers, list) else []
    # soundboard endpoint returns {"items": [...]}
    live_sb = (live_sounds.get('items', []) if isinstance(live_sounds, dict) else live_sounds) \
              if ok_sb else []
    if not isinstance(live_sb, list):
        live_sb = []

    return jsonify({
        'ok': True,
        'emoji': {
            'configured': len(cfg_emoji),
            'live_total': len(live_e),
            'discord_ok': ok_e,
            'matches': _match(cfg_emoji, live_e),
            'extra_live': _extra(cfg_emoji, live_e),
        },
        'stickers': {
            'configured': len(cfg_stickers),
            'live_total': len(live_s),
            'discord_ok': ok_s,
            'matches': _match(cfg_stickers, live_s),
            'extra_live': _extra(cfg_stickers, live_s),
        },
        'soundboard': {
            'configured': len(cfg_soundboard),
            'live_total': len(live_sb),
            'discord_ok': ok_sb,
            'matches': _match(cfg_soundboard, live_sb),
        },
    })


@app.route('/api/func-test/roles/<server_id>')
@login_required
def func_test_roles(server_id):
    """Compare configured roles against live Discord guild roles."""
    server, config = _func_test_get_server(server_id)
    if server is None:
        return jsonify({'error': 'Server not found or not authorized'}), 404

    guild_id = server.get('guild_id', '')
    if not guild_id:
        return jsonify({'error': 'No guild_id configured for this server'}), 400

    token, _ = _first_bot_token(config)
    if not token:
        return jsonify({'error': 'No bot token configured for this server'}), 400

    configured_roles = config.get('custom_roles', [])

    ok, live_roles, status = _disc_get(token, f'/guilds/{guild_id}/roles')
    if not ok:
        return jsonify({'discord_status': status, 'ok': False,
                        'error': live_roles.get('message', 'Discord error')}), 502

    live_names = {r['name'].lower() for r in live_roles}
    cfg_names  = {r.get('name', '').lower() for r in configured_roles}

    # Also include roles created by Setup_server.py from templates
    tmpl_dir = (config.get('paths') or {}).get('template_dir', '')
    if tmpl_dir:
        for _tmpl_file in ('moderation_template.json', 'welcome_template.json'):
            _tmpl_path = os.path.join(tmpl_dir, _tmpl_file)
            if os.path.exists(_tmpl_path):
                try:
                    with open(_tmpl_path, 'r', encoding='utf-8') as _f:
                        for _r in json.load(_f).get('roles', []):
                            _name = (_r.get('name', '') if isinstance(_r, dict) else _r)
                            cfg_names.add(_name.lower())
                except Exception:
                    pass

    # Setup_server.py always creates a bots role (hardcoded, not from any template)
    cfg_names.add(config.get('bots_role_name', 'bots').lower())

    role_matches = [
        {
            'name':        r.get('name', ''),
            'color':       r.get('color', '#99aab5'),
            'hoist':       r.get('hoist', False),
            'permissions': r.get('permissions', []),
            'live':        r.get('name', '').lower() in live_names,
        }
        for r in configured_roles
    ]

    # Live roles not in config and not managed (bot-created) and not @everyone
    extra_live = [
        {'name': r['name'], 'id': r['id'], 'managed': r.get('managed', False),
         'position': r.get('position', 0)}
        for r in live_roles
        if r['name'].lower() not in cfg_names
        and r['name'] != '@everyone'
        and not r.get('managed', False)
    ]

    non_managed_live = [r for r in live_roles
                        if r['name'] != '@everyone' and not r.get('managed', False)]

    return jsonify({
        'ok': True,
        'discord_status': status,
        'configured_count': len(configured_roles),
        'live_count': len(non_managed_live),
        'roles': role_matches,
        'extra_live': extra_live,
        'live_all': [{'name': r['name'], 'id': r['id'], 'position': r.get('position', 0),
                      'managed': r.get('managed', False)}
                     for r in sorted(live_roles, key=lambda x: -x.get('position', 0))],
    })


# ============================================
# ABOUT / DISCLAIMER
# ============================================

@app.route('/about')
def about_page():
    return render_template('about.html', username=session.get('username'))


@app.route('/checklist')
def checklist_page():
    return send_from_directory(os.path.dirname(_APP_DIR), 'checklist.html')


# ============================================
# FEEDBACK (GitHub Issues)
# ============================================

@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html', username=session.get('username'))


@app.route('/api/feedback', methods=['POST'])
@login_required
def submit_feedback():
    data = request.get_json(silent=True) or {}
    title    = (data.get('title') or '').strip()
    category = (data.get('category') or 'general').strip()
    body     = (data.get('body') or '').strip()
    contact  = (data.get('contact') or '').strip()

    if not title or not body:
        return jsonify({'error': 'Title and description are required.'}), 400

    token = os.environ.get('GITHUB_TOKEN', '')
    if not token:
        return jsonify({'error': 'Feedback submission is not configured (missing GITHUB_TOKEN).'}), 500

    username = session.get('username', 'anonymous')
    full_body = f"**Category:** {category}\n**Submitted by:** {username}"
    if contact:
        full_body += f"\n**Contact:** {contact}"
    full_body += f"\n\n---\n\n{body}"

    resp = requests.post(
        f'https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/{GITHUB_FEEDBACK_REPO}/issues',
        headers={
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Python-Flask',
        },
        json={'title': title, 'body': full_body, 'labels': [category]},
        timeout=10,
    )
    if resp.status_code in (200, 201):
        issue = resp.json()
        return jsonify({'ok': True, 'issue_url': issue.get('html_url', '')})
    return jsonify({'error': f'GitHub API error: {resp.status_code}'}), 502


# ============================================
# ADMIN / OWNER PORTAL
# ============================================

def _require_admin():
    username = session.get('user_id')
    if not username or username != ADMIN_USERNAME:
        return False
    return True


@app.route('/admin')
def admin_portal():
    if not _require_admin():
        return redirect(url_for('dashboard'))

    all_users   = load_json(USERS_FILE, {})
    all_servers = load_servers()

    total_users   = len(all_users)
    total_servers = len(all_servers)
    total_bots    = sum(len(s.get('bots', [])) for s in all_servers.values())

    user_list = []
    for uname, udata in all_users.items():
        owned = sum(1 for s in all_servers.values() if s.get('owner') == uname)
        user_list.append({
            'username': uname,
            'email':    udata.get('email', ''),
            'servers':  owned,
            'discord':  udata.get('discord_username', ''),
        })
    user_list.sort(key=lambda u: u['servers'], reverse=True)

    recent_feedback = []
    token = os.environ.get('GITHUB_TOKEN', '')
    if token:
        try:
            r = requests.get(
                f'https://api.github.com/repos/{GITHUB_BOT_SCRIPTS_USER}/{GITHUB_FEEDBACK_REPO}/issues',
                headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'Python-Flask'},
                params={'state': 'open', 'per_page': 10},
                timeout=5,
            )
            if r.status_code == 200:
                recent_feedback = [{'title': i['title'], 'url': i['html_url'], 'state': i['state'], 'created_at': i['created_at'][:10]} for i in r.json()]
        except Exception:
            pass

    return render_template('admin.html',
        username=session.get('username'),
        total_users=total_users,
        total_servers=total_servers,
        total_bots=total_bots,
        user_list=user_list,
        recent_feedback=recent_feedback,
    )


# ============================================
# AGENT WEBSOCKET NAMESPACE
# ============================================

AGENT_MIN_VERSION = '1.0.0'

def _agent_token_to_user(token: str):
    """Look up which username owns this agent token. Returns None if invalid."""
    if not token:
        return None
    users = load_users()
    return next((u for u, d in users.items() if d.get('agent_token') == token), None)

@socketio.on('connect', namespace='/agent')
def _agent_connect(auth):
    token   = (auth or {}).get('token', '') or request.args.get('token', '')
    version = (auth or {}).get('version', '0.0.0') or request.headers.get('X-Agent-Version', '0.0.0')
    username = _agent_token_to_user(token)
    if not username:
        emit('auth_failed', {'reason': 'Invalid or expired token'})
        _sio_disconnect()
        return
    with _agents_lock:
        _agents[request.sid] = {
            'username':     username,
            'version':      version,
            'bots':         [],
            'connected_at': time.time(),
            'last_seen':    time.time(),
        }
    emit('version_check', {'min_version': AGENT_MIN_VERSION})

@socketio.on('disconnect', namespace='/agent')
def _agent_disconnect():
    with _agents_lock:
        _agents.pop(request.sid, None)

@socketio.on('register', namespace='/agent')
def _agent_register(data):
    with _agents_lock:
        agent = _agents.get(request.sid)
        if agent:
            agent['bots']      = data.get('bots', [])
            agent['last_seen'] = time.time()

@socketio.on('status', namespace='/agent')
def _agent_status_update(data):
    with _agents_lock:
        agent = _agents.get(request.sid)
        if agent:
            agent['bots']      = data.get('bots', [])
            agent['last_seen'] = time.time()

@socketio.on('command_result', namespace='/agent')
def _agent_command_result(data):
    pass  # reserved for forwarding to user web session in a future update


# ── Agent HTTP endpoints ──────────────────────────────────────────────────────

@app.route('/api/agent/token', methods=['GET'])
@login_required
def api_agent_token():
    """Get (or generate) the current user's agent token."""
    users    = load_users()
    username = session['user_id']
    user     = users.get(username, {})
    token    = user.get('agent_token', '')
    created_at = user.get('agent_token_created_at', '')
    if not token:
        token               = secrets.token_urlsafe(32)
        created_at          = datetime.now(timezone.utc).isoformat()
        user['agent_token']            = token
        user['agent_token_created_at'] = created_at
        users[username]     = user
        save_users(users)
    return jsonify({'token': token, 'created_at': created_at})


@app.route('/api/agent/token/regenerate', methods=['POST'])
@login_required
@csrf_protect
def api_agent_token_regenerate():
    """Regenerate (rotate) the agent token — old agents will be disconnected."""
    users    = load_users()
    username = session['user_id']
    user     = users.get(username, {})
    token                          = secrets.token_urlsafe(32)
    user['agent_token']            = token
    user['agent_token_created_at'] = datetime.now(timezone.utc).isoformat()
    users[username]     = user
    save_users(users)
    # Kick any agent currently using the old token
    with _agents_lock:
        stale = [sid for sid, a in _agents.items() if a['username'] == username]
    for sid in stale:
        socketio.emit('auth_failed', {'reason': 'Token regenerated'}, namespace='/agent', to=sid)
        socketio.server.disconnect(sid, namespace='/agent')
    return jsonify({'token': token})


@app.route('/api/agent/status', methods=['GET'])
def api_agent_status():
    """Return connection status and bot list for the current user's agent."""
    if 'user_id' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    username = session['user_id']
    with _agents_lock:
        agent = next((a for a in _agents.values() if a['username'] == username), None)
    if not agent:
        return jsonify({'connected': False, 'bots': []})
    return jsonify({
        'connected':     True,
        'version':       agent.get('version'),
        'bots':          agent.get('bots', []),
        'last_seen':     agent.get('last_seen'),
        'connected_at':  agent.get('connected_at'),
    })


@app.route('/api/agent/command', methods=['POST'])
@csrf_protect
def api_agent_command():
    """Send a start/stop/restart command to the current user's agent."""
    if 'username' not in session:
        return jsonify({'error': 'Not logged in'}), 401
    username = session['username']
    data     = request.get_json(silent=True) or {}
    action   = data.get('action', '')
    bot_name = data.get('bot', '')
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'error': f'Unknown action: {action}'}), 400
    with _agents_lock:
        sid = next((s for s, a in _agents.items() if a['username'] == username), None)
    if not sid:
        return jsonify({'error': 'Agent not connected'}), 404
    socketio.emit('command', {'action': action, 'bot': bot_name}, namespace='/agent', to=sid)
    return jsonify({'ok': True})


# ============================================
# REACT FRONTEND CATCH-ALL
# ============================================

_REACT_DIST = os.path.join(_APP_DIR, 'static', 'dist')

@app.route('/app/', defaults={'path': ''})
@app.route('/app/<path:path>')
def react_app(path):
    """Serve the React frontend from /app/. API routes are unaffected."""
    file_path = os.path.join(_REACT_DIST, path)
    if path and os.path.isfile(file_path):
        return send_from_directory(_REACT_DIST, path)
    return send_from_directory(_REACT_DIST, 'index.html')


# ============================================
# ENTRY POINT
# ============================================

if __name__ == '__main__':
    print(f'[OAuth] Discord: {"configured" if DISCORD_CLIENT_ID else "NOT configured (add DISCORD_CLIENT_ID to .env)"}')
    print('[server] For WebSocket support run: python server.py')
    app.run(host='0.0.0.0', port=5000, debug=False)