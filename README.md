# DiscordForge

A self-hosted web platform for designing, deploying, and managing Discord servers and bots — without writing code.

You run it on your own machine or server. Users register on your instance and manage their bots locally.

---

## Features

- **Server wizard** — step-by-step builder for channels, categories, roles, and permissions
- **Bot management** — add Discord bots, download a local runner package, track heartbeat and uptime
- **Collaborators** — invite friends to help manage servers with per-permission access
- **Script library** — browse and apply community cog scripts to your bots
- **Theme engine** — 20+ UI themes including animated overlays (all free)
- **Discord OAuth** — link your Discord account for avatar and identity
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
| Production | gevent WSGI · optional Docker |

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

## Docker (optional)

If you prefer containers instead of running Python directly:

```bash
cp app/.env.example app/.env
# edit app/.env

docker compose up -d --build
```

The `docker-compose.yml` mounts `./data` as a volume so user data persists across rebuilds.

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
│   ├── app.py                      # Main application
│   ├── server.py                   # Production entry point (gevent + SocketIO)
│   ├── bot_manager_direct.py       # Local bot runner bridge
│   ├── pages/                      # Jinja2 HTML templates
│   ├── static/
│   │   ├── assets/                 # Static images
│   │   └── dist/                   # Built React frontend (npm run build output)
│   ├── stress-tests/               # Browser-based load and functional test pages
│   ├── deploy/
│   │   └── control.ps1             # Windows control panel
│   ├── .env.example                # Environment variable template
│   └── requirements.txt
├── frontend/                       # React + Vite source
│   ├── src/
│   │   ├── App.jsx                 # Main SPA shell
│   │   ├── api.js                  # API client
│   │   ├── pages/                  # Page components (auth, settings, collaborators, …)
│   │   └── themes/
│   │       ├── library/            # Theme definitions (20+ themes)
│   │       └── *.jsx               # Animated canvas overlays
│   ├── public/                     # Static assets (favicon, icons)
│   └── vite.config.js
├── agent/                          # Agent for remote bot management
│   ├── agent.py
│   └── requirements.txt
├── discord-server-setup-template/  # Bot runner scripts deployed to user machines
│   ├── Setup_server.py
│   ├── Update_server.py
│   ├── launcher.py
│   ├── cogs/                       # Discord.py cog modules
│   ├── setup_cogs/
│   ├── templates/                  # JSON server templates
│   └── utils/
├── dev/                            # Internal dev files (gitignored from public repo)
├── data/                           # Runtime user data (gitignored)
├── Dockerfile
└── docker-compose.yml
```

---

## Data persistence

All user data lives in `data/` and is gitignored. Back it up separately before updating or rebuilding.

---

## Disclaimer

DiscordForge is an independent project and is not affiliated with, endorsed by, or connected to Discord Inc. Discord and its logo are trademarks of Discord Inc.
