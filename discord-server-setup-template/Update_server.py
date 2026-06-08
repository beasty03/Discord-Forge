"""
update_server.py  —  Diff-based Discord server updater.

Unlike Setup_server.py (which wipes everything and rebuilds), this script
compares the current state of the Discord server against the desired state
in config.json and only applies the delta:

  • Roles  : create missing, delete removed, skip unchanged
  • Categories : create missing, delete removed (with their channels), skip unchanged
  • Channels   : within each category — create missing, delete removed,
                 update permissions if changed, skip unchanged
  • Server name / icon  : update only if changed

The script reads config.json from the same directory as itself, same as
Setup_server.py, so Flask can call it the same way:

    python update_server.py <path/to/config.json>
"""

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

# ── Config ────────────────────────────────────────────────────────────────────

if len(sys.argv) > 1:
    CONFIG_JSON = sys.argv[1]
else:
    CONFIG_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

with open(CONFIG_JSON, 'r', encoding='utf-8-sig') as f:
    config = json.load(f)

SETUPBOT_TOKEN = config['bot_token']
GUILD_ID       = config['server']['guild_id']
TEMPLATE_DIR   = config['paths']['template_dir']

MOD_TEMPLATE_PATH     = os.path.join(TEMPLATE_DIR, 'moderation_template.json')
WELCOME_TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, 'welcome_template.json')

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_color(color_name):
    if color_name and color_name.startswith('#'):
        try:
            return discord.Color(int(color_name[1:], 16))
        except ValueError:
            return discord.Color.default()
    colors = {
        'red': discord.Color.red(), 'orange': discord.Color.orange(),
        'yellow': discord.Color.yellow(), 'green': discord.Color.green(),
        'blue': discord.Color.blue(), 'purple': discord.Color.purple(),
        'magenta': discord.Color.magenta(), 'gold': discord.Color.gold(),
        'default': discord.Color.default()
    }
    return colors.get((color_name or 'default').lower(), discord.Color.default())


async def get_icon_bytes(icon_path, icon_type):
    if icon_type == 'file' and icon_path:
        with open(icon_path, 'rb') as f:
            return f.read()
    elif icon_type == 'url' and icon_path:
        async with aiohttp.ClientSession() as session:
            async with session.get(icon_path) as resp:
                if resp.status == 200:
                    return await resp.read()
    return None


async def ensure_role(guild, role_name, role_data=None):
    """Return existing role or create it, updating color/hoist if provided."""
    existing = discord.utils.get(guild.roles, name=role_name)
    if existing:
        if role_data:
            edits = {}
            raw_color = role_data.get('color')
            if raw_color:
                new_color = get_color(raw_color)
                if new_color.value != existing.color.value:
                    edits['color'] = new_color
            raw_hoist = role_data.get('hoist')
            if raw_hoist is not None and raw_hoist != existing.hoist:
                edits['hoist'] = raw_hoist
            if edits:
                try:
                    await existing.edit(**edits)
                    print(f'  Updated role: {role_name} ({", ".join(edits)})')
                except Exception as e:
                    print(f'  Could not update role {role_name}: {e}')
        else:
            print(f'  Role exists: {role_name}')
        return existing
    perms = discord.Permissions(**(role_data or {}).get('permissions', {}))
    color = get_color((role_data or {}).get('color', 'default'))
    hoist = (role_data or {}).get('hoist', False)
    role  = await guild.create_role(name=role_name, permissions=perms, color=color, hoist=hoist)
    print(f'  ✅ Created role: {role_name}')
    return role


async def apply_channel_permissions(channel, permissions_data, role_map):
    """Apply permission overwrites to a channel."""
    if not permissions_data:
        return
    overwrites = {}
    if '@everyone' in permissions_data.get('deny', []):
        overwrites[channel.guild.default_role] = discord.PermissionOverwrite(view_channel=False)
    for role_name in permissions_data.get('view', []):
        if role_name in role_map:
            overwrites[role_map[role_name]] = discord.PermissionOverwrite(view_channel=True)
    for role_name in permissions_data.get('deny', []):
        if role_name in role_map and role_name != '@everyone':
            overwrites[role_map[role_name]] = discord.PermissionOverwrite(view_channel=False)
    await channel.edit(overwrites=overwrites)


