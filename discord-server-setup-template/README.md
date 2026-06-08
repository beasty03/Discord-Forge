# Auto Discord Server Deployment

Automatically set up a complete Discord server with predefined roles, channels, categories, and moderation tools using a simple PowerShell script.

## Features

- Automated Server Setup - Configure your entire Discord server in minutes
- Role Management - Automatically create moderation roles with specific permissions
- Channel Organization - Set up categories, text channels, voice channels, and forum channels
- Moderation Tools - Built-in moderation template with logs and reports
- Welcome System - Optional welcome channels and roles
- User Database - SQLite database for tracking user data
- Diff-Based Updates - `Update_server.py` applies only the changes since last setup (no full wipe)
- Customizable - Add your own roles, categories, and channels


## Prerequisites

### 1. Install Python (use Microsoft Store)
- Open **Microsoft Store** on Windows
- Search for **"Python install manager"** (or latest version available)
- Click **"Get"**
- **Add python to PATH y/N: yes**

**Alternative:** Download from [python.org](https://www.python.org/downloads/)
- **Important:** During installation, check **"Add Python to PATH"**

### 2. Install Git
- Download **Git** from [git-scm.com/downloads](https://git-scm.com/downloads)
- Run the installer with default settings
- Restart PowerShell after installation

### 3. Install Required Python Packages
Open Command Prompt or PowerShell and run:
```bash
pip install discord.py aiohttp
```

## Structure view 
```
 discord-server-setup/
├── cogs/
│   ├── Database_management/          # Example cog folder
│   │     ├── database_manager.py     # Main cog file
│   │     ├── variables.py            # Cog-specific variables
│   │     └── README.md               # Information about this cog
│   ├── __init__.py
│   └── ...
│
├── setup_cogs/
│   ├── generate_invite.py            # Setup bot invite to server script        
│   └── init_database.py              # Database initialization script
│
├── templates/
│   ├── moderation_template.json      # Moderation roles and channels template
│   ├── user_database_template.json   # Database template
│   └── welcome_template.json         # Welcome channels template
│
├── utils/
│   ├── config_loader.py              # Multi-bot logic
│   └── logger.py                     # Logging logic
│
├── database/                         # Auto-created; stores user_database.db
├── logs/                             # Auto-created; stores bot.log
│
├── config.json                       # Configuration: server settings and bot tokens
├── Setup_server.py                   # Full server setup (wipes and rebuilds)
├── Update_server.py                  # Diff-based update (only applies changes)
├── launcher.py                       # Launches the bot and loads cogs
├── setup.ps1                         # Main PowerShell setup script
├── bot_config.ps1                    # Bot config and cog importation
└── README.md                         # This file
```

## First Run 

1. Create a folder where you would like to keep your data
2. Download `setup.ps1` from the repository
3. Place the script in the folder
4. Right-click `setup.ps1` → `"Run with PowerShell"`

The script will guide you through configuring `config.json` and running `Setup_server.py`.

## Running the Bot

After setup is complete, start the bot with:
```bash
python launcher.py
```

To launch a specific bot when multiple are configured:
```bash
python launcher.py --bot BotName
```

Press **Ctrl+C** to stop the bot.

## Updating an Existing Server

To apply config changes without a full wipe:
```bash
python Update_server.py
```

This compares the current Discord server state against `config.json` and only creates/deletes/updates what changed (roles, categories, channels, server name/icon).

## Recommended Development Environment

### Visual Studio Code (Optional but Recommended)

**Why VS Code?**
- Built-in terminal for running scripts
- Syntax highlighting for Python and PowerShell
- IntelliSense for code completion
- Integrated Git support
- Easy file management

#### Install VS Code
1. Download from [code.visualstudio.com](https://code.visualstudio.com/)
2. Run the installer with default settings
3. Launch VS Code

#### Required Extensions

Install these extensions for the best development experience:

**Python Development:**
- **Python** (by Microsoft) - Python language support
  - Extension ID: `ms-python.python`
  - Provides IntelliSense, debugging, and code formatting

**PowerShell Support:**
- **PowerShell** (by Microsoft) - PowerShell language support
  - Extension ID: `ms-vscode.powershell`
  - Syntax highlighting and script debugging

**Additional Recommended Extensions:**
- **GitLens** (by GitKraken) - Enhanced Git integration
  - Extension ID: `eamodio.gitlens`
  - View commit history and blame annotations

- **Discord Presence** (by iCrawl) - Show what you're working on in Discord
  - Extension ID: `icrawl.discord-vscode`
  - Optional: Display your coding activity

- **Error Lens** (by Alexander) - Highlight errors inline
  - Extension ID: `usernamehw.errorlens`
  - See errors and warnings directly in your code

#### How to Install Extensions

**Method 1: Through VS Code**
1. Open VS Code
2. Click the **Extensions** icon in the sidebar (or press `Ctrl+Shift+X`)
3. Search for the extension name
4. Click **Install**

---

# COG DEVELOPMENT GUIDE

This guide ensures consistency and proper functionality when creating new cogs for the Discord bot.

---

## TABLE OF CONTENTS

1. [File Structure](#file-structure)
2. [Required Imports](#required-imports)
3. [Configuration Setup](#configuration-setup)
4. [Database Setup (Optional)](#database-setup-optional)
5. [Cog Class Structure](#cog-class-structure)
6. [Setup Function](#setup-function)
7. [Command Best Practices](#command-best-practices)
8. [Error Handling](#error-handling)
9. [Logging](#logging)
10. [Testing Checklist](#testing-checklist)
11. [Examples](#examples)

---

## FILE STRUCTURE

### Standard Cog Location
```
cogs/
├── YourCategory/          # Category folder (e.g., Casino, Moderation, Fun)
│   ├── __init__.py        # Required (can be empty)
│   ├── variables.py       # Category-specific configuration
│   ├── cog_name.py        # Your cog file
│   └── other_cog.py       # Additional cogs in same category
```

### Naming Conventions

- **Folder names**: PascalCase (e.g., `Casino`, `Moderation`)
- **File names**: snake_case (e.g., `gamble.py`, `blackjack.py`)
- **Class names**: PascalCase + "Cog" suffix (e.g., `GambleCog`, `BlackjackCog`)

---

## REQUIRED IMPORTS

### Minimum Required Imports

```python
import discord
from discord.ext import commands
from discord import app_commands
import sys
from pathlib import Path
```

### Additional Common Imports

```python
import sqlite3                              # For database operations
import random                               # For random elements
import time                                 # For cooldowns/timestamps
from datetime import datetime, timedelta    # For time-based features
import asyncio                              # For async operations
```

---

## CONFIGURATION SETUP

### 1. Create `variables.py` in Your Category Folder

```python
# variables.py

from utils.config_loader import get_bot_token, load_config
from pathlib import Path

# ============================================================================
# CENTRAL CONFIG LOADER
# ============================================================================

BOT_TOKEN = get_bot_token()  # or get_bot_token('SpecificBotName')
config = load_config()
GUILD_ID = int(config['guild_id'])
SERVER_NAME = config['server_name']

# Database path from config (nested under 'paths')
if 'paths' in config:
    paths = config['paths']
    if 'database_file' in paths:
        DATABASE_NAME = str(Path(paths['database_file']))
    elif 'db_file' in paths:
        DATABASE_NAME = str(Path(paths['db_file']))
    else:
        PROJECT_ROOT = Path(__file__).parent.parent.parent
        DATABASE_DIR = PROJECT_ROOT / 'database'
        DATABASE_DIR.mkdir(exist_ok=True)
        DATABASE_NAME = str(DATABASE_DIR / 'user_database.db')
else:
    PROJECT_ROOT = Path(__file__).parent.parent.parent
    DATABASE_DIR = PROJECT_ROOT / 'database'
    DATABASE_DIR.mkdir(exist_ok=True)
    DATABASE_NAME = str(DATABASE_DIR / 'user_database.db')

# ============================================================================
# YOUR COG-SPECIFIC SETTINGS
# ============================================================================

FEATURE_ENABLED = True
MAX_VALUE = 1000
MIN_VALUE = 10
COOLDOWN_SECONDS = 5

# Embed Colors (in hex)
COLOR_SUCCESS = 0x00FF00  # Green
COLOR_ERROR = 0xFF0000    # Red
COLOR_WARNING = 0xFFA500  # Orange
COLOR_INFO = 0x00BFFF     # Light Blue

# Messages
MESSAGE_SUCCESS = "Operation completed successfully!"
MESSAGE_ERROR = "An error occurred!"
```

### 2. Import Variables in Your Cog

```python
import sys
from pathlib import Path

# Add the cog's folder to path to import variables.py
sys.path.insert(0, str(Path(__file__).parent))
import variables as var
```

---

## DATABASE SETUP (OPTIONAL)

### If Your Cog Uses a Database

#### 1. Create Database Initialization Function
```python
def init_database():
    """Initialize the SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(var.DATABASE_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS your_table_name (
            user_id INTEGER PRIMARY KEY,
            data_field TEXT NOT NULL,
            counter INTEGER DEFAULT 0,
            created_at REAL DEFAULT (julianday('now'))
        )
    ''')
    
    conn.commit()
    conn.close()
```

#### 2. Create Helper Functions
```python
def get_user_data(user_id: int):
    conn = sqlite3.connect(var.DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM your_table_name WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result

def update_user_data(user_id: int, data: str):
    conn = sqlite3.connect(var.DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO your_table_name (user_id, data_field)
        VALUES (?, ?)
    ''', (user_id, data))
    conn.commit()
    conn.close()
```

#### 3. Important Database Rules
- Always use **unique table names** (e.g., `casino`, `moderation_logs`, `user_levels`)
- Always **close connections** after use
- Use **parameterized queries** to prevent SQL injection: `cursor.execute('SELECT * FROM table WHERE id = ?', (value,))`
- Call `init_database()` in the `setup()` function

---

## COG CLASS STRUCTURE

### Basic Template
```python 
class YourCog(commands.Cog):
    """Brief description of what this cog does."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(
        name="commandname",
        description="What this command does"
    )
    @app_commands.describe(
        parameter="Description of this parameter"
    )
    async def command_name(
        self, 
        interaction: discord.Interaction, 
        parameter: str
    ):
        embed = discord.Embed(
            title="Title",
            description="Description",
            color=var.COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)
```

### Important Notes

- Class name should be descriptive + "Cog" suffix
- Always include `__init__` method with `bot` parameter
- Use `@app_commands.command` for slash commands
- Use `@app_commands.describe` to document parameters
- Always respond to interactions (or defer if processing takes time)

---

## SETUP FUNCTION

### Required at Bottom of Every Cog File
```python 
async def setup(bot: commands.Bot):
    """Required for the launcher to load this module."""
    # init_database()  # Uncomment if your cog uses a database
    await bot.add_cog(YourCog(bot))
    print("✅ YourCategory/YourCog loaded successfully")
```

### Important Rules

- **MUST** be named `setup`
- **MUST** be `async`
- **MUST** accept `bot: commands.Bot` parameter
- **MUST** call `await bot.add_cog(YourCog(bot))`
- Call `init_database()` here if your cog uses a database

---

## COMMAND BEST PRACTICES

### 1. Always Use Embeds for Responses
```python 
embed = discord.Embed(
    title="Command Title",
    description="Main message",
    color=var.COLOR_SUCCESS
)
embed.add_field(name="Field Name", value="Field Value", inline=True)
embed.set_footer(text=f"Requested by {interaction.user.display_name}")
embed.timestamp = datetime.utcnow()

await interaction.response.send_message(embed=embed)
```

### 2. Use Ephemeral for Errors
```python 
await interaction.response.send_message(embed=error_embed, ephemeral=True)
```

### 3. Add Cooldowns
```python 
@app_commands.command(name="command")
@app_commands.checks.cooldown(1, 60.0)  # 1 use per 60 seconds
async def command(self, interaction: discord.Interaction):
    pass
```

### 4. Defer Long Operations
```python 
@app_commands.command(name="command")
async def command(self, interaction: discord.Interaction):
    await interaction.response.defer()
    await asyncio.sleep(5)  # Long operation
    await interaction.followup.send(embed=embed)
```

### 5. Validate User Input
```python 
if amount <= 0:
    embed = discord.Embed(
        title="❌ Invalid Input",
        description="Amount must be positive!",
        color=var.COLOR_ERROR
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    return
```

---

## ERROR HANDLING

### Command-Level Error Handler
```python 
@command_name.error
async def command_error(self, interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        embed = discord.Embed(
            title="⏰ Cooldown Active",
            description=f"Try again in {error.retry_after:.1f} seconds",
            color=var.COLOR_WARNING
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="❌ Error",
            description=f"An error occurred: {str(error)}",
            color=var.COLOR_ERROR
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
```

### Cog-Level Error Handler
```python 
async def cog_app_command_error(
    self, 
    interaction: discord.Interaction, 
    error: app_commands.AppCommandError
):
    if isinstance(error, app_commands.CommandOnCooldown):
        pass  # Handle cooldown
    elif isinstance(error, app_commands.MissingPermissions):
        pass  # Handle permissions
    else:
        pass  # Generic error
```

---

## LOGGING

```python 
from utils.logger import setup_logger

logger = setup_logger(__name__)

logger.info(f"User {interaction.user} used command /commandname")
logger.error(f"Error in command: {str(error)}")
logger.warning(f"Warning: unusual behavior detected")
``` 

---

## TESTING CHECKLIST

Before considering your cog complete:

- [ ] Cog loads without errors in launcher
- [ ] All commands appear in Discord (`/` autocomplete)
- [ ] Commands respond correctly
- [ ] Error messages are user-friendly
- [ ] Database tables are created correctly (if applicable)
- [ ] No SQL injection vulnerabilities
- [ ] Cooldowns work as expected
- [ ] Embeds display correctly
- [ ] Variables are properly imported from `variables.py`
- [ ] `setup()` function is present and correct
- [ ] No hardcoded values (use `variables.py`)

---

## EXAMPLES

### Example 1: Simple Command (No Database)
```python
import discord
from discord.ext import commands
from discord import app_commands
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import variables as var

class PingCog(commands.Cog):
    """Simple ping command."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="ping", description="Check bot latency")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong!",
            description=f"Latency: **{latency}ms**",
            color=var.COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(PingCog(bot))
    print("✅ Utility/Ping cog loaded successfully")
```

### Example 2: Command with Database
```python
import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import variables as var

def init_database():
    conn = sqlite3.connect(var.DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_points (
            user_id INTEGER PRIMARY KEY,
            points INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def add_points(user_id: int, points: int):
    conn = sqlite3.connect(var.DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO user_points (user_id, points) 
        VALUES (?, ?)
        ON CONFLICT(user_id) DO UPDATE SET points = points + ?
    ''', (user_id, points, points))
    conn.commit()
    conn.close()

class PointsCog(commands.Cog):
    """Points system."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot
    
    @app_commands.command(name="addpoints", description="Add points to user")
    @app_commands.describe(amount="Number of points to add")
    async def addpoints(self, interaction: discord.Interaction, amount: int):
        if amount <= 0:
            embed = discord.Embed(
                title="❌ Invalid Amount",
                description="Points must be positive!",
                color=var.COLOR_ERROR
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        add_points(interaction.user.id, amount)
        
        embed = discord.Embed(
            title="✅ Points Added",
            description=f"Added **{amount}** points to {interaction.user.mention}",
            color=var.COLOR_SUCCESS
        )
        await interaction.response.send_message(embed=embed)

async def setup(bot: commands.Bot):
    init_database()
    await bot.add_cog(PointsCog(bot))
    print("✅ Points cog loaded successfully")
```
