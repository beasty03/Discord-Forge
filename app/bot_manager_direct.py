#!/usr/bin/env python3
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

# ── Shared secret for Flask → bot-manager calls ───────────────────────────────
_SECRET_FILE = BASE_DIR / '.botmgr_secret'

def _load_or_create_secret():
    import secrets as _sec
    if _SECRET_FILE.exists():
        return _SECRET_FILE.read_text().strip()
    secret = _sec.token_hex(32)
    _SECRET_FILE.write_text(secret)
    return secret

_BOTMGR_SECRET = _load_or_create_secret()

def _dlog(msg):
    if DEBUG:
        print(f'[DBG] {msg}', flush=True)


# ── Bot process ───────────────────────────────────────────────────────────────
class BotProcess:
    MAX_RESTARTS   = 5
    RESTART_WINDOW = 300  # reset crash counter if bot stays up longer than this (seconds)

    def __init__(self, name, config_path):
        self.name          = name
        self.config_path   = config_path
        self.process       = None
        self.log_lines     = []
        self.lock          = threading.Lock()
        self.status        = 'stopped'
        self.started_at    = None
        self._log_th       = None
        self._crash_count  = 0
        self._last_crash   = 0.0

    def _is_alive(self):
        return self.process is not None and self.process.poll() is None

    def _notify_crash(self, msg: str):
        """POST a crash notification to the Flask app so it can fire user webhooks."""
        try:
            import urllib.request as _ur, json as _json
            secret_path = BASE_DIR / '.botmgr_secret'
            secret = secret_path.read_text().strip() if secret_path.exists() else ''
            payload = _json.dumps({'bot_name': self.name, 'message': msg}).encode()
            req = _ur.Request('http://127.0.0.1:5000/api/internal/bot-crash-alert',
                              data=payload,
                              headers={'Content-Type': 'application/json',
                                       'X-Manager-Secret': secret})
            _ur.urlopen(req, timeout=3)
        except Exception:
            pass

    def _maybe_restart(self):
        now = time.time()
        if now - self._last_crash > self.RESTART_WINDOW:
            self._crash_count = 0
        self._last_crash = now
        self._crash_count += 1
        if self._crash_count > self.MAX_RESTARTS:
            msg = (f'Bot "{self.name}" crashed {self._crash_count} times — '
                   f'auto-restart disabled. Restart manually.')
            with self.lock:
                self.log_lines.append(f'[BOT-MANAGER] {msg}')
            self._notify_crash(msg)
            return
        delay = min(5 * self._crash_count, 60)
        msg = (f'Bot "{self.name}" crashed (attempt {self._crash_count}/'
               f'{self.MAX_RESTARTS}). Restarting in {delay}s…')
        with self.lock:
            self.log_lines.append(f'[BOT-MANAGER] {msg}')
        self._notify_crash(msg)
        def _delayed():
            time.sleep(delay)
            self.start()
        threading.Thread(target=_delayed, daemon=True).start()

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
                    self._crash_count = 0  # successful start resets crash counter
                elif 'error' in low and self.status == 'starting':
                    self.status = 'error'
        except Exception:
            pass
        self.process.wait()
        crashed = self.status not in ('stopped', 'error')
        self.status = 'stopped'
        if crashed:
            self._maybe_restart()

    def stop(self):
        if not self._is_alive():
            self.status = 'stopped'
            return False, 'Not running'
        self._crash_count = self.MAX_RESTARTS  # prevent restart on manual stop
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


