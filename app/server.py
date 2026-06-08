"""
DiscordForge — production entry point.
Runs Flask + Flask-SocketIO with gevent (async, WebSocket support).
Replaces: py -m waitress --port=5000 app:app

Usage (from the app/ directory):
    python server.py
    python server.py --port 5000
    python server.py --host 127.0.0.1 --port 5000
"""
import gevent.monkey
gevent.monkey.patch_all()  # must be first — patches sockets for async I/O

import argparse
import sys
import os

def _parse():
    p = argparse.ArgumentParser()
    p.add_argument('--host', default='0.0.0.0')
    p.add_argument('--port', type=int, default=5000)
    p.add_argument('--debug', action='store_true')
    return p.parse_args()

if __name__ == '__main__':
    args = _parse()

    # Must import AFTER monkey_patch
    from app import app, socketio

    print(f'[DiscordForge] Starting server (gevent, WebSocket enabled)')
    print(f'[DiscordForge] http://{args.host}:{args.port}')
    print()

    socketio.run(
        app,
        host=args.host,
        port=args.port,
        debug=args.debug,
        use_reloader=False,
        log_output=False,
    )
