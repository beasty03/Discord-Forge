import webbrowser
import os 
import sys
import json
import discord
import asyncio

# Add parent directory to path FIRST
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLIENT_ID = 1486718913273135124

from discord.ext import commands

def generate_invite_link(client_id, permissions=8):
    """
    Generate Discord bot invite link
    
    Permissions:
    8 = Administrator (all permissions)
    """
    invite_url = f"https://discord.com/api/oauth2/authorize?client_id={client_id}&permissions={permissions}&scope=bot%20applications.commands"
    return invite_url

async def check_bot_in_server(bot_token, guild_id):
    """
    Check if bot is already in the specified server
    Returns: (is_in_server: bool, guild_name: str or None)
    """
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    
    result = {'in_server': False, 'guild_name': None, 'checked': False}
    
    @client.event
    async def on_ready():
        result['checked'] = True  # Mark that we successfully connected
        guild = client.get_guild(int(guild_id))
        
        if guild:
            result['in_server'] = True
            result['guild_name'] = guild.name
            print(f"[SUCCESS] Bot is already in server: '{guild.name}'")
            print(f"          Guild ID: {guild_id}\n")
        else:
            print(f"[INFO] Bot is NOT in the specified server (Guild ID: {guild_id})\n")
        
        await client.close()
    
    try:
        # Use asyncio.wait_for to add a timeout
        await asyncio.wait_for(client.start(bot_token), timeout=10.0)
    except asyncio.TimeoutError:
        print("[WARNING] Connection timeout - cannot verify bot status\n")
        await client.close()
    except discord.LoginFailure:
        print("[ERROR] Invalid bot token\n")
        await client.close()
    except Exception as e:
        print(f"[WARNING] Could not verify bot status: {e}\n")
        try:
            await client.close()
        except:
            pass
    
    # Only return True if we successfully checked AND bot is in server
    if result['checked']:
        return result['in_server'], result['guild_name']
    else:
        # If we couldn't check, assume bot is NOT in server (safe default)
        return False, None
    
async def setup(bot: commands.Bot):
    pass  # This cog doesn't add any commands, just provides utility function

if __name__ == "__main__":
    print("=== Discord Bot Invite Link Generator ===\n")
    
    # Try to load config to get guild_id and bot_token
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    
    guild_id = None
    bot_token = None
    bot_already_in_server = False
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8-sig') as f:
                config = json.load(f)
                guild_id = config.get('server', {}).get('guild_id')
                bot_token = config.get('bot_token')
                
            if guild_id and bot_token:
                print("Checking if bot is already in your server...\n")
                
                try:
                    bot_already_in_server, server_name = asyncio.run(check_bot_in_server(bot_token, guild_id))
                except KeyboardInterrupt:
                    print("\n[INFO] Check interrupted by user\n")
                except Exception as e:
                    print(f"[WARNING] Could not verify bot status: {e}\n")
        
        except Exception as e:
            print(f"[WARNING] Could not read config.json: {e}\n")
    
    # Generate and show invite link
    if not bot_already_in_server:
        invite_link = generate_invite_link(CLIENT_ID)
        print(f"Bot Invite Link:\n{invite_link}\n")
        
        print("Opening invite link in browser...")
        webbrowser.open(invite_link)
        
        print("\nSteps to invite the bot:")
        print("1. Select your server in the browser window")
        print("2. Click 'Authorize'")
        print("3. Complete the captcha if prompted")
        
        if not guild_id:
            print("\nTo get your Guild ID:")
            print("1. Enable Developer Mode: Discord Settings → Advanced → Developer Mode")
            print("2. Right-click your server → Copy Server ID")
            print("3. Add the Guild ID to config.json")
    else:
        print("No need to invite the bot - it's already in your server!")
        print("\nYou can proceed with the next steps:")
        print("  python setup_server.py")
    
    print("\n" + "="*50)
    
    # Ensure script exits cleanly
    sys.exit(0)