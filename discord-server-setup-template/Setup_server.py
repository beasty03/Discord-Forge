import sys
import io
# Force UTF-8 output so emoji in print() don't crash on Windows (cp1252)
if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import discord
from discord.ext import commands
import json
import asyncio
import os
import sys
import aiohttp

# Load config
CONFIG_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

with open(CONFIG_JSON, 'r', encoding='utf-8-sig') as f:
    config = json.load(f)

# Extract variables from config
SETUPBOT_TOKEN = config['bot_token']  # Injected by setup.ps1
GUILD_ID = config['server']['guild_id']
TEMPLATE_DIR = config['paths']['template_dir']

# Load templates
MOD_TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, 'moderation_template.json')
WELCOME_TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, 'welcome_template.json')

# Bot setup with ALL intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

def get_color(color_name):
    """Convert color name or hex string to discord.Color"""
    if color_name and color_name.startswith('#'):
        try:
            return discord.Color(int(color_name[1:], 16))
        except ValueError:
            return discord.Color.default()
    colors = {
        'red': discord.Color.red(),
        'orange': discord.Color.orange(),
        'yellow': discord.Color.yellow(),
        'green': discord.Color.green(),
        'blue': discord.Color.blue(),
        'purple': discord.Color.purple(),
        'magenta': discord.Color.magenta(),
        'gold': discord.Color.gold(),
        'default': discord.Color.default()
    }
    return colors.get((color_name or 'default').lower(), discord.Color.default())

async def get_icon_bytes(icon_path, icon_type):
    """Convert icon to bytes for Discord API"""
    if icon_type == "file":
        with open(icon_path, 'rb') as f:
            return f.read()
    elif icon_type == "url":
        async with aiohttp.ClientSession() as session:
            async with session.get(icon_path) as resp:
                if resp.status == 200:
                    return await resp.read()
    return None

async def create_role_with_permissions(guild, role_data):
    """Create a role with specific permissions if it doesn't already exist"""
    # Check if role already exists
    existing_role = discord.utils.get(guild.roles, name=role_data['name'])
    if existing_role:
        print(f'Role already exists: {existing_role.name} - skipping creation')
        return existing_role

    perms_dict = role_data.get('permissions', {})
    permissions = discord.Permissions(**perms_dict)

    color = get_color(role_data.get('color', 'default'))
    hoist = role_data.get('hoist', False)

    role = await guild.create_role(
        name=role_data['name'],
        permissions=permissions,
        color=color,
        hoist=hoist
    )
    print(f'Created role: {role.name}')
    return role

async def set_channel_permissions(channel, permissions_data, role_map):
    """Set channel permissions based on template"""
    overwrites = {}

    # Deny @everyone by default if specified
    if '@everyone' in permissions_data.get('deny', []):
        overwrites[channel.guild.default_role] = discord.PermissionOverwrite(view_channel=False)

    # Allow specific roles to view
    for role_name in permissions_data.get('view', []):
        if role_name in role_map:
            overwrites[role_map[role_name]] = discord.PermissionOverwrite(view_channel=True)

    # Explicitly deny specific roles
    for role_name in permissions_data.get('deny', []):
        if role_name in role_map and role_name != '@everyone':
            overwrites[role_map[role_name]] = discord.PermissionOverwrite(view_channel=False)

    await channel.edit(overwrites=overwrites)

