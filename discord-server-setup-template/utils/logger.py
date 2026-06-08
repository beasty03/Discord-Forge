# ============================================================================
# LOGGING UTILITY
# ============================================================================
#
# Provides centralized logging for the entire bot
# Logs to both console and file with rotation
#
# ============================================================================

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime

# ============================================================================
# IMPORT CONFIGURATION
# ============================================================================

try:
    from utils.config_loader import load_config
    
    config = load_config()
    
    # Get paths from config
    if 'paths' in config:
        LOGS_DIR = Path(config['paths'].get('logs_dir', 'logs'))
        LOG_FILE = "bot.log"  # Just the filename, will be combined with LOGS_DIR
    else:
        LOGS_DIR = Path("logs")
        LOG_FILE = "bot.log"
    
    # Logging settings (with fallback defaults)
    ENABLE_FILE_LOGGING = True
    LOG_LEVEL = "INFO"
    MAX_LOG_SIZE = 5 * 1024 * 1024  # 5 MB
    LOG_BACKUP_COUNT = 3
    
except ImportError:
    # Fallback defaults if config_loader doesn't exist
    ENABLE_FILE_LOGGING = True
    LOG_LEVEL = "INFO"
    LOG_FILE = "bot.log"
    MAX_LOG_SIZE = 5 * 1024 * 1024
    LOG_BACKUP_COUNT = 3
    LOGS_DIR = Path("logs")

# ============================================================================
# LOGGER SETUP
# ============================================================================

def setup_logger(name: str = "discord_bot"):
    """
    Creates and configures a logger instance
    
    Args:
        name (str): Logger name (usually module name)
        
    Returns:
        logging.Logger: Configured logger instance
    """
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    
    # Prevent duplicate handlers
    if logger.handlers:
        return logger
    
    # ========================================
    # Console Handler (colored output)
    # ========================================
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # Console format with colors
    console_format = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # ========================================
    # File Handler (with rotation)
    # ========================================
    
    if ENABLE_FILE_LOGGING:
        # Ensure log directory exists
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        
        # Combine logs directory with log filename
        log_path = LOGS_DIR / LOG_FILE
        
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=MAX_LOG_SIZE,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(logging.DEBUG)
        
        # File format (more detailed)
        file_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)
    
    return logger

# ============================================================================
# COLORED CONSOLE OUTPUT
# ============================================================================

class ColoredFormatter(logging.Formatter):
    """
    Custom formatter that adds colors to console output
    """
    
    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }
    
    def format(self, record):
        # Store original levelname
        original_levelname = record.levelname
        
        # Add color to level name
        if original_levelname in self.COLORS:
            record.levelname = f"{self.COLORS[original_levelname]}{original_levelname}{self.COLORS['RESET']}"
        
        # Format the message
        result = super().format(record)
        
        # Restore original levelname
        record.levelname = original_levelname
        
        return result

# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def log_startup():
    """Logs bot startup information"""
    logger = logging.getLogger("discord_bot")
    logger.info("=" * 60)
    logger.info("BOT STARTING UP")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Log Level: {LOG_LEVEL}")
    logger.info(f"File Logging: {'Enabled' if ENABLE_FILE_LOGGING else 'Disabled'}")
    logger.info(f"Logs Directory: {LOGS_DIR}")
    logger.info("=" * 60)

def log_shutdown():
    """Logs bot shutdown information"""
    logger = logging.getLogger("discord_bot")
    logger.info("=" * 60)
    logger.info("BOT SHUTTING DOWN")
    logger.info(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

def log_cog_loaded(cog_name: str):
    """Logs when a cog is loaded"""
    logger = logging.getLogger("discord_bot")
    logger.info(f"✅ Loaded cog: {cog_name}")

def log_cog_failed(cog_name: str, error: Exception):
    """Logs when a cog fails to load"""
    logger = logging.getLogger("discord_bot")
    logger.error(f"❌ Failed to load cog: {cog_name}")
    logger.error(f"   Error: {error}")

def log_command_used(user: str, command: str, guild: str = None):
    """Logs when a command is used"""
    logger = logging.getLogger("discord_bot")
    guild_info = f" in {guild}" if guild else ""
    logger.info(f"Command '{command}' used by {user}{guild_info}")

# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    # Test the logger
    logger = setup_logger()
    
    log_startup()
    
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")
    
    log_cog_loaded("TestCog")
    log_command_used("TestUser#1234", "/test", "Test Server")
    
    log_shutdown()