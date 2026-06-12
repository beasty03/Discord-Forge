# ============================================================================
# DISCORD BOT LAUNCHER
# ============================================================================
#
# This script starts your Discord bot and automatically loads all runtime cogs.
#
# WHAT DOES THIS SCRIPT DO?
# - Reads configuration from config.json
# - Starts the Discord bot
# - Scans the /cogs folder for available runtime modules (in subfolders)
# - Loads all found cogs automatically
# - Provides clear feedback about what's being loaded
#
# HOW TO ADD NEW FEATURES?
# 1. Create a new folder in the /cogs folder
# 2. Add your .py file inside that folder
# 3. Make sure it has a setup() function
# 4. Restart this launcher
# 5. The cog will be automatically detected and loaded!
#
# HOW TO START THE BOT:
# 1. Open terminal/command prompt
# 2. Navigate to this folder: cd path/to/discord-server-setup
# 3. Run: python launcher.py
# 4. The bot starts automatically!
#
# HOW TO STOP THE BOT:
# - Press Ctrl+C in the terminal
#
# TROUBLESHOOTING:
# - Bot won't start? Check your bot token in config.json
# - Cog won't load? Look at the error messages below
# - Permission issues? Check bot permissions in Discord Developer Portal
#
# ============================================================================

import asyncio
import discord
from discord.ext import commands
import json
import sys
from pathlib import Path
import traceback
from datetime import datetime
import importlib.util

# ============================================================================
# CONFIGURATION
# ============================================================================

# Get project root
SCRIPT_DIR = Path(__file__).parent
CONFIG_FILE = SCRIPT_DIR / "config.json"

import os as _os
import sys as _sys
_env_cogs = _os.environ.get('BOT_COGS_DIR', '').strip()
COGS_DIR = Path(_env_cogs) if _env_cogs else SCRIPT_DIR / "cogs"
if _env_cogs:
    _cogs_parent = str(Path(_env_cogs).parent)
    if _cogs_parent not in _sys.path:
        _sys.path.insert(0, _cogs_parent)

# Default settings
COMMAND_PREFIX = "!"
BOT_STATUS = "your server"
BOT_STATUS_TYPE = "watching"

# ============================================================================
# LOGGING SETUP
# ============================================================================

import logging

_LOG_DIR = SCRIPT_DIR / 'logs'
_LOG_DIR.mkdir(exist_ok=True)
_LOG_FILE = _LOG_DIR / 'bot.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding='utf-8'),
    ]
)
logger = logging.getLogger("launcher")

# ============================================================================
# CONFIGURATION LOADING
# ============================================================================

def load_config():
    """
    Loads configuration from BOT_CONFIG_JSON env var (Docker mode) or config.json (local mode).
    """
    import os as _os
    env_json = _os.environ.get('BOT_CONFIG_JSON', '')
    if env_json:
        try:
            config = json.loads(env_json)
            logger.info("✅ Configuration loaded from BOT_CONFIG_JSON env var")
            return config
        except json.JSONDecodeError as e:
            logger.error(f"❌ ERROR: BOT_CONFIG_JSON is not valid JSON: {e}")
            sys.exit(1)

    try:
        if not CONFIG_FILE.exists():
            logger.error("❌ ERROR: config.json not found!")
            logger.error(f"   Expected location: {CONFIG_FILE}")
            logger.error("   Please run bot_config.ps1 first to configure your bots")
            sys.exit(1)

        with open(CONFIG_FILE, 'r', encoding='utf-8-sig') as f:
            config = json.load(f)
        
        logger.info("✅ Configuration loaded from config.json")
        return config
        
    except json.JSONDecodeError as e:
        logger.error(f"❌ ERROR: config.json is not valid JSON format")
        logger.error(f"   Details: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ ERROR: Could not load configuration")
        logger.error(f"   Details: {e}")
        sys.exit(1)

