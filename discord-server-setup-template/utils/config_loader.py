import json
import os

def load_config():
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        'discord-server-setup',
        'config.json'
    )
    
    with open(config_path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)

def get_bot_token(bot_name=None):
    config = load_config()
    
    if bot_name:
        return next(bot['token'] for bot in config['discord_bots'] if bot['name'] == bot_name)
    else:
        return config['discord_bots'][0]['token']