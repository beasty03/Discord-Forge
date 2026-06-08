#!/usr/bin/env python3
"""
DiscordForge Agent  v1.0.0
Runs on the user's machine — manages Discord bots locally and reports
status to the DiscordForge server via WebSocket.

Usage:
    python agent.py --server http://discordforge.duckdns.org:5000 --token YOUR_TOKEN
    python agent.py --server http://localhost:5000 --token YOUR_TOKEN --bot-dir ./my-bots
    python agent.py --version
"""

AGENT_VERSION = '1.0.0'
MIN_PYTHON    = (3, 8)

import sys
import os

# ── Python version guard ──────────────────────────────────────────────────────
if sys.version_info < MIN_PYTHON:
    sys.exit(f'DiscordForge Agent requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+')

# ── Auto-install dependencies ─────────────────────────────────────────────────
def _ensure_deps():
    required = {'python-socketio[client]': 'socketio', 'requests': 'requests'}
    missing  = [pkg for pkg, mod in required.items() if not _importable(mod)]
    if not missing:
        return
    print('[agent] Installing dependencies...')
    import subprocess
    subprocess.check_call(
        [sys.executable, '-m', 'pip', 'install', '--quiet'] + missing
    )
    print('[agent] Dependencies ready.\n')

def _importable(mod):
    try:
        __import__(mod)
        return True
    except ImportError:
        return False

_ensure_deps()

# ── Imports (after deps are guaranteed) ──────────────────────────────────────
import json
import time
import threading
import subprocess
import argparse
import signal
from pathlib import Path

import socketio as _sio_lib
import requests