# ── Main update logic ──────────────────────────────────────────────────────────

@bot.event
async def on_ready():
    print(f'Update bot logged in as {bot.user}')

    guild = bot.get_guild(int(GUILD_ID))
    if not guild:
        print(f'❌ Could not find guild {GUILD_ID}')
        await bot.close()
        return

    print(f'Connected to: {guild.name}')

    try:
        await run_update(guild)
    except discord.Forbidden:
        print('❌ Bot lacks permissions to update server')
    except Exception as e:
        import traceback
        print(f'❌ Unexpected error: {e}')
        traceback.print_exc()

    await bot.close()


async def run_update(guild):
    # ── 1. Server name / icon ──────────────────────────────────────────────────
    desired_name = config['server']['name']
    icon_path    = config['server'].get('icon')
    icon_type    = config['server'].get('icon_type', 'none')

    edit_kwargs = {}
    if guild.name != desired_name:
        edit_kwargs['name'] = desired_name
        print(f'Renaming server: {guild.name} → {desired_name}')

    if icon_path and icon_type != 'none':
        try:
            icon_bytes = await get_icon_bytes(icon_path, icon_type)
            if icon_bytes:
                edit_kwargs['icon'] = icon_bytes
                print('Updating server icon')
        except Exception as e:
            print(f'  Could not load icon: {e}')

    if edit_kwargs:
        await guild.edit(**edit_kwargs)
        print('✅ Server settings updated')

    # ── 2. Roles ──────────────────────────────────────────────────────────────
    print('\nUpdating roles...')

    # Build desired role name set
    desired_role_names = set()

    # Moderation template roles
    mod_template = None
    if os.path.exists(MOD_TEMPLATE_PATH):
        with open(MOD_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            mod_template = json.load(f)
    if mod_template:
        for r in mod_template.get('roles', []):
            desired_role_names.add(r['name'])

    # Custom roles from config
    for entry in config.get('custom_roles', []):
        desired_role_names.add(entry['name'] if isinstance(entry, dict) else str(entry))

    # Welcome template roles — protect from deletion
    if config.get('use_welcome_template', False) and os.path.exists(WELCOME_TEMPLATE_PATH):
        with open(WELCOME_TEMPLATE_PATH, 'r', encoding='utf-8') as f:
            _wt = json.load(f)
        for r in _wt.get('roles', []):
            desired_role_names.add(r['name'])

    # Build role_map (existing + newly created)
    role_map = {}

    # Create missing moderation roles
    if mod_template:
        for role_data in mod_template.get('roles', []):
            role = await ensure_role(guild, role_data['name'], role_data)
            role_map[role_data['name']] = role

    # Create missing custom roles
    for entry in config.get('custom_roles', []):
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
            role_data = None
        role = await ensure_role(guild, role_name, role_data)
        role_map[role_name] = role

    # Create/ensure bots role (hoisted so bots appear separately in the member list)
    bots_role_name = config.get('bots_role_name', 'bots')
    desired_role_names.add(bots_role_name)
    bots_role_obj = await ensure_role(guild, bots_role_name, {'color': 'blue', 'hoist': True})

    # Assign the bots role to all configured runtime bots.
    # The update bot is invited with Administrator, so it can assign any role regardless of position.
    for bot_entry in config.get('discord_bots', []):
        token = bot_entry.get('token', '')
        if not token:
            continue
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    'https://discord.com/api/v10/users/@me',
                    headers={'Authorization': f'Bot {token}'}
                ) as resp:
                    if resp.status != 200:
                        print(f'  ⚠️  Could not fetch user for bot {bot_entry.get("name")}: HTTP {resp.status}')
                        continue
                    data = await resp.json()
                    bot_user_id = int(data['id'])
            member = guild.get_member(bot_user_id)
            if member is None:
                print(f'  ⚠️  Bot {bot_entry.get("name")} is not in this guild — skipping role assignment')
                continue
            if bots_role_obj and bots_role_obj not in member.roles:
                await member.add_roles(bots_role_obj, reason='Assigned bots role by update bot')
                print(f'  ✅ Assigned "{bots_role_name}" role to {bot_entry.get("name")}')
            else:
                print(f'  Role "{bots_role_name}" already assigned to {bot_entry.get("name")}')
        except Exception as e:
            print(f'  ⚠️  Could not assign bots role to {bot_entry.get("name")}: {e}')

    # Also map any other existing roles (so permissions work)
    for role in guild.roles:
        if role.name not in role_map:
            role_map[role.name] = role

    # Delete roles that are no longer desired
    # (only delete roles we would have created — skip @everyone, bot roles, etc.)
    protected_names = {'@everyone'}
    for role in guild.roles:
        if role.managed:  # bot-managed roles — never touch
            continue
        if role.name in protected_names:
            continue
        # Only delete if it was a custom role we previously created and is no longer wanted
        if role.name in role_map and role.name not in desired_role_names:
            # Check it's not a higher-permission role (safety guard)
            if not role.permissions.administrator and not role.permissions.manage_guild:
                try:
                    await role.delete(reason='Removed from server config')
                    print(f'  🗑️  Deleted role: {role.name}')
                except Exception as e:
                    print(f'  Could not delete role {role.name}: {e}')

    # ── 3. Categories & Channels ──────────────────────────────────────────────
    print('\nUpdating categories and channels...')

    desired_cats = config.get('custom_categories', [])
    desired_cat_names = {c['name'] for c in desired_cats}

    # Map existing categories by name
    existing_cats = {
        cat.name: cat
        for cat in guild.categories
    }

    # --- Delete categories (and their channels) no longer in config ---
    # Only delete categories that are NOT from mod/welcome templates
    # (those are managed by Setup_server.py, not us)
    mod_cat_names = set()
    if mod_template:
        for c in mod_template.get('categories', []):
            mod_cat_names.add(c['name'])

    for cat_name, cat_obj in list(existing_cats.items()):
        if cat_name in mod_cat_names:
            continue  # leave mod template categories alone
        if cat_name not in desired_cat_names:
            print(f'  🗑️  Removing category: {cat_name}')
            for channel in cat_obj.channels:
                try:
                    await channel.delete()
                    print(f'    🗑️  Deleted channel: {channel.name}')
                    await asyncio.sleep(0.3)
                except Exception as e:
                    print(f'    Could not delete channel {channel.name}: {e}')
            try:
                await cat_obj.delete()
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f'  Could not delete category {cat_name}: {e}')

    # --- Create or update categories that are in config ---
    for cat_data in desired_cats:
        cat_name   = cat_data['name']
        is_private = cat_data.get('private', False)

        if cat_name in existing_cats:
            cat_obj = existing_cats[cat_name]
            print(f'  Category exists: {cat_name}')

            # Update category privacy if needed
            everyone_overwrite = cat_obj.overwrites_for(guild.default_role)
            currently_private  = everyone_overwrite.view_channel is False
            if is_private != currently_private:
                overwrites = dict(cat_obj.overwrites)
                if is_private:
                    overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                else:
                    overwrites.pop(guild.default_role, None)
                await cat_obj.edit(overwrites=overwrites)
                print(f'    Updated privacy → {"private" if is_private else "public"}')
        else:
            # Create new category
            cat_overwrites = {}
            if is_private:
                cat_overwrites[guild.default_role] = discord.PermissionOverwrite(view_channel=False)
                allowed_roles = set()
                for ch in cat_data.get('text_channels', []) + cat_data.get('voice_channels', []):
                    if isinstance(ch, dict):
                        for r in ch.get('permissions', {}).get('view', []):
                            allowed_roles.add(r)
                for rname in allowed_roles:
                    if rname in role_map:
                        cat_overwrites[role_map[rname]] = discord.PermissionOverwrite(view_channel=True)

            cat_obj = await guild.create_category(cat_name, overwrites=cat_overwrites)
            existing_cats[cat_name] = cat_obj
            print(f'  ✅ Created category: {cat_name}{"  [private]" if is_private else ""}')

        # --- Sync channels inside this category ---
        await sync_channels(guild, cat_obj, cat_data, role_map, is_private)

    print('\n✅ Server update complete!')

    if not config.get('keep_in_guild', False):
        try:
            print('Removing bot from server...')
            await guild.leave()
            print('✅ Bot has left the server')
        except Exception as e:
            print(f'❌ Error leaving server: {e}')
    else:
        print('ℹ️ Bot stays in server (keep_in_guild=true)')