def get_bot_token(config: dict, bot_name: str = None):
    """
    Gets bot token from config
    
    Args:
        config (dict): Configuration data
        bot_name (str): Optional bot name to select specific bot
        
    Returns:
        tuple: (token, bot_name)
    """
    if not config.get('discord_bots'):
        logger.error("❌ ERROR: No bots configured in config.json!")
        logger.error("   Please run bot_config.ps1 first to configure your bots")
        sys.exit(1)
    
    bots = config['discord_bots']
    
    # If bot name specified, find that bot
    if bot_name:
        for bot in bots:
            if bot['name'].lower() == bot_name.lower():
                return bot['token'], bot['name']
        logger.error(f"❌ ERROR: Bot '{bot_name}' not found in config!")
        logger.error(f"   Available bots: {', '.join([b['name'] for b in bots])}")
        sys.exit(1)
    
    # If multiple bots, ask user to select (or auto-select first in non-interactive mode)
    if len(bots) > 1:
        import os as _os, sys as _sys
        if not _sys.stdin.isatty() or _os.environ.get('BOT_CONFIG_JSON'):
            logger.info(f"Multiple bots in config — auto-selecting first: {bots[0]['name']}")
            return bots[0]['token'], bots[0]['name']

        logger.info("\n📋 Multiple bots configured:")
        for i, bot in enumerate(bots, 1):
            logger.info(f"   {i}. {bot['name']}")

        while True:
            try:
                selection = input("\nSelect bot number to launch (or press Enter for first bot): ").strip()
                if not selection:
                    return bots[0]['token'], bots[0]['name']

                index = int(selection) - 1
                if 0 <= index < len(bots):
                    return bots[index]['token'], bots[index]['name']
                else:
                    print("Invalid selection. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except KeyboardInterrupt:
                print("\n\nCancelled by user")
                sys.exit(0)
    
    # Single bot, use it
    return bots[0]['token'], bots[0]['name']

# ============================================================================
# COG DISCOVERY (WITH NESTED FOLDER STRUCTURE)
# ============================================================================

def discover_cogs(cogs_dir: Path):
    """
    Scans the /cogs folder and finds all available runtime cog modules
    Now supports nested folder structure: cogs/FolderName/script.py
    
    Args:
        cogs_dir (Path): Path to the cogs folder
        
    Returns:
        list: List of cog module paths (e.g., "cogs.Casino.casino_bot")
    """
    logger.info("\n🔍 Scanning for runtime cogs...")
    logger.info(f"   Location: {cogs_dir}")
    logger.info("-" * 60)
    
    if not cogs_dir.exists():
        logger.warning(f"⚠️  WARNING: Cogs folder not found: {cogs_dir}")
        logger.warning("   Creating folder... Place your cog folders there")
        cogs_dir.mkdir(parents=True, exist_ok=True)
        return []
    
    discovered_cogs = []
    
    # Scan all subdirectories in the cogs folder
    for folder in sorted(cogs_dir.iterdir()):
        if not folder.is_dir():
            continue
        
        # Skip private folders (start with _)
        if folder.name.startswith("_"):
            logger.debug(f"⏭️  Skipping: {folder.name} (private folder)")
            continue
        
        # Look for Python files in this folder
        for file_path in sorted(folder.glob("*.py")):
            # Skip private files (start with _)
            if file_path.stem.startswith("_"):
                logger.debug(f"⏭️  Skipping: {folder.name}/{file_path.name} (private file)")
                continue
            
            # Validate that it's a proper cog
            if validate_cog_file(file_path):
                # Format: cogs.FolderName.filename
                cog_path = f"cogs.{folder.name}.{file_path.stem}"
                discovered_cogs.append(cog_path)
                logger.info(f"✅ Found: {folder.name}/{file_path.name}")
            else:
                logger.warning(f"⚠️  Invalid: {folder.name}/{file_path.name} (missing setup function)")
    
    logger.info("-" * 60)
    logger.info(f"📦 Total runtime cogs discovered: {len(discovered_cogs)}\n")
    
    return discovered_cogs

def validate_cog_file(file_path: Path):
    """
    Checks if a Python file is a valid cog
    
    A valid cog must have a setup() or async setup() function
    
    Args:
        file_path (Path): Path to the Python file
        
    Returns:
        bool: True if it's a valid cog
    """
    try:
        content = file_path.read_text(encoding='utf-8')
        
        if 'def setup(' in content or 'async def setup(' in content:
            return True
        
        return False
        
    except Exception as e:
        logger.debug(f"   Error validating {file_path.name}: {e}")
        return False

# ============================================================================
# BOT INITIALIZATION
# ============================================================================

def create_bot(config: dict, bot_name: str):
    """
    Creates and configures the Discord bot instance
    
    Args:
        config (dict): Configuration data from config.json
        bot_name (str): Name of the bot being launched
        
    Returns:
        commands.Bot: Configured bot instance
    """
    logger.info("🤖 Initializing bot...")
    
    intents = discord.Intents.all()
    
    bot = commands.Bot(
        command_prefix=COMMAND_PREFIX,
        intents=intents,
        help_command=None
    )
    
    # Add custom attributes
    bot.config = config
    bot.start_time = datetime.utcnow()
    bot.bot_name = bot_name
    bot.server_name = config.get('server_name', 'Unknown Server')
    bot.guild_id = config.get('guild_id') or config.get('server', {}).get('guild_id')

    async def _setup_hook():
        bot.loop.create_task(_heartbeat_loop(bot))
    bot.setup_hook = _setup_hook

    logger.info(f"✅ Bot initialized")
    logger.info(f"   Bot Name: {bot_name}")
    logger.info(f"   Server: {bot.server_name}")
    logger.info(f"   Prefix: {COMMAND_PREFIX}")
    logger.info(f"   Guild ID: {bot.guild_id}\n")
    
    return bot

# ============================================================================
# COG LOADING
# ============================================================================

async def load_cogs(bot: commands.Bot, cog_list: list):
    """
    Loads all runtime cogs into the bot
    
    Args:
        bot (commands.Bot): The bot instance
        cog_list (list): List of cog module paths to load
    """
    logger.info("📥 Loading runtime cogs...")
    logger.info("-" * 60)
    
    loaded_count = 0
    failed_count = 0
    
    for cog_path in cog_list:
        try:
            await bot.load_extension(cog_path)
            logger.info(f"✅ Loaded: {cog_path}")
            loaded_count += 1
            
        except commands.ExtensionNotFound:
            logger.error(f"❌ Failed: {cog_path} (not found)")
            failed_count += 1
        except commands.ExtensionAlreadyLoaded:
            logger.warning(f"⚠️  Warning: {cog_path} (already loaded)")
        except commands.NoEntryPointError:
            logger.error(f"❌ Failed: {cog_path} (no setup function)")
            failed_count += 1
        except commands.ExtensionFailed as e:
            logger.error(f"❌ Failed: {cog_path}")
            logger.error(f"   Error: {e}")
            failed_count += 1
        except Exception as e:
            logger.error(f"❌ Failed: {cog_path}")
            logger.error(f"   Unexpected error: {e}")
            traceback.print_exc()
            failed_count += 1
    
    logger.info("-" * 60)
    logger.info(f"✅ Successfully loaded: {loaded_count}")
    if failed_count > 0:
        logger.warning(f"❌ Failed to load: {failed_count}")
    logger.info("")

# ============================================================================
# FORGE API HEARTBEAT
# ============================================================================

_API_URL   = ''
_SERVER_ID = ''
_BOT_ID    = ''
_API_TOKEN = ''
_USER_TZ   = 'UTC'
_messages_today      = 0
_messages_today_date = None
_member_msg_counts: dict = {}


def _uptime_str(start_time: datetime) -> str:
    delta = datetime.utcnow() - start_time
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m = rem // 60
    return f'{h}h {m}m' if h else f'{m}m'


def _log_tail(n: int = 20) -> list:
    try:
        lines = _LOG_FILE.read_text(encoding='utf-8', errors='replace').splitlines()
        return lines[-n:]
    except Exception:
        return []


async def _post_heartbeat(bot: commands.Bot):
    if not (_API_URL and _SERVER_ID and _BOT_ID and _API_TOKEN):
        return
    try:
        import aiohttp
        payload = {
            'server_id':      _SERVER_ID,
            'bot_id':         _BOT_ID,
            'status':         'online',
            'ping_ms':        round(bot.latency * 1000) if bot.latency else None,
            'uptime':         _uptime_str(bot.start_time),
            'log_tail':       _log_tail(),
            'messages_today':     _messages_today,
            'cogs_loaded':        len(bot.cogs),
            'cog_extensions':     list(bot.extensions.keys()),
            'member_msg_counts':  dict(_member_msg_counts),
        }
        async with aiohttp.ClientSession() as session:
            await session.post(
                f'{_API_URL}/api/local-bot/heartbeat',
                json=payload,
                headers={'X-Bot-Token': _API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        logger.debug(f'Heartbeat failed: {e}')


async def _push_members(bot: commands.Bot):
    if not (_API_URL and _SERVER_ID and _BOT_ID and _API_TOKEN):
        return
    if not bot.guild_id:
        return
    try:
        import aiohttp
        guild = bot.get_guild(int(bot.guild_id))
        if not guild:
            return
        members = [
            {
                'id':           str(m.id),
                'username':     m.name,
                'display_name': m.display_name,
                'avatar':       str(m.display_avatar.url),
                'roles':        [r.name for r in m.roles if r.name != '@everyone'],
                'joined_at':    m.joined_at.isoformat() if m.joined_at else None,
                'bot':          m.bot,
            }
            for m in guild.members
        ]
        async with aiohttp.ClientSession() as session:
            await session.post(
                f'{_API_URL}/api/local-bot/members',
                json={'server_id': _SERVER_ID, 'bot_id': _BOT_ID, 'members': members},
                headers={'X-Bot-Token': _API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=30),
            )
    except Exception as e:
        logger.debug(f'Member push failed: {e}')


async def _poll_commands(bot: commands.Bot):
    if not (_API_URL and _SERVER_ID and _BOT_ID and _API_TOKEN):
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            r = await session.get(
                f'{_API_URL}/api/local-bot/commands',
                headers={'X-Bot-Token': _API_TOKEN},
                params={'server_id': _SERVER_ID, 'bot_id': _BOT_ID},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if r.status != 200:
                return
            data = await r.json()
    except Exception as e:
        logger.debug(f'Command poll failed: {e}')
        return
    guild = bot.get_guild(int(bot.guild_id)) if bot.guild_id else None
    for cmd in data.get('commands', []):
        await _execute_command(bot, guild, cmd)


async def _execute_command(bot: commands.Bot, guild, cmd: dict):
    import aiohttp
    cmd_id    = cmd.get('id', '')
    ctype     = cmd.get('type', '')
    user_id   = cmd.get('user_id', '')
    reason    = cmd.get('reason') or 'Action via dashboard'
    role_name = cmd.get('role_name', '')
    success, err = False, ''
    try:
        if not guild:
            raise ValueError('Guild not found')
        member = guild.get_member(int(user_id)) if user_id else None
        if ctype == 'kick':
            if not member:
                raise ValueError(f'Member {user_id} not in guild')
            await member.kick(reason=reason)
            success = True
        elif ctype == 'ban':
            if not member:
                raise ValueError(f'Member {user_id} not in guild')
            await member.ban(reason=reason, delete_message_days=0)
            success = True
        elif ctype == 'warn':
            if not member:
                raise ValueError(f'Member {user_id} not in guild')
            try:
                await member.send(f'⚠️ You have received a warning in **{guild.name}**.\nReason: {reason}')
            except Exception:
                pass
            # Write to moderation.db so /warnings slash command shows dashboard warns
            try:
                import sqlite3 as _sq
                from pathlib import Path as _P
                _db = _P(__file__).parent / 'database' / 'moderation.db'
                _db.parent.mkdir(parents=True, exist_ok=True)
                with _sq.connect(str(_db)) as _conn:
                    _conn.execute('''CREATE TABLE IF NOT EXISTS warnings (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id TEXT NOT NULL, guild_id TEXT NOT NULL,
                        reason TEXT, warned_by TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
                    _conn.execute(
                        'INSERT INTO warnings (user_id, guild_id, reason, warned_by) VALUES (?,?,?,?)',
                        (str(member.id), str(guild.id), reason or 'No reason provided', 'Dashboard'),
                    )
            except Exception as _e:
                logger.debug(f'Warning DB write failed: {_e}')
            success = True
        elif ctype == 'assign_role':
            if not member:
                raise ValueError(f'Member {user_id} not in guild')
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                raise ValueError(f'Role "{role_name}" not found')
            await member.add_roles(role, reason=reason)
            success = True
        elif ctype == 'remove_role':
            if not member:
                raise ValueError(f'Member {user_id} not in guild')
            role = discord.utils.get(guild.roles, name=role_name)
            if not role:
                raise ValueError(f'Role "{role_name}" not found')
            await member.remove_roles(role, reason=reason)
            success = True
        else:
            err = f'Unknown command type: {ctype}'
    except Exception as e:
        err = str(e)
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f'{_API_URL}/api/local-bot/command-result',
                json={
                    'server_id':  _SERVER_ID,
                    'bot_id':     _BOT_ID,
                    'command_id': cmd_id,
                    'success':    success,
                    'error':      err,
                },
                headers={'X-Bot-Token': _API_TOKEN},
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        logger.debug(f'Command result post failed: {e}')


async def _heartbeat_loop(bot: commands.Bot):
    await bot.wait_until_ready()
    while not bot.is_closed():
        await _post_heartbeat(bot)
        await _poll_commands(bot)
        await asyncio.sleep(30)


# ============================================================================
# BOT EVENTS
# ============================================================================

def setup_events(bot: commands.Bot):
    """
    Registers event handlers for the bot
    """
    
    @bot.event
    async def on_ready():
        """
        Triggered when the bot successfully connects to Discord
        """
        logger.info("=" * 60)
        logger.info("🎉 BOT IS ONLINE!")
        logger.info("=" * 60)
        logger.info(f"Bot Name:     {bot.user.name}")
        logger.info(f"Bot ID:       {bot.user.id}")
        logger.info(f"Config Name:  {bot.bot_name}")
        logger.info(f"Server:       {bot.server_name}")
        logger.info(f"Guild ID:     {bot.guild_id}")
        logger.info(f"Cogs Loaded:  {len(bot.cogs)}")
        logger.info(f"Latency:      {round(bot.latency * 1000)}ms")
        logger.info(f"Prefix:       {COMMAND_PREFIX}")
        logger.info("=" * 60)
        
        # Set bot status
        try:
            activity_type = {
                'playing': discord.ActivityType.playing,
                'watching': discord.ActivityType.watching,
                'listening': discord.ActivityType.listening,
                'competing': discord.ActivityType.competing,
            }.get(BOT_STATUS_TYPE.lower(), discord.ActivityType.watching)
            
            activity = discord.Activity(type=activity_type, name=BOT_STATUS)
            await bot.change_presence(activity=activity)
            logger.info(f"✅ Status set: {BOT_STATUS_TYPE.title()} {BOT_STATUS}")
        except Exception as e:
            logger.warning(f"⚠️  Could not set bot status: {e}")
        
        # Sync slash commands
        try:
            if bot.guild_id:
                guild = discord.Object(id=int(bot.guild_id))
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                logger.info("✅ Slash commands synced")
        except Exception as e:
            logger.warning(f"⚠️  Could not sync slash commands: {e}")

        # Self-assign the bots role so this bot appears in the hoisted group
        try:
            guild_id = bot.config.get('server', {}).get('guild_id') or bot.config.get('guild_id')
            bots_role_name = bot.config.get('bots_role_name', 'bots')
            if guild_id:
                real_guild = bot.get_guild(int(guild_id))
                if real_guild:
                    bots_role = discord.utils.get(real_guild.roles, name=bots_role_name)
                    if bots_role:
                        bot_member = real_guild.get_member(bot.user.id)
                        if bot_member and bots_role not in bot_member.roles:
                            await bot_member.add_roles(bots_role)
                            logger.info(f'✅ Assigned "{bots_role_name}" role to self')
                    else:
                        logger.warning(f'⚠️  Bots role "{bots_role_name}" not found in guild')
        except Exception as e:
            logger.warning(f"⚠️  Could not assign bots role: {e}")

        # Push member list to Forge on connect / reconnect
        bot.loop.create_task(_push_members(bot))

        logger.info("\n✨ Bot is ready to use!\n")

    @bot.event
    async def on_command_error(ctx, error):
        """
        Triggered when a command raises an error
        """
        if isinstance(error, commands.CommandNotFound):
            return
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You don't have permission to use this command!")
            return
        
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"❌ Missing required argument: `{error.param.name}`")
            return
        
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏰ This command is on cooldown. Try again in {error.retry_after:.1f}s")
            return
        
        logger.error(f"❌ Command error in {ctx.command}: {error}")
        logger.error(traceback.format_exception(type(error), error, error.__traceback__))
        
        await ctx.send("❌ An error occurred while executing this command.")
    
    @bot.event
    async def on_message(message):
        global _messages_today, _messages_today_date, _member_msg_counts
        if not message.author.bot:
            try:
                from zoneinfo import ZoneInfo
                today = datetime.now(ZoneInfo(_USER_TZ)).date()
            except Exception:
                today = datetime.utcnow().date()
            if _messages_today_date != today:
                _messages_today = 0
                _messages_today_date = today
                _member_msg_counts = {}
            _messages_today += 1
            uid = str(message.author.id)
            _member_msg_counts[uid] = _member_msg_counts.get(uid, 0) + 1
        await bot.process_commands(message)

    @bot.event
    async def on_error(event, *args, **kwargs):
        """
        Triggered when a non-command error occurs
        """
        logger.error(f"❌ Error in event {event}")
        logger.error(traceback.format_exc())

# ============================================================================
# MAIN LAUNCHER
# ============================================================================

async def main():
    """
    Main function that starts the bot and keeps it running
    """
    print("\n" + "=" * 60)
    print("  DISCORD BOT LAUNCHER - RUNTIME MODE")
    print("=" * 60 + "\n")
    
    # 1. Load config.json
    config = load_config()

    # Initialize Forge API heartbeat credentials
    global _API_URL, _SERVER_ID, _BOT_ID, _API_TOKEN, _USER_TZ
    _API_URL   = _os.environ.get('FORGE_API_URL', config.get('api_url', '')).rstrip('/')
    _SERVER_ID = config.get('server_id', '')
    _BOT_ID    = config.get('bot_id', '') or (config['discord_bots'][0].get('id', '') if config.get('discord_bots') else '')
    _API_TOKEN = config.get('api_token', '')
    _USER_TZ   = config.get('timezone', 'UTC')

    # 2. Get bot token
    # Support --bot <name> argument so Flask can launch a specific bot
    # without hitting the interactive input() prompt.
    logger.info("🔑 Selecting bot...")
    import argparse
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--bot', default=None)
    args, _ = parser.parse_known_args()
    bot_token, bot_name = get_bot_token(config, bot_name=args.bot)
    logger.info(f"✅ Selected: {bot_name}\n")
    
    # 3. Discover available cogs
    cog_list = discover_cogs(COGS_DIR)
    
    # 4. Create bot instance
    bot = create_bot(config, bot_name)
    # Expose Forge API credentials so cogs can call back to Forge
    bot.forge_api_url   = _API_URL
    bot.forge_server_id = _SERVER_ID
    bot.forge_bot_id    = _BOT_ID
    bot.forge_api_token = _API_TOKEN

    # 5. Setup event handlers
    setup_events(bot)
    
    # 6. Load cogs
    if cog_list:
        await load_cogs(bot, cog_list)
    else:
        logger.warning("⚠️  No cogs found to load")
        logger.warning("   The bot will start but won't have any features")
        logger.warning("   Add cog folders to the /cogs directory\n")
    
    # 7. Start the bot
    try:
        logger.info("🚀 Starting bot...")
        logger.info("   Press Ctrl+C to stop\n")
        await bot.start(bot_token)
    except discord.LoginFailure:
        logger.error("❌ ERROR: Invalid bot token!")
        logger.error("   Please check your token in config.json")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("\n⏹️  Shutting down bot...")
        await bot.close()
        logger.info("✅ Bot stopped successfully")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        traceback.print_exc()
        sys.exit(1)

# ============================================================================
# ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    try:
        # Check Python version
        if sys.version_info < (3, 8):
            logger.error("❌ ERROR: Python 3.8 or higher is required!")
            logger.error(f"   Your version: {sys.version}")
            sys.exit(1)
        
        # Run the bot
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        traceback.print_exc()
        sys.exit(1)
