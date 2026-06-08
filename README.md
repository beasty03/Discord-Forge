# DiscordForge

A self-hosted web platform for designing, deploying, and managing Discord servers and bots — without writing code.

You run it on your own machine or server. Users register on your instance and manage their bots locally.

---

## Features

- **Server wizard** — step-by-step builder for channels, categories, roles, and permissions
- **Bot management** — add Discord bots, download a local runner package, track heartbeat and uptime
- **Script library** — browse and apply community cog scripts to your bots
- **Theme engine** — 20+ UI themes including animated overlays
- **Discord OAuth** — link your Discord account for avatar and identity
- **Email verification & password reset** via SMTP
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
| Production | Docker (multi-stage) · gevent WSGI |

---

## Quick start (Docker)

**1. Clone the repo**
```bash
git clone https://github.com/<your-username>/discordforge.git
cd discordforge
```

**2. Create your `.env`**
```bash
cp app/.env.example app/.env
# edit app/.env and fill in your values
```

**3. Build and run**
```bash
docker compose up -d --build
```

App is available at `http://localhost:5000`.

---

## Environment variables

Copy `app/.env.example` to `app/.env` and fill in:

| Variable | Required | Notes |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | **Yes** | Fernet key — generate once, never change. `py -3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `DISCORD_CLIENT_ID` | For OAuth | From [Discord Developer Portal](https://discord.com/developers/applications) |
| `DISCORD_CLIENT_SECRET` | For OAuth | — |
| `DISCORD_REDIRECT_URI` | For OAuth | `http://<your-host>:5000/auth/discord/callback` |
| `HCAPTCHA_SITE_KEY` / `HCAPTCHA_SECRET_KEY` | Optional | Skipped if blank |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | Optional | Enables email verification and password reset |
| `SESSION_COOKIE_SECURE` | Production | Set to `true` when running behind HTTPS |

---

## Development setup

**Backend**
```bash
cd app
pip install -r requirements.txt
python server.py
```

**Frontend** (in a separate terminal)
```bash
cd frontend
npm install
npm run dev
```

Vite dev server runs on `http://localhost:5173` and proxies API calls to Flask on `5000`.

To build the frontend into Flask's static folder:
```bash
cd frontend
npm run build   # outputs to app/static/dist/
```

---

## Project structure

```
DiscordForge/
├── app/                        # Flask backend
│   ├── app.py                  # Main application
│   ├── server.py               # Production entry point (gevent + SocketIO)
│   ├── bot_manager_direct.py   # Local bot runner bridge
│   ├── pages/                  # Jinja2 HTML templates
│   ├── static/
│   │   └── dist/               # Built React frontend (generated)
│   ├── deploy/                 # Control scripts
│   └── requirements.txt
├── frontend/                   # React + Vite source
│   └── src/
│       ├── pages/              # Page components
│       └── themes/             # Theme definitions and canvas overlays
├── agent/                      # AI agent integration
├── discord-server-setup-template/  # Bot setup scripts
├── data/                       # Runtime data (gitignored)
│   ├── users.json
│   ├── servers_config.json
│   ├── users/
│   ├── uploads/
│   └── bots/
├── Dockerfile
└── docker-compose.yml
```

---

## Data persistence

All user data lives in `data/` and is mounted as a Docker volume. It is gitignored — back it up separately.

---

## Disclaimer

DiscordForge is an independent project and is not affiliated with, endorsed by, or connected to Discord Inc. Discord and its logo are trademarks of Discord Inc.