async def sync_channels(guild, cat_obj, cat_data, role_map, cat_private):
    """
    Sync text and voice channels inside a category.
    Creates missing, deletes removed, updates permissions on changed ones.
    """
    desired_text   = {ch['name']: ch for ch in cat_data.get('text_channels',  [])}
    desired_voice  = {ch['name']: ch for ch in cat_data.get('voice_channels', [])}

    existing_text  = {ch.name: ch for ch in cat_obj.text_channels}
    existing_voice = {ch.name: ch for ch in cat_obj.voice_channels}

    # Delete text channels no longer desired
    for ch_name, ch_obj in list(existing_text.items()):
        if ch_name not in desired_text:
            try:
                await ch_obj.delete()
                print(f'    🗑️  Deleted text channel: #{ch_name}')
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f'    Could not delete #{ch_name}: {e}')

    # Delete voice channels no longer desired
    for ch_name, ch_obj in list(existing_voice.items()):
        if ch_name not in desired_voice:
            try:
                await ch_obj.delete()
                print(f'    🗑️  Deleted voice channel: {ch_name}')
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f'    Could not delete {ch_name}: {e}')

    # Create / update text channels
    for ch_name, ch_data in desired_text.items():
        perms = ch_data.get('permissions') if isinstance(ch_data, dict) else None
        if cat_private and not perms:
            perms = {'deny': ['@everyone'], 'view': []}

        if ch_name in existing_text:
            print(f'    Text channel exists: #{ch_name}')
            if perms:
                await apply_channel_permissions(existing_text[ch_name], perms, role_map)
                print(f'      └─ permissions refreshed')
        else:
            ch = await guild.create_text_channel(ch_name, category=cat_obj)
            print(f'    ✅ Created text channel: #{ch_name}')
            if perms:
                await apply_channel_permissions(ch, perms, role_map)
                print(f'      └─ permissions applied')

    # Create / update voice channels
    for ch_name, ch_data in desired_voice.items():
        perms = ch_data.get('permissions') if isinstance(ch_data, dict) else None
        if cat_private and not perms:
            perms = {'deny': ['@everyone'], 'view': []}

        if ch_name in existing_voice:
            print(f'    Voice channel exists: {ch_name}')
            if perms:
                await apply_channel_permissions(existing_voice[ch_name], perms, role_map)
                print(f'      └─ permissions refreshed')
        else:
            ch = await guild.create_voice_channel(ch_name, category=cat_obj)
            print(f'    ✅ Created voice channel: {ch_name}')
            if perms:
                await apply_channel_permissions(ch, perms, role_map)
                print(f'      └─ permissions applied')

    # Create / delete forum channels
    desired_forum  = {ch['name']: ch for ch in cat_data.get('forum_channels', [])}
    existing_forum = {ch.name: ch for ch in cat_obj.forums}

    for ch_name, ch_obj in list(existing_forum.items()):
        if ch_name not in desired_forum:
            try:
                await ch_obj.delete()
                print(f'    🗑️  Deleted forum channel: {ch_name}')
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f'    Could not delete forum {ch_name}: {e}')

    for ch_name, ch_data in desired_forum.items():
        if ch_name in existing_forum:
            print(f'    Forum channel exists: {ch_name}')
        else:
            try:
                ch = await guild.create_forum_channel(ch_name, category=cat_obj)
                print(f'    ✅ Created forum channel: {ch_name}')
            except Exception as e:
                print(f'    Could not create forum {ch_name}: {e}')


# ── Entry point ───────────────────────────────────────────────────────────────
bot.run(SETUPBOT_TOKEN)