# ── Cloud bot process (server-side, delegates from Flask) ─────────────────────
class CloudBotProcess:
    """Runs launcher.py on the server — registered by Flask for cloud-hosted bots."""
    def __init__(self, server_id, bot_name, launcher, cwd):
        self.server_id  = server_id
        self.bot_name   = bot_name
        self.launcher   = launcher  # absolute path to launcher.py
        self.cwd        = cwd       # discord-server-setup directory
        self.process    = None
        self.log_lines  = []
        self.lock       = threading.Lock()
        self.status     = 'stopped'
        self.started_at = None
        self._log_th    = None

    def key(self):
        return f'{self.server_id}:{self.bot_name}'

    def _is_alive(self):
        return self.process is not None and self.process.poll() is None

    def start(self):
        if self._is_alive():
            return False, 'Already running'
        try:
            env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
            self.process = subprocess.Popen(
                [sys.executable, self.launcher, '--bot', self.bot_name],
                cwd=self.cwd,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env,
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
            if sys.platform == 'win32':
                subprocess.call(
                    ['taskkill', '/F', '/T', '/PID', str(self.process.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
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
            'server_id': self.server_id,
            'name':      self.bot_name,
            'status':    self.status,
            'pid':       self.process.pid if alive else None,
            'uptime':    self.uptime_str(),
            'logs':      logs,
        }


# ── Registry ──────────────────────────────────────────────────────────────────
_bots: dict = {}
_bots_lock   = threading.Lock()

# Cloud bots registered by Flask (server-hosted)
_cloud_bots: dict = {}
_cloud_lock       = threading.Lock()

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

    def _check_secret(self):
        """Return True if the request carries the correct shared secret."""
        return self.headers.get('X-Manager-Secret', '') == _BOTMGR_SECRET

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path in ('/', '/index.html'):
            _html_resp(self); return

        if not self._check_secret():
            _json_resp(self, 401, {'error': 'Unauthorized'}); return

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

        # ── Cloud bot routes ──────────────────────────────────────────────────
        if path == '/api/cloud/status':
            with _cloud_lock:
                infos = [b.info() for b in _cloud_bots.values()]
            _json_resp(self, 200, {'bots': infos}); return

        # GET /api/cloud/<server_id>/<bot_name>/log
        if (len(parts) == 5 and parts[:2] == ['api', 'cloud'] and parts[4] == 'log'):
            key = f'{urllib.parse.unquote(parts[2])}:{urllib.parse.unquote(parts[3])}'
            with _cloud_lock:
                bot = _cloud_bots.get(key)
            if not bot:
                _json_resp(self, 404, {'error': 'Cloud bot not found'}); return
            with bot.lock:
                logs = list(bot.log_lines[-300:])
            _json_resp(self, 200, {'logs': logs}); return

        _json_resp(self, 404, {'error': 'Not found'})

    def do_POST(self):
        path   = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get('Content-Length', 0))
        body   = self.rfile.read(length)

        if not self._check_secret():
            _json_resp(self, 401, {'error': 'Unauthorized'}); return

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

        # ── Cloud bot routes (delegated by Flask) ─────────────────────────────
        # POST /api/cloud/start  {server_id, bot_name, launcher, cwd}
        if path == '/api/cloud/start':
            try:
                data      = json.loads(body) if body else {}
                server_id = data.get('server_id', '')
                bot_name  = data.get('bot_name', '')
                launcher  = data.get('launcher', '')
                cwd       = data.get('cwd', '')
                if not all([server_id, bot_name, launcher, cwd]):
                    _json_resp(self, 400, {'error': 'Missing required fields'}); return
                key = f'{server_id}:{bot_name}'
                with _cloud_lock:
                    if key not in _cloud_bots:
                        _cloud_bots[key] = CloudBotProcess(server_id, bot_name, launcher, cwd)
                    bot = _cloud_bots[key]
                ok, msg = bot.start()
                _json_resp(self, 200, {'ok': ok, 'msg': msg, 'info': bot.info()}); return
            except Exception as e:
                _json_resp(self, 400, {'error': str(e)}); return

        # POST /api/cloud/stop  {server_id, bot_name}
        if path == '/api/cloud/stop':
            try:
                data      = json.loads(body) if body else {}
                server_id = data.get('server_id', '')
                bot_name  = data.get('bot_name', '')
                key = f'{server_id}:{bot_name}'
                with _cloud_lock:
                    bot = _cloud_bots.get(key)
                if not bot:
                    _json_resp(self, 404, {'error': 'Cloud bot not registered'}); return
                ok, msg = bot.stop()
                _json_resp(self, 200, {'ok': ok, 'msg': msg, 'info': bot.info()}); return
            except Exception as e:
                _json_resp(self, 400, {'error': str(e)}); return

        # POST /api/cloud/restart  {server_id, bot_name, launcher?, cwd?}
        if path == '/api/cloud/restart':
            try:
                data      = json.loads(body) if body else {}
                server_id = data.get('server_id', '')
                bot_name  = data.get('bot_name', '')
                launcher  = data.get('launcher', '')
                cwd       = data.get('cwd', '')
                key = f'{server_id}:{bot_name}'
                with _cloud_lock:
                    bot = _cloud_bots.get(key)
                    if not bot and launcher and cwd:
                        bot = CloudBotProcess(server_id, bot_name, launcher, cwd)
                        _cloud_bots[key] = bot
                if not bot:
                    _json_resp(self, 404, {'error': 'Cloud bot not registered'}); return
                bot.stop()
                time.sleep(0.5)
                ok, msg = bot.start()
                _json_resp(self, 200, {'ok': ok, 'msg': msg, 'info': bot.info()}); return
            except Exception as e:
                _json_resp(self, 400, {'error': str(e)}); return

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
        _server = _ThreadingServer(('127.0.0.1', PORT), _Handler)
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
