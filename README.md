# DiscordForge

A self-hosted web platform for designing, deploying, and managing Discord servers and bots — without writing code.

You run it on your own machine or server. Users register on your instance and manage their bots locally.

---

## Features

- **Server wizard** — step-by-step builder for channels, categories, roles, and permissions
- **Docker-per-bot runner** — each bot runs in its own isolated container; start, stop, and restart from the dashboard
- **Live dashboard** — real-time ping, uptime, messages-today, cog health badge, and per-member message counts via 30-second heartbeat
- **Script library** — browse, install, and uninstall cogs from GitHub-hosted repositories; loaded/failed badge per script
- **Member management** — full member list with roles, message counts, and warning history; warn/kick/ban directly from the dashboard
- **Moderation cog** — `/warn`, `/warnings`, `/clearwarnings`, `/kick`, `/ban` slash commands; warnings stored in SQLite and synced back to the dashboard
- **Per-user timezone** — all timestamps across the UI displayed in the user's chosen timezone
- **Collaborators** — invite friends to help manage servers with per-permission access
- **Theme engine** — 20+ UI themes including animated overlays (all free)
- **Discord OAuth** — link your Discord account for avatar and identity
- **Activity log + webhooks** — every bot event, member sync, and moderation action is logged; Discord webhook notifications supported
- **Password reset** via SMTP (optional)
- **hCaptcha** support on register/login
- **Admin portal** for instance management

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · Flask · Flask-SocketIO · gevent |
| Frontend | React 19 · Vite 8 |
| Auth | Session-based · Discord OAuth2 · hCaptcha |
| Storage | JSON flat files (no database required) |
| Bot runner | Docker SDK — one container per bot |
| Cog storage | SQLite per cog (warnings, casino, etc.) |
| Production | gevent WSGI · Docker Compose |

---

## Quick start (local)

**1. Clone the repo**
```bash
git clone https://github.com/beasty03/Discord-Forge.git
cd Discord-Forge
```

**2. Create your `.env`**
```bash
cp app/.env.example app/.env
# edit app/.env and fill in your values (see Environment variables below)
```

**3. Install dependencies**
```bash
cd app
pip install -r requirements.txt
```

**4. Start the app**

Option A — control panel (Windows, recommended):
```powershell
.\app\deploy\control.ps1
# then press [1] to start
```

Option B — direct:
```bash
cd app
python server.py
```

App runs at `http://localhost:5000`.

---

## Control panel (`app/deploy/control.ps1`)

A PowerShell menu for managing the app on Windows:

```
  +------------------------------------------+
  |     DiscordForge  Control Panel          |
  +------------------------------------------+
  |  [1] Start app                           |
  |  [2] Stop app                            |
  |  [3] Restart app                         |
  |  [4] Status check                        |
  |  [5] View logs  (tail flask.log)         |
  |  [6] Rate-limit burst test               |
  |  [7] Open stress tests in browser        |
  |  [8] Check / update public IP            |
  |  [Q] Quit                                |
  +------------------------------------------+
```

Option **[8]** detects your current public IP, updates `control.ps1` and `app/.env` in place, and optionally pushes the new IP to DuckDNS. Configure DuckDNS at the top of the script:

```powershell
$DuckDnsToken  = 'your-token'
$DuckDnsDomain = 'your-subdomain'   # subdomain only, no .duckdns.org
```

---

## Docker (recommended)

```bash
cp app/.env.example app/.env
# edit app/.env

docker compose up -d --build
```

The `docker-compose.yml` mounts `./data` as a volume so user data persists across rebuilds.

**After any change to `launcher.py` or the cogs, rebuild the bot image:**

```bash
docker build -t discordforge-bot ./discord-server-setup-template/
```

Each bot you start from the dashboard runs as a sibling container using this image. The Flask container communicates with them over the Docker socket.

---

## Environment variables

Copy `app/.env.example` to `app/.env` and fill in:

