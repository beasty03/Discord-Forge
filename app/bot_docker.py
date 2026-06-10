"""
Docker backend for bot management.

Active when BOT_RUNNER=docker in the environment.
Each bot runs as a sibling container named df-bot-{server_id[:12]}-{bot_name}.

Requires:
  - /var/run/docker.sock mounted in the Flask container (see docker-compose.yml)
  - DOCKER_NETWORK env var set to the compose network name (default: discordforge_default)
  - BOT_IMAGE env var set to the bot image name (default: discordforge-bot)
  - The bot image built from discord-server-setup-template/Dockerfile
"""

import json
import os
import re

_BOT_RUNNER  = os.environ.get('BOT_RUNNER', 'subprocess')
_BOT_IMAGE   = os.environ.get('BOT_IMAGE',  'discordforge-bot')
_NETWORK     = os.environ.get('DOCKER_NETWORK', 'discordforge_default')
_FORGE_URL   = os.environ.get('FORGE_API_URL',  'http://discordforge:5000')


def is_docker_mode() -> bool:
    return _BOT_RUNNER == 'docker'


def _client():
    import docker
    return docker.from_env()


def _container_name(server_id: str, bot_name: str) -> str:
    safe = re.sub(r'[^a-z0-9-]', '-', bot_name.lower())
    return f'df-bot-{server_id[:12]}-{safe}'


def start(server_id: str, bot_name: str, bot_token: str, config: dict) -> tuple:
    """
    Start a bot container. Removes any existing stopped container with the same name first.
    Returns (ok: bool, message: str).
    """
    client = _client()
    name   = _container_name(server_id, bot_name)

    try:
        existing = client.containers.get(name)
        if existing.status == 'running':
            return False, 'Already running'
        existing.remove()
    except Exception:
        pass  # docker.errors.NotFound — nothing to clean up

    config_json = json.dumps(config)
    try:
        client.containers.run(
            _BOT_IMAGE,
            name=name,
            detach=True,
            restart_policy={'Name': 'unless-stopped'},
            environment={
                'BOT_CONFIG_JSON': config_json,
                'BOT_NAME':        bot_name,
                'FORGE_API_URL':   _FORGE_URL,
            },
            labels={
                'discordforge.bot':       '1',
                'discordforge.server_id': server_id,
                'discordforge.bot_name':  bot_name,
            },
            network=_NETWORK,
        )
        return True, 'Started'
    except Exception as e:
        return False, str(e)


def stop(server_id: str, bot_name: str) -> tuple:
    """Stop a running bot container. Returns (ok, message)."""
    client = _client()
    name   = _container_name(server_id, bot_name)
    try:
        c = client.containers.get(name)
        c.stop(timeout=10)
        return True, 'Stopped'
    except Exception as e:
        return False, str(e)


def restart(server_id: str, bot_name: str, bot_token: str, config: dict) -> tuple:
    """Stop and re-create the bot container with fresh config. Returns (ok, message)."""
    stop(server_id, bot_name)
    client = _client()
    name   = _container_name(server_id, bot_name)
    try:
        client.containers.get(name).remove()
    except Exception:
        pass
    return start(server_id, bot_name, bot_token, config)


def remove(server_id: str, bot_name: str) -> tuple:
    """Stop and delete the bot container entirely. Returns (ok, message)."""
    client = _client()
    name   = _container_name(server_id, bot_name)
    try:
        c = client.containers.get(name)
        c.stop(timeout=5)
        c.remove()
        return True, 'Removed'
    except Exception:
        return True, 'Already removed'


def get_status(server_id: str, bot_name: str) -> str:
    """Return 'running' or 'stopped'."""
    client = _client()
    name   = _container_name(server_id, bot_name)
    try:
        c = client.containers.get(name)
        return 'running' if c.status == 'running' else 'stopped'
    except Exception:
        return 'stopped'


def get_all_statuses() -> dict:
    """
    Return {'{server_id}:{bot_name}': 'running'|'stopped'} for all bot containers
    managed by this DiscordForge instance.
    """
    client = _client()
    result = {}
    try:
        containers = client.containers.list(
            all=True,
            filters={'label': 'discordforge.bot=1'},
        )
        for c in containers:
            labels = c.labels
            sid    = labels.get('discordforge.server_id', '')
            bname  = labels.get('discordforge.bot_name', '')
            if sid and bname:
                result[f'{sid}:{bname}'] = 'running' if c.status == 'running' else 'stopped'
    except Exception:
        pass
    return result
