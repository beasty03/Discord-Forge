import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import logging
from pathlib import Path

_log = logging.getLogger("launcher")
_DB_PATH = str(Path(__file__).parent.parent.parent / 'database' / 'moderation.db')


class ModerationDB:
    def __init__(self, db_path: str = _DB_PATH):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS warnings (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    TEXT NOT NULL,
                    guild_id   TEXT NOT NULL,
                    reason     TEXT,
                    warned_by  TEXT,
                    timestamp  DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

    def add_warning(self, user_id: str, guild_id: str, reason: str, warned_by: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                'INSERT INTO warnings (user_id, guild_id, reason, warned_by) VALUES (?,?,?,?)',
                (user_id, guild_id, reason, warned_by),
            )
            count = conn.execute(
                'SELECT COUNT(*) FROM warnings WHERE user_id=? AND guild_id=?',
                (user_id, guild_id),
            ).fetchone()[0]
        return count

    def get_warnings(self, user_id: str, guild_id: str) -> list:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                'SELECT id, reason, warned_by, timestamp FROM warnings '
                'WHERE user_id=? AND guild_id=? ORDER BY timestamp DESC',
                (user_id, guild_id),
            ).fetchall()
        return [{'id': r[0], 'reason': r[1], 'warned_by': r[2], 'timestamp': r[3]} for r in rows]

    def clear_warnings(self, user_id: str, guild_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM warnings WHERE user_id=? AND guild_id=?', (user_id, guild_id))
            return conn.total_changes


class Moderation(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db  = ModerationDB()

    async def _forge_post(self, action_type: str, member: discord.Member, reason: str, warns_count=None):
        api_url   = getattr(self.bot, 'forge_api_url',   '')
        server_id = getattr(self.bot, 'forge_server_id', '')
        bot_id    = getattr(self.bot, 'forge_bot_id',    '')
        api_token = getattr(self.bot, 'forge_api_token', '')
        if not (api_url and server_id and bot_id and api_token):
            return
        try:
            import aiohttp
            payload = {
                'server_id':   server_id,
                'bot_id':      bot_id,
                'action_type': action_type,
                'user_id':     str(member.id),
                'username':    str(member),
                'reason':      reason,
            }
            if warns_count is not None:
                payload['warns_count'] = warns_count
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f'{api_url}/api/local-bot/moderation',
                    json=payload,
                    headers={'X-Bot-Token': api_token},
                    timeout=aiohttp.ClientTimeout(total=10),
                )
        except Exception as e:
            _log.debug(f'Moderation forge post failed: {e}')

    # ── /warn ──────────────────────────────────────────────────────────────

    @app_commands.command(name='warn', description='Warn a member')
    @app_commands.describe(member='Member to warn', reason='Reason for the warning')
    @app_commands.default_permissions(kick_members=True)
    async def warn(self, interaction: discord.Interaction,
                   member: discord.Member, reason: str = 'No reason provided'):
        if member.bot:
            await interaction.response.send_message('❌ Cannot warn bots.', ephemeral=True)
            return
        count = self.db.add_warning(
            str(member.id), str(interaction.guild_id), reason, str(interaction.user)
        )
        try:
            await member.send(
                f'⚠️ You have been warned in **{interaction.guild.name}**.\n'
                f'Reason: {reason}\n'
                f'You now have **{count}** warning(s).'
            )
        except discord.Forbidden:
            pass
        await interaction.response.send_message(
            f'⚠️ **{member.name}** has been warned — {reason} '
            f'({count} warning(s) total).'
        )
        await self._forge_post('warn', member, reason, warns_count=count)

    # ── /warnings ──────────────────────────────────────────────────────────

    @app_commands.command(name='warnings', description='Show warnings for a member')
    @app_commands.describe(member='Member to check')
    @app_commands.default_permissions(kick_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        warns = self.db.get_warnings(str(member.id), str(interaction.guild_id))
        if not warns:
            await interaction.response.send_message(
                f'✅ {member.mention} has no warnings.', ephemeral=True
            )
            return
        lines = [f'**{member.name}** — {len(warns)} warning(s)']
        for w in warns[:10]:
            lines.append(f'• {w["timestamp"][:10]}: {w["reason"]} *(by {w["warned_by"]})*')
        if len(warns) > 10:
            lines.append(f'…and {len(warns) - 10} more')
        await interaction.response.send_message('\n'.join(lines), ephemeral=True)

    # ── /clearwarnings ─────────────────────────────────────────────────────

    @app_commands.command(name='clearwarnings', description='Clear all warnings for a member')
    @app_commands.describe(member='Member to clear')
    @app_commands.default_permissions(administrator=True)
    async def clearwarnings(self, interaction: discord.Interaction, member: discord.Member):
        self.db.clear_warnings(str(member.id), str(interaction.guild_id))
        await interaction.response.send_message(
            f'✅ Cleared all warnings for {member.mention}.', ephemeral=True
        )

    # ── /kick ──────────────────────────────────────────────────────────────

    @app_commands.command(name='kick', description='Kick a member from the server')
    @app_commands.describe(member='Member to kick', reason='Reason for the kick')
    @app_commands.default_permissions(kick_members=True)
    async def kick(self, interaction: discord.Interaction,
                   member: discord.Member, reason: str = 'No reason provided'):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                '❌ I cannot kick this member (role hierarchy).', ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            await member.send(
                f'👢 You have been kicked from **{interaction.guild.name}**.\nReason: {reason}'
            )
        except discord.Forbidden:
            pass
        await member.kick(reason=f'{reason} (by {interaction.user})')
        await interaction.followup.send(f'🚪 **{member}** has been kicked. Reason: {reason}')
        await self._forge_post('kick', member, reason)

    # ── /ban ───────────────────────────────────────────────────────────────

    @app_commands.command(name='ban', description='Ban a member from the server')
    @app_commands.describe(member='Member to ban', reason='Reason for the ban')
    @app_commands.default_permissions(ban_members=True)
    async def ban(self, interaction: discord.Interaction,
                  member: discord.Member, reason: str = 'No reason provided'):
        if member.top_role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                '❌ I cannot ban this member (role hierarchy).', ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            await member.send(
                f'🔨 You have been banned from **{interaction.guild.name}**.\nReason: {reason}'
            )
        except discord.Forbidden:
            pass
        await member.ban(reason=f'{reason} (by {interaction.user})', delete_message_days=0)
        await interaction.followup.send(f'🚨 **{member}** has been banned. Reason: {reason}')
        await self._forge_post('ban', member, reason)


async def setup(bot: commands.Bot):
    await bot.add_cog(Moderation(bot))