# ── CLI args ──────────────────────────────────────────────────────────────────
def _parse_args():
    p = argparse.ArgumentParser(
        description='DiscordForge Agent — manages your Discord bots locally',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent.py --server http://discordforge.duckdns.org:5000 --token abc123
  python agent.py --server http://localhost:5000 --token abc123 --bot-dir ./bot
        """,
    )
    p.add_argument('--server',  required=False, help='DiscordForge server URL')
    p.add_argument('--token',   required=False, help='Agent token from your dashboard')
    p.add_argument('--bot-dir', default=None,   help='Directory containing config*.json and launcher.py (default: agent directory)')
    p.add_argument('--version', action='store_true', help='Print version and exit')
    return p.parse_args()


# ── Bot process ───────────────────────────────────────────────────────────────
class BotProcess:
    MAX_RESTARTS   = 5
    RESTART_WINDOW = 300  # seconds — reset counter if stable for this long

    def __init__(self, name: str, config_path: str, launcher: str):
        self.name        = name
        self.config_path = config_path
        self.launcher    = launcher
        self.process     = None
        self.log_lines   = []
        self.lock        = threading.Lock()
        self.status      = 'stopped'
        self.started_at  = None
        self._crash_count = 0
        self._last_crash  = 0.0
        self.on_change   = None  # callback(bot) — called on every status change

    # ── Internal ──────────────────────────────────────────────────────────────

    def _alive(self):
        return self.process is not None and self.process.poll() is None

    def _emit(self):
        if self.on_change:
            try:
                self.on_change(self)
            except Exception:
                pass

    def _log(self, msg: str):
        with self.lock:
            self.log_lines.append(msg)
            if len(self.log_lines) > 600:
                self.log_lines = self.log_lines[-600:]

    def _read_output(self):
        try:
            for raw in self.process.stdout:
                line = raw.rstrip()
                self._log(line)
                low = line.lower()
                if 'logged in as' in low or 'ready' in low:
                    if self.status != 'running':
                        self.status       = 'running'
                        self._crash_count = 0
                        self._emit()
                elif 'error' in low and self.status == 'starting':
                    self.status = 'error'
                    self._emit()
        except Exception:
            pass
        rc = self.process.wait()
        crashed = self.status not in ('stopped', 'error')
        self.status = 'stopped'
        self._emit()
        if crashed:
            self._maybe_restart()

    def _maybe_restart(self):
        now = time.time()
        if now - self._last_crash > self.RESTART_WINDOW:
            self._crash_count = 0
        self._last_crash   = now
        self._crash_count += 1
        if self._crash_count > self.MAX_RESTARTS:
            msg = (f'[agent] Bot "{self.name}" crashed {self._crash_count}× — '
                   f'auto-restart disabled. Restart manually from your dashboard.')
            self._log(msg)
            self._emit()
            return
        delay = min(5 * self._crash_count, 60)
        msg = (f'[agent] Bot "{self.name}" crashed '
               f'({self._crash_count}/{self.MAX_RESTARTS}). Restarting in {delay}s…')
        self._log(msg)
        self._emit()
        threading.Thread(
            target=lambda: (time.sleep(delay), self.start()),
            daemon=True,
        ).start()

    # ── Public ────────────────────────────────────────────────────────────────

    def start(self):
        if self._alive():
            return False, 'Already running'
        if not Path(self.launcher).exists():
            return False, f'launcher.py not found at {self.launcher}'
        env = {**os.environ, 'BOT_CONFIG': self.config_path, 'PYTHONIOENCODING': 'utf-8'}
        try:
            self.process = subprocess.Popen(
                [sys.executable, self.launcher, '--bot', self.name],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1,
                cwd=str(Path(self.launcher).parent),
                env=env,
            )
            self.status     = 'starting'
            self.started_at = time.time()
            self._emit()
            threading.Thread(target=self._read_output, daemon=True).start()
            return True, 'Started'
        except Exception as e:
            self.status = 'error'
            self._emit()
            return False, str(e)

    def stop(self):
        if not self._alive():
            self.status = 'stopped'
            return False, 'Not running'
        self._crash_count = self.MAX_RESTARTS  # prevent auto-restart on manual stop
        try:
            self.process.terminate()
            try:
                self.process.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.status = 'stopped'
            self._emit()
            return True, 'Stopped'
        except Exception as e:
            return False, str(e)

    def uptime_str(self):
        if not self._alive() or not self.started_at:
            return None
        s  = int(time.time() - self.started_at)
        h, m, ss = s // 3600, (s % 3600) // 60, s % 60
        return f'{h}h {m}m' if h else f'{m}m {ss}s' if m else f'{ss}s'

    def info(self):
        alive = self._alive()
        if not alive and self.status not in ('stopped', 'error'):
            self.status = 'stopped'
        with self.lock:
            logs = list(self.log_lines[-200:])
        return {
            'name':   self.name,
            'status': self.status,
            'pid':    self.process.pid if alive else None,
            'uptime': self.uptime_str(),
            'logs':   logs,
        }


# ── Agent ─────────────────────────────────────────────────────────────────────
class Agent:
    def __init__(self, server_url: str, token: str, bot_dir: Path):
        self.server_url = server_url.rstrip('/')
        self.token      = token
        self.bot_dir    = bot_dir
        self.bots: dict[str, BotProcess] = {}
        self._sio       = _sio_lib.Client(
            reconnection=True,
            reconnection_attempts=0,   # retry forever
            reconnection_delay=3,
            reconnection_delay_max=30,
            logger=False,
            engineio_logger=False,
        )
        self._running   = True
        self._setup_events()
        self._discover()

    # ── Bot discovery ─────────────────────────────────────────────────────────

    def _discover(self):
        launcher = self.bot_dir / 'launcher.py'
        for cfg in sorted(self.bot_dir.glob('config*.json')):
            try:
                data = json.loads(cfg.read_text(encoding='utf-8'))
                stem = cfg.stem
                raw  = stem[len('config'):].lstrip('_') or 'main'
                name = data.get('bot_name', raw)
                if name not in self.bots:
                    bot          = BotProcess(name, str(cfg), str(launcher))
                    bot.on_change = self._on_bot_change
                    self.bots[name] = bot
                    print(f'  + bot: {name}  ({cfg.name})')
            except Exception as e:
                print(f'  ! skip {cfg.name}: {e}')
        if not self.bots:
            print('  ! No config*.json files found in', self.bot_dir)
            print('    Add a config.json (or config_<name>.json) to this directory.')

    # ── SocketIO events ───────────────────────────────────────────────────────

    def _setup_events(self):
        sio = self._sio

        @sio.event(namespace='/agent')
        def connect():
            print('[agent] Connected to DiscordForge')
            sio.emit('register', {
                'token':   self.token,
                'version': AGENT_VERSION,
                'bots':    [b.info() for b in self.bots.values()],
            }, namespace='/agent')

        @sio.event(namespace='/agent')
        def connect_error(data):
            print(f'[agent] Connection error: {data}')

        @sio.event(namespace='/agent')
        def disconnect():
            print('[agent] Disconnected — will reconnect…')

        @sio.on('auth_failed', namespace='/agent')
        def on_auth_failed(data):
            print(f'\n[agent] Authentication failed: {data.get("reason", "invalid token")}')
            print('        Check your token in the DiscordForge dashboard.\n')
            self._running = False
            sio.disconnect()

        @sio.on('version_check', namespace='/agent')
        def on_version_check(data):
            min_v = data.get('min_version', '0.0.0')
            if _ver(AGENT_VERSION) < _ver(min_v):
                print(f'\n[agent] !! Update required — you: v{AGENT_VERSION}  min: v{min_v}')
                print('[agent] !! Download the latest agent from your DiscordForge dashboard.\n')

        @sio.on('command', namespace='/agent')
        def on_command(data):
            action   = data.get('action', '')
            bot_name = data.get('bot', '')
            bot      = self.bots.get(bot_name)
            if not bot:
                sio.emit('command_result', {
                    'ok': False, 'msg': f'Bot "{bot_name}" not found', 'bot': bot_name,
                }, namespace='/agent')
                return
            if action == 'start':
                ok, msg = bot.start()
            elif action == 'stop':
                ok, msg = bot.stop()
            elif action == 'restart':
                bot.stop()
                time.sleep(0.8)
                ok, msg = bot.start()
            else:
                ok, msg = False, f'Unknown action: {action}'
            sio.emit('command_result', {
                'ok': ok, 'msg': msg, 'bot': bot_name,
            }, namespace='/agent')

        @sio.on('ping', namespace='/agent')
        def on_ping(_data):
            sio.emit('status', {
                'bots': [b.info() for b in self.bots.values()],
            }, namespace='/agent')

    # ── Status push ───────────────────────────────────────────────────────────

    def _on_bot_change(self, _bot):
        if self._sio.connected:
            try:
                self._sio.emit('status', {
                    'bots': [b.info() for b in self.bots.values()],
                }, namespace='/agent')
            except Exception:
                pass

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(self):
        url = self.server_url
        print(f'[agent] Connecting to {url} …')
        try:
            self._sio.connect(
                url,
                namespaces=['/agent'],
                transports=['websocket'],
                auth={'token': self.token, 'version': AGENT_VERSION},
                wait_timeout=10,
            )
        except Exception as e:
            print(f'[agent] Could not connect: {e}')
            print(f'[agent] Retrying every 3-30s — Ctrl+C to quit\n')
            # python-socketio handles reconnection automatically after first connect attempt
            # Block here and wait for user to kill if unreachable
            try:
                while self._running:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
            return

        try:
            self._sio.wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        print('\n[agent] Shutting down bots…')
        self._running = False
        for bot in self.bots.values():
            if bot.status not in ('stopped', 'error'):
                bot.stop()
        if self._sio.connected:
            self._sio.disconnect()
        print('[agent] Done.')


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ver(v: str):
    try:
        return tuple(int(x) for x in v.split('.'))
    except Exception:
        return (0, 0, 0)


def _load_config(bot_dir: Path):
    """Load token/server from agent.cfg if present."""
    cfg = bot_dir / 'agent.cfg'
    if not cfg.exists():
        return {}
    out = {}
    for line in cfg.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' in line:
            k, _, v = line.partition('=')
            out[k.strip().lower()] = v.strip()
    return out


def _save_config(bot_dir: Path, server: str, token: str):
    cfg = bot_dir / 'agent.cfg'
    cfg.write_text(
        f'# DiscordForge Agent config — do not share this file\n'
        f'server={server}\n'
        f'token={token}\n',
        encoding='utf-8',
    )
    print(f'[agent] Saved config to {cfg}')


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    args = _parse_args()

    if args.version:
        print(f'DiscordForge Agent v{AGENT_VERSION}')
        return

    print()
    print(f'  DiscordForge Agent  v{AGENT_VERSION}')
    print(f'  Python {sys.version.split()[0]}')
    print()

    bot_dir = Path(args.bot_dir).resolve() if args.bot_dir else Path(__file__).parent.resolve()

    # Load saved config, CLI flags override it
    saved   = _load_config(bot_dir)
    server  = args.server or saved.get('server', '')
    token   = args.token  or saved.get('token',  '')

    # Interactive setup if no server/token provided
    if not server:
        print('  No --server provided.')
        server = input('  DiscordForge server URL: ').strip()
    if not token:
        print('  No --token provided.')
        print('  Get your token from: Dashboard → Account → Agent Token')
        token = input('  Agent token: ').strip()

    if not server or not token:
        sys.exit('  Error: server URL and token are required.')

    # Persist config so user only needs to type it once
    if not (args.server and args.token):
        _save_config(bot_dir, server, token)

    print(f'  Bot directory: {bot_dir}')
    print(f'  Server:        {server}')
    print(f'  Token:         {token[:8]}…')
    print()

    agent = Agent(server, token, bot_dir)

    # Graceful Ctrl+C on Windows
    def _sigint(_sig, _frame):
        agent.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, _sigint)

    agent.run()


if __name__ == '__main__':
    main()
