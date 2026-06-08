# DiscordForge — Flask App

## Starting the app locally

```
python app.py
```

Or use the control panel:

```
.\deploy\control.ps1
```

App runs at `http://localhost:5000`.

---

## Deployment (current)

- **Public URL:** `http://193.74.155.90:5000` via Proximus port forwarding (port 5000 → app)
- **Dynamic DNS:** `discordforge.duckdns.org` — IP updated every 5 min by Windows Task Scheduler task (`deploy/duckdns_update.ps1`)
- **HTTPS:** deferred — DuckDNS nameservers return SERVFAIL on ACME challenges; revisit when a real domain is acquired
- **WSGI server:** waitress (must be run from this `app/` directory)

### Control panel

```
.\deploy\control.ps1
```

Options: start / stop / restart / status / logs / rate-limit test / open stress tests.

---

## Discord OAuth

Set both redirect URIs in the [Discord Developer Portal](https://discord.com/developers/applications):

```
http://193.74.155.90:5000/auth/discord/callback     (public)
http://127.0.0.1:5000/auth/discord/callback          (local dev)
```

The app picks the right one automatically based on the incoming host.

---

## Environment variables (`.env`)

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | Optional | Auto-generated to `.secret_key` if missing |
| `TOKEN_ENCRYPTION_KEY` | **Required** | Fernet key — **never change** or all stored bot tokens break |
| `DISCORD_CLIENT_ID` | Required for OAuth | — |
| `DISCORD_CLIENT_SECRET` | Required for OAuth | — |
| `SMTP_USER` / `SMTP_PASS` | Optional | Gmail app password; enables email verification + password reset |
| `HCAPTCHA_SITE_KEY` / `HCAPTCHA_SECRET_KEY` | Optional | Skipped if not set |
| `ADMIN_USERNAME` | Optional | Defaults to `beastyboy03` |
| `GITHUB_TOKEN` | Optional | Increases GitHub API rate limit for cog browser |