| Variable | Required | Notes |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | **Yes** | Fernet key — generate once, never change. `py -3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DISCORD_CLIENT_ID` | For OAuth | From [Discord Developer Portal](https://discord.com/developers/applications) |
| `DISCORD_CLIENT_SECRET` | For OAuth | — |
| `DISCORD_REDIRECT_URI` | For OAuth | `http://<your-host>:5000/auth/discord/callback` |
| `DISCORD_REDIRECT_URI_LOCAL` | For OAuth | `http://127.0.0.1:5000/auth/discord/callback` |
| `HCAPTCHA_SITE_KEY` / `HCAPTCHA_SECRET_KEY` | Optional | Skipped if blank |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | Optional | Enables password reset via email |
| `SESSION_COOKIE_SECURE` | Production | Set to `true` when running behind HTTPS |

---

## Development setup

**Backend**
```bash
cd app
pip install -r requirements.txt
python server.py
```

**Frontend** (separate terminal)
```bash
cd frontend
npm install
npm run dev   # Vite dev server on http://localhost:5173, proxies API to :5000
```

Build the frontend into Flask's static folder:
```bash
cd frontend
npm run build   # outputs to app/static/dist/
```

---

## Project structure

```
Discord-Forge/
├── app/                            # Flask backend
│   ├── app.py                      # All API routes, heartbeat, moderation, member sync
│   ├── bot_docker.py               # Docker SDK wrapper — spawns/stops bot containers
│   ├── server.py                   # Production entry point (gevent + SocketIO)
│   ├── pages/                      # Jinja2 HTML templates
│   ├── static/
│   │   ├── assets/                 # Static images
│   │   └── dist/                   # Built React frontend (npm run build output)
│   ├── deploy/
│   │   └── control.ps1             # Windows control panel
│   ├── .env.example                # Environment variable template
│   └── requirements.txt
├── frontend/                       # React + Vite source
│   ├── src/
│   │   ├── App.jsx                 # Main SPA shell + all page components
│   │   ├── api.js                  # Typed API client
│   │   ├── utils.js                # fmtDate timezone-aware formatter
│   │   ├── pages/                  # ActivityPage, AgentPage, SettingsPage, …
│   │   └── themes/
│   │       ├── library/            # 20+ theme definitions
│   │       └── *.jsx               # Animated canvas overlays
│   ├── public/
│   └── vite.config.js
├── discord-server-setup-template/  # Source for the discordforge-bot Docker image
│   ├── launcher.py                 # Bot runner: heartbeat, command polling, events
│   ├── requirements.txt
│   ├── cogs/
│   │   ├── Database_management/    # Casino / shared currency cog
│   │   └── moderation/             # Warn, kick, ban slash commands + SQLite storage
│   ├── Setup_server.py             # Full Discord server setup from config.json
│   ├── Update_server.py            # Diff-based server update
│   ├── templates/                  # JSON server templates
│   └── utils/
├── data/                           # Runtime user data (gitignored)
├── Dockerfile
└── docker-compose.yml
```

---

## Bot heartbeat

Running bots POST to `/api/local-bot/heartbeat` every 30 seconds:

```json
{
  "server_id": "...", "bot_id": "...", "status": "online",
  "ping_ms": 42, "uptime": "2h 15m",
  "messages_today": 137,
  "member_msg_counts": { "123456789": 12, "987654321": 5 },
  "cogs_loaded": 2,
  "cog_extensions": ["cogs.moderation.moderation", "cogs.Database_management.database_manager"]
}
```

Flask merges `member_msg_counts` into `members.json` so the Members page shows per-member message counts that survive bot restarts. The dashboard script tab shows a **loaded / failed** badge per cog based on `cog_extensions`.

Bots also poll `/api/local-bot/commands` each cycle to execute queued dashboard actions (warn, kick, ban, assign/remove role) and report results back via `/api/local-bot/command-result`.

---

## Moderation

**From Discord** (slash commands, immediate):
```
/warn @user reason  →  DMs user  →  stores in moderation.db  →  syncs warning count to dashboard
/kick @user reason  →  kicks in Discord  →  logs to dashboard
/ban @user reason   →  bans in Discord   →  logs to dashboard
/warnings @user     →  shows warning history (ephemeral)
```

**From the dashboard** (queued, runs on next heartbeat poll ≤30s):
```
⚠️ Warn / 🚪 Kick / 🚨 Ban  →  commands.json  →  bot executes  →  members.json updated
```

---

## Data persistence

All user data lives in `data/` and is gitignored. Back it up separately before updating or rebuilding.

---

## Disclaimer

DiscordForge is an independent project and is not affiliated with, endorsed by, or connected to Discord Inc. Discord and its logo are trademarks of Discord Inc.
