import sqlite3
import json
import os
import sys

# Load config
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_JSON = os.path.join(parent_dir, 'config.json')

with open(CONFIG_JSON, 'r', encoding='utf-8-sig') as f:
    config = json.load(f)

DB_FILE = config['paths'].get('database_file', 'database/user_database.db')
TEMPLATE_DIR = config['paths']['template_dir']
TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, 'user_database_template.json')

print("[DatabaseInit] Initializing user database...")
print(f"[DatabaseInit] Database file: {DB_FILE}")
print(f"[DatabaseInit] Template file: {TEMPLATE_PATH}")

# Ensure database directory exists
db_dir = os.path.dirname(DB_FILE)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir)
    print(f"[DatabaseInit] Created directory: {db_dir}")

try:
    # Load template
    with open(TEMPLATE_PATH, 'r', encoding='utf-8') as f:
        template = json.load(f)
    
    # Connect to database
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Build table from template
    user_fields = template.get("user", {})
    columns = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
    
    for field_name, default_value in user_fields.items():
        if field_name == "user_id":
            columns.append("user_id TEXT UNIQUE")
        else:
            columns.append(f"{field_name} TEXT")
    
    create_sql = f"CREATE TABLE IF NOT EXISTS users ({', '.join(columns)})"
    cursor.execute(create_sql)
    conn.commit()
    
    print("[DatabaseInit] ✅ Database initialized successfully!")
    print(f"[DatabaseInit] Location: {os.path.abspath(DB_FILE)}")
    
    conn.close()
    print("[DatabaseInit] Database connection closed.")
    
except FileNotFoundError:
    print(f"[DatabaseInit] ❌ Error: Template file not found!")
    print(f"[DatabaseInit] Expected location: {TEMPLATE_PATH}")
    sys.exit(1)
except Exception as e:
    print(f"[DatabaseInit] ❌ Error initializing database: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