@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}')

    guild = bot.get_guild(int(GUILD_ID))
    if not guild:
        print(f'Error: Could not find guild with ID {GUILD_ID}')
        await bot.close()
        return

    print(f'Found guild: {guild.name}')

    # Get bot member object (needed for role operations)
    bot_member = guild.get_member(bot.user.id)
    if not bot_member:
        print('Error: Could not find bot member in guild')
        await bot.close()
        return

    print(f'Bot member: {bot_member.name}')

    try:
        # Change server name and icon
        new_server_name = config["server"]["name"]
        icon_path = config["server"].get("icon")
        icon_type = config["server"].get("icon_type", "none")

        print(f'Updating server settings...')

        # Prepare icon
        icon_bytes = None
        if icon_path and icon_type != "none":
            try:
                icon_bytes = await get_icon_bytes(icon_path, icon_type)
            except Exception as e:
                print(f'Could not load icon: {e}')

        # Update server
        if guild.name != new_server_name or icon_bytes:
            await guild.edit(name=new_server_name, icon=icon_bytes)
            print(f'Server name updated to: {new_server_name}')

        # Clean up existing channels and categories
        print('Cleaning server...')
        for channel in guild.channels:
            try:
                await channel.delete()
                print(f'Deleted channel: {channel.name}')
                await asyncio.sleep(0.5)
            except Exception as e:
                print(f'Could not delete channel {channel.name}: {e}')

        print('Server cleaned!\n')

        # Load moderation template
        print('Loading Moderation Template...')
        mod_template = None
        if os.path.exists(MOD_TEMPLATE_PATH):
            with open(MOD_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                mod_template = json.load(f)

        # Load welcome template if specified
        welcome_template = None
        if config.get("use_welcome_template", False) and os.path.exists(WELCOME_TEMPLATE_PATH):
            with open(WELCOME_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
                welcome_template = json.load(f)
            # Apply custom onboarding names if the user configured them  # _ob_names_patch
            ob = config.get('onboarding', {})
            if ob and welcome_template:
                for role_data in welcome_template.get('roles', []):
                    if role_data.get('name') == 'Member' and ob.get('member_role_name'):
                        role_data['name'] = ob['member_role_name']
                for ch_data in welcome_template.get('text_channels', []):
                    if ch_data.get('name') == 'welcome' and ob.get('welcome_channel_name'):
                        ch_data['name'] = ob['welcome_channel_name']
                    elif ch_data.get('name') == 'rules' and ob.get('rules_channel_name'):
                        ch_data['name'] = ob['rules_channel_name']

        # Create roles
        print('Creating Roles...')
        role_map = {}

        # Create moderation roles first (Admin, Moderator)
        if mod_template and 'roles' in mod_template:
            for role_data in mod_template['roles']:
                role = await create_role_with_permissions(guild, role_data)
                role_map[role.name] = role

        # Create custom roles from config
        if 'custom_roles' in config and config['custom_roles']:
            for entry in config['custom_roles']:
                if isinstance(entry, dict):
                    role_name = entry['name']
                    perms_list = entry.get('permissions', [])
                    role_data = {
                        'name': role_name,
                        'permissions': {p: True for p in perms_list} if isinstance(perms_list, list) else perms_list,
                        'color': entry.get('color', 'default'),
                        'hoist': entry.get('hoist', False),
                    }
                else:
                    role_name = str(entry)
                    role_data = {'name': role_name}
                role = await create_role_with_permissions(guild, role_data)
                role_map[role_name] = role

        # Create welcome roles if specified
        if welcome_template and 'roles' in welcome_template:
            for role_data in welcome_template['roles']:
                role = await create_role_with_permissions(guild, role_data)
                role_map[role.name] = role

        # Create bots role (hoisted so bots appear separately in the member list)
        bots_role_name = config.get('bots_role_name', 'bots')
        bots_role = await create_role_with_permissions(guild, {
            'name': bots_role_name,
            'permissions': {},
            'color': 'blue',
            'hoist': True,
        })
        role_map[bots_role_name] = bots_role

        # Create categories and channels
        print('Creating Categories and Channels...')

        # Create moderation categories and channels
        if mod_template and 'categories' in mod_template:
            for category_data in mod_template['categories']:
                category_name = category_data['name']
                category = await guild.create_category(category_name)
                print(f'Created category: {category_name}')

                # Create text channels
                for channel_data in category_data.get('text_channels', []):
                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data
                    _ch_nsfw = bool(channel_data.get('nsfw', False)) if isinstance(channel_data, dict) else False
                    _ch_slow = int(channel_data.get('slowmode', 0) or 0) if isinstance(channel_data, dict) else 0
                    channel = await guild.create_text_channel(channel_name, category=category, nsfw=_ch_nsfw, slowmode_delay=_ch_slow)
                    print(f'Created text channel: {channel_name}')

                    # Set permissions if specified
                    if isinstance(channel_data, dict) and 'permissions' in channel_data:
                        await set_channel_permissions(channel, channel_data['permissions'], role_map)

                # Create voice channels
                for channel_data in category_data.get('voice_channels', []):
                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data
                    channel = await guild.create_voice_channel(channel_name, category=category)
                    print(f'Created voice channel: {channel_name}')
                    if isinstance(channel_data, dict) and 'permissions' in channel_data:
                        await set_channel_permissions(channel, channel_data['permissions'], role_map)
                        print(f'  └─ permissions applied')

        # Create welcome category and channels if specified
        if welcome_template:
            print('Creating Welcome Channels...')
            for channel_data in welcome_template.get('text_channels', []):
                channel_name = channel_data['name']
                channel = await guild.create_text_channel(channel_name)
                print(f'Created welcome text channel: {channel_name}')

                # Set permissions if specified
                if 'permissions' in channel_data:
                    await set_channel_permissions(channel, channel_data['permissions'], role_map)

        # Enable Community if requested — must happen before forum channels
        if config.get('community_server'):  # _guild_refresh_fetch
            if 'COMMUNITY' not in guild.features:
                print('Enabling Community feature (required for forum channels)...')
                cs = config.get('community_settings', {})
                vlevel_map = {
                    'none': discord.VerificationLevel.none,
                    'low': discord.VerificationLevel.low,
                    'medium': discord.VerificationLevel.medium,
                    'high': discord.VerificationLevel.high,
                    'highest': discord.VerificationLevel.highest,
                }
                cfilter_map = {
                    'disabled': discord.ContentFilter.disabled,
                    'no_role': discord.ContentFilter.no_role,
                    'all_members': discord.ContentFilter.all_members,
                }
                vlevel  = vlevel_map.get(cs.get('verification_level', 'low'), discord.VerificationLevel.low)
                cfilter = cfilter_map.get(cs.get('content_filter', 'all_members'), discord.ContentFilter.all_members)
                all_text = [ch for ch in guild.channels if isinstance(ch, discord.TextChannel)]
                rules_ch   = all_text[0] if all_text else None
                updates_ch = all_text[-1] if all_text else None
                if rules_ch and updates_ch:
                    try:
                        await guild.edit(
                            community=True,
                            rules_channel=rules_ch,
                            public_updates_channel=updates_ch,
                            verification_level=vlevel,
                            explicit_content_filter=cfilter,
                        )
                        print(f'Community enabled (rules: #{rules_ch.name}, updates: #{updates_ch.name})')
                        await asyncio.sleep(1)
                        guild = await bot.fetch_guild(int(GUILD_ID))  # _guild_refresh_fetch
                    except Exception as e:
                        print(f'Could not enable Community: {e}')
                        print('Forum channels will be skipped if Community is not enabled.')
                else:
                    print('No text channels found yet — Community could not be enabled. Forum channels may fail.')
            else:
                print('Community already enabled.')
                guild = await bot.fetch_guild(int(GUILD_ID))  # _guild_refresh_fetch

        # Create custom categories and channels from config
        print('Creating Custom Categories...')
        if 'custom_categories' in config and config['custom_categories']:
            for category_data in config['custom_categories']:
                category_name = category_data['name']
                is_private = category_data.get('private', False)

                # Private category: deny @everyone, grant access to any roles
                # that appear in the channel permissions inside this category
                cat_overwrites = {}
                if is_private:
                    cat_overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                    allowed_roles = set()
                    all_chs = (category_data.get('text_channels', [])
                               + category_data.get('voice_channels', [])
                               + category_data.get('forum_channels', []))
                    for ch in all_chs:
                        if isinstance(ch, dict):
                            for r in ch.get('permissions', {}).get('view', []):
                                allowed_roles.add(r)
                    for role_name in allowed_roles:
                        if role_name in role_map:
                            cat_overwrites[role_map[role_name]] = discord.PermissionOverwrite(view_channel=True)

                category = await guild.create_category(category_name, overwrites=cat_overwrites)
                print(f'Created category: {category_name}{"  [private]" if is_private else ""}')

                # Create text channels
                for channel_data in category_data.get('text_channels', []):
                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data
                    channel = await guild.create_text_channel(channel_name, category=category)
                    print(f'Created text channel: #{channel_name}')
                    if isinstance(channel_data, dict) and 'permissions' in channel_data:
                        await set_channel_permissions(channel, channel_data['permissions'], role_map)
                        print(f'  └─ permissions applied')

                # Create voice channels
                for channel_data in category_data.get('voice_channels', []):
                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data
                    channel = await guild.create_voice_channel(channel_name, category=category)
                    print(f'Created voice channel: {channel_name}')
                    if isinstance(channel_data, dict) and 'permissions' in channel_data:
                        await set_channel_permissions(channel, channel_data['permissions'], role_map)
                        print(f'  └─ permissions applied')

                # Create forum channels (requires Community to be enabled)
                for channel_data in category_data.get('forum_channels', []):
                    channel_name = channel_data['name'] if isinstance(channel_data, dict) else channel_data
                    if 'COMMUNITY' not in guild.features:
                        print(f'Skipped forum channel {channel_name}: Community is not enabled on this server.')
                        continue
                    try:
                        channel = await guild.create_forum_channel(channel_name, category=category)
                        print(f'Created forum channel: {channel_name}')
                        if isinstance(channel_data, dict) and 'permissions' in channel_data:
                            await set_channel_permissions(channel, channel_data['permissions'], role_map)
                            print(f'  └─ permissions applied')
                    except Exception as e:
                        print(f'Could not create forum channel {channel_name}: {e}')

        print('✅ Server setup complete!')

        # Remove bot from server (skip if config keeps own bot in guild)
        if not config.get('keep_in_guild', False):
            try:
                print('Removing bot from server...')
                await guild.leave()
                print('✅ Bot has left the server')
            except Exception as e:
                print(f'❌ Error leaving server: {e}')
        else:
            print('ℹ️ Bot stays in server (keep_in_guild=true)')

    except discord.Forbidden:
        print('❌ Error: Bot does not have permission to manage server')
    except Exception as e:
        print(f'❌ Error during setup: {e}')

    await bot.close()

# Run bot
bot.run(SETUPBOT_TOKEN)
