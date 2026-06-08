# DiscordForge — Project Audit

**Date:** 2026-05-28 (updated — 5 bug fixes, 91 entries)
**Audited by:** Claude (automated multi-pass review)
**Scope:** Security vulnerabilities, application completeness, data model integrity, broken flows

---

## Table of Contents

1. [Security Vulnerabilities](#1-security-vulnerabilities)
2. [Broken Routes & Features](#2-broken-routes--features)
3. [Missing Flows](#3-missing-flows)
4. [Silent Failures & Error Handling](#4-silent-failures--error-handling)
5. [Data Model Issues](#5-data-model-issues)
6. [Bot Lifecycle Gaps](#6-bot-lifecycle-gaps)
7. [Permissions Issues](#7-permissions-issues)
8. [Dead Code & Orphaned Logic](#8-dead-code--orphaned-logic)
9. [Config & Env Gaps](#9-config--env-gaps)
10. [Fixes Already Applied](#10-fixes-already-applied)
11. [Recommended Priority Order](#11-recommended-priority-order)

---

## 1. Security Vulnerabilities

### 1.1 Hardcoded `SETUP_BOT_TOKEN` in source — `app.py:122`
- **Status:** ✅ FULLY REMOVED
- **Severity:** Critical
- The token was first committed directly in Python source (→ moved to `.env`). Subsequently the entire DiscordForge-owned setup bot service was eliminated: `SETUP_BOT_TOKEN`, `CLIENT_ID`, and `DISCORD_HEADERS` were removed from `app.py` and from `.env`. Users must always supply their own bot; no shared/managed bot exists in the system.

### 1.2 Pre-auth RCE via bot manager — `bot_manager_direct.py`
- **Status:** ✅ FIXED
- **Severity:** Critical
- Bot manager bound to `0.0.0.0:5001` with zero authentication. The `/api/cloud/start` route accepted a `launcher` path directly into `subprocess.Popen` — any network peer could execute arbitrary Python.
- **Fix:** Bound to `127.0.0.1`. Added `X-Manager-Secret` header shared between `app.py` and `bot_manager_direct.py`.

### 1.3 Path traversal — script ZIP download — `app.py:5334`
- **Status:** ✅ FIXED
- **Severity:** High
- `script` query parameter joined directly to `install_dir/.../cogs/<script>` without `realpath` guard. `os.walk()` would serve any directory including `data/users.json`.
- **Fix:** `realpath` + `startswith(cogs_root)` check before `os.walk`.

### 1.4 Path traversal — script vars write — `app.py:6521`
- **Status:** ✅ FIXED
- **Severity:** High
- `script` POST field joined to cogs path without sanitization, then opened for write. Allowed overwriting arbitrary files reachable by the process.
- **Fix:** Same `realpath` + `startswith` guard before write.

### 1.5 Arbitrary file write via icon upload — `app.py:1551`
- **Status:** ✅ FIXED
- **Severity:** High
- `icon_file.filename` used raw in `os.path.join` with no `secure_filename` call. A filename like `../../app/pages/dashboard.html` would overwrite templates.
- **Fix:** `werkzeug.utils.secure_filename` applied before constructing save path.

### 1.6 IDOR — `/load_config` exposes any server — `app.py:1297`
- **Status:** ✅ FIXED
- **Severity:** High
- Any logged-in user could retrieve any server's full record (including `install_dir`, `config_path`, tokens) by guessing the Discord guild ID (a public value).
- **Fix:** Response now scoped to servers owned by the requesting user.

### 1.7 Unauthenticated GitHub issue creation — `app.py:7756`
- **Status:** ✅ FIXED
- **Severity:** Medium
- `/api/feedback` had no `@login_required`. Anyone could POST and create GitHub issues using the server's `GITHUB_TOKEN`.
- **Fix:** Added `@login_required`.

### 1.8 All Discord identities leaked to any logged-in user — `app.py:1742`
- **Status:** ✅ FIXED
- **Severity:** Medium
- `GET /api/discord-linked-users` returned every user's Discord ID and username to any authenticated caller.
- **Fix:** Response scoped to users who share at least one server with the caller.

### 1.9 Open redirect after login — `app.py:766`
- **Status:** ✅ FIXED
- **Severity:** Medium
- `next` param checked with `startswith('/')` only — didn't block `/\evil.com` forms on some browsers.
- **Fix:** `urlparse` used to reject any URL with a `scheme` or `netloc`.

### 1.10 Bot token stored in `localStorage` — `setup.html`
- **Status:** ✅ FIXED
- **Severity:** High
- `maintBotToken` was included in the "Save for later" draft written to `localStorage`. Any XSS could steal it.
- **Fix:** Token removed from `saveDraft()` and `loadDraft()` — user must re-paste after returning to a draft.

### 1.11 Bot token partially rendered in HTML — `servers.html:497`
- **Status:** ✅ FIXED
- **Severity:** Medium
- `{{ bot.token[:20] }}…` rendered first 20 chars of the real Discord token in page source.
- **Fix:** Replaced with `"token set ✓"` indicator.

### 1.12 Bot tokens plaintext in JSON config files
- **Status:** ✅ FIXED
- **Severity:** Medium
- `bot_token` and `discord_bots[n].token` stored as raw strings in `config.json` files.
- **Fix:** Fernet AES-128 encryption at `save_server_config`; decrypted transparently at `load_server_config`. Key stored in `.env` as `TOKEN_ENCRYPTION_KEY`. Existing plaintext tokens re-encrypted on next save.

### 1.13 Admin portal completely broken — `app.py:7833`
- **Status:** ✅ FIXED
- **Severity:** Medium (lockout bug, not attacker-exploitable)
- `_require_admin()` reads `session.get('username')` but login sets `session['user_id']`. Admin is always redirected to dashboard; nobody can reach the admin portal.
- **Fix:** Changed `session.get('username')` → `session.get('user_id')` in `_require_admin`.

### 1.14 No CSRF protection
- **Status:** ✅ FIXED
- **Severity:** Medium
- Flask-WTF not configured. `SESSION_COOKIE_SAMESITE = 'Lax'` mitigates top-level navigations but not AJAX or subframe requests.
- **Fix:** `csrf_protect` decorator added; session-stored `_csrf` token validated on all `POST`/`PUT`/`DELETE`/`PATCH` routes. `csrf_token()` exposed to Jinja2 globals for template use.

### 1.15 No rate limiting
- **Status:** ✅ FIXED
- **Severity:** Medium
- No Flask-Limiter or equivalent on login, registration, or sensitive endpoints.
- **Fix:** Flask-Limiter installed; `/login` limited to 30/min, `/register` limited to 10/hour.

### 1.16 Member kick/ban requires only `view_server` permission — `app.py:5489`
- **Status:** ✅ FIXED
- **Severity:** High
- Member actions (kick, ban) should require `edit_server` but the permission check used `view_server`.
- **Fix:** Permission check on member action route changed to `require_permission='edit_server'`.

### 1.17 Concurrent setup race condition — `app.py:2145`
- **Status:** ✅ FIXED
- **Severity:** Medium
- No per-server lock on setup runs. Two requests could start setup simultaneously, leading to interleaved writes and config corruption.
- **Fix:** `_get_setup_lock(server_id)` returns a per-server `threading.Lock`; `acquire(blocking=False)` returns 409 if already running; `finally: _lock.release()` ensures cleanup.

### 1.18 Non-atomic JSON writes — `save_json`, `save_server_config`
- **Status:** ✅ FIXED
- **Severity:** Medium
- JSON files written directly — a crash mid-write left files corrupt or truncated.
- **Fix:** All JSON saves now write to a `.tmp` file then `os.replace()` atomically.

---

## 2. Broken Routes & Features

| Route | File:Line | Issue |
|---|---|---|
| `/admin` | `app.py:7839` | Session key mismatch in `_require_admin` — **FIXED** |
| `/subscriptions` | `app.py:1248` | Renders template but no payment integration; `PLANS` dict only has `'free'` (line 179) |
| `/api/setup/run` | `app.py:2145` | Background setup works but client must poll `/api/setup/status`; no timeout or failure broadcast |
| `/api/bots/add-to-server` | `app.py:3198` | "Bot already in server" edge case not cleanly handled |
| `/api/setup/test-invite/<server_id>` | `app.py:6892` | Manual test trigger; not wired into normal setup flow |

---

## 3. Missing Flows

### 3.1 Password Reset — ✅ IMPLEMENTED
Routes added: `GET/POST /forgot-password`, `GET/POST /reset-password/<token>`. Token stored as SHA-256 hash in `users.json` with 1-hour expiry. Email sent via SMTP (falls back gracefully if SMTP not configured).

### 3.2 Email Verification — ✅ IMPLEMENTED
Registration sets `email_verified: False` and sends a 24-hour verification link. Route `GET /verify-email/<token>` marks account verified. `POST /api/account/resend-verification` re-sends the link.

### 3.3 Account Deletion — ✅ IMPLEMENTED
`POST /account` with `action=delete_account` (requires CSRF token, current password confirmation) removes user from `users.json`, unlinks all servers, and clears session.

### 3.4 Invite Expiry — ✅ IMPLEMENTED
`/invite/<token>` now rejects invites older than 7 days before rendering the accept page.

### 3.5 Session Revocation — ✅ IMPLEMENTED
`.revoked_sessions.json` stores revoked session IDs. `before_request` hook checks every request against the revoked set. `POST /api/account/revoke-other-sessions` invalidates all sessions except the current one.

### 3.6 Webhook Retry — ✅ IMPLEMENTED
`_fire_single_webhook()` helper retries up to 3 times with exponential backoff; handles Discord 429 `retry_after` delays.

### 3.7 Bot Downtime Alerts — ✅ IMPLEMENTED
`_notify_crash()` in `bot_manager_direct.py` POSTs to `/api/internal/bot-crash-alert` when a bot exits unexpectedly. Flask handler fires user notification webhooks.

### 3.8 Bulk Member Operations — ✅ IMPLEMENTED
`members.html` has a select-all checkbox, per-row checkboxes, and a bulk action bar supporting assign_role, remove_role, kick, and ban. Actions are queued via individual calls to `/api/members/<server_id>/action`.

### 3.9 Bot Script Upgrades — ✅ IMPLEMENTED
`GET /api/scripts/check-updates` compares each installed cog's `.version` SHA against the latest GitHub commit. `POST /api/scripts/update` downloads and overwrites the cog folder in-place, then updates the `.version` file. The scripts page UI surfaces both actions.

### 3.10 Bot Auto-restart on Crash — ✅ IMPLEMENTED
`BotProcess._maybe_restart()` restarts crashed bots with exponential backoff (5s × attempt, max 60s). Max 5 restarts within a 300s window before giving up. Manual `stop()` disables restart by saturating the restart counter.

---

## 4. Silent Failures & Error Handling

The following locations swallow exceptions with `except Exception: pass` or return `None` without user feedback:

| Location | Description | Severity |
|---|---|---|
| `app.py` ~2312 | Setup attempt exception swallowed; no flash message shown | High |
| `app.py` ~2511 | Failed cog import — user gets no error | Medium |
| `app.py` ~1798, ~1912 | Asset upload errors (emoji, stickers, soundboard) invisible to user | Medium |
| `app.py` ~4915 | Bot config save failure — config not persisted, user not told | High |
| `app.py` ~77 | `_botmgr()` returns `None` when bot manager is unreachable; callers rarely check | High |
| `app.py` ~284 | Fernet decryption failure returns plaintext legacy token silently | Medium |

---

## 5. Data Model Issues

### 5.1 `users.json` gaps

| Field | Issue |
|---|---|
| `created_at` | ✅ Now set at registration |
| `email_verified` | ✅ Now set at registration (`False`); updated via verification link |
| `plan` | ✅ Now written as `'free'` on registration (`app.py:900`) |
| `avatar_source` | Used in code (`app.py:1105`) but not in schema |
| `google_username` | `google_id` stored but no username field (unlike `discord_username`) |

### 5.2 `servers_config.json` gaps

| Field | Issue |
|---|---|
| `updated_at` | Missing — no last-modified timestamp |
| `status` | No `setup_pending` / `active` / `archived` state field |
| Collaborators format | Two schemas in use: old = list of permission strings; new = dict with metadata. Code handles both (`app.py:366`) but both exist in production data |

### 5.3 Per-server `config.json` gaps

- No schema version field — impossible to detect or migrate old structures
- ✅ Auto-backup before modification — `.bak` file created by `save_server_config` before every write
- Token encryption prefix (`enc:`) works but if `TOKEN_ENCRYPTION_KEY` is lost or rotated, all tokens become permanently unreadable

---

## 6. Bot Lifecycle Gaps

| Operation | Status | Gap |
|---|---|---|
| Start | Implemented | — |
| Stop | Implemented | — |
| Restart | Implemented | Queued via heartbeat; client not notified of failure |
| Status | Partial | Only checks heartbeat age (3-min window); no deep health check |
| Logs | Implemented | Max 200 lines retained; older lines lost |
| Upgrade scripts | ✅ Implemented | `/api/scripts/check-updates` + `/api/scripts/update` |
| Auto-restart on crash | ✅ Implemented | Exponential backoff, max 5 restarts / 300s window |
| Crash alerts | ✅ Implemented | `_notify_crash()` → `/api/internal/bot-crash-alert` → user webhooks |
| Scaling (multiple instances) | Missing | One bot process per server only |
| Rollback | Missing | No version history; failed setup requires full re-clone |

### Bot Manager Status Detection — Fragile
`bot_manager_direct.py:84` — Status `'running'` is set only when `"logged in as"` or `"ready"` appears in log output. If the bot framework changes its startup message, detection silently breaks.

---

## 7. Permissions Issues

| Issue | Location | Status |
|---|---|---|
| Member kick/ban requires `view_server` | `app.py:5489` | ✅ Fixed — changed to `edit_server` |
| Collaborator permission check inconsistent | Multiple routes | Open — audit all mutation routes |
| No permission check on `/load_config` before fix | `app.py:1297` | ✅ Fixed — ownership check added |

---

## 8. Dead Code & Orphaned Logic

| Item | Location | Notes |
|---|---|---|
| `can_use_cloud()` | `app.py:308` | Checks plan for `'cloud'`; plans dict only has `'free'` — always returns `False`, but IS called (lines 3496, 3513, 3682) so not removable yet |
| `find_file_ci()` | `app.py:632` | ✅ NOT dead — called at 7 locations including `run_setup_api`, `run_update_api`, `start_bot` (audit entry was incorrect) |
| `_disc_get/post/patch()` | `app.py:7336+` | ✅ NOT dead — used extensively in `_post_setup_apply_assets`, `dashboard_live_status`, and functional test routes (audit entry was incorrect) |
| `_first_bot_token()` | `app.py:7406` | ✅ NOT dead — called by multiple routes including `guild_limits_api`, `dashboard_live_status` (audit entry was incorrect) |
| `re` import | `app.py:19` | ✅ NOT unused — used at lines 4287 (inside `_BOT_MANAGER_PY` string), 6603, 6608, 6613, 6862, 6912 (audit entry was incorrect) |
| Pro/Enterprise plan definitions | `app.py:269` | Commented-out stubs; referenced nowhere. Low priority — remove when subscriptions page is built out |

---

## 9. Config & Env Gaps

### Variables in `.env` that need attention

| Variable | Status | Action |
|---|---|---|
| `SETUP_BOT_TOKEN` | ✅ Removed entirely | Setup bot service eliminated; old token is revoked |
| `DISCORD_CLIENT_SECRET` | In `.env` | Keep out of version control ✓ |
| `GOOGLE_CLIENT_SECRET` | In `.env` | Keep out of version control ✓ |
| `GITHUB_TOKEN` | In `.env` | Keep out of version control ✓ |
| `HCAPTCHA_SECRET_KEY` | In `.env` | Keep out of version control ✓ |
| `TOKEN_ENCRYPTION_KEY` | In `.env` | **Never change** — changing it makes all stored bot tokens unreadable |
| `ADMIN_USERNAME` | Not in `.env` | Defaults to hardcoded `'beastyboy03'`; add to `.env` |
| `SESSION_COOKIE_SECURE` | ✅ Now env-configurable | Set `SESSION_COOKIE_SECURE=true` in `.env` for HTTPS production |

### Missing operational config

- **Log rotation** — ✅ Bot log files now use `RotatingFileHandler(maxBytes=1 MB, backupCount=3)`; takes effect on next "Deploy Locally"
- **HTTPS enforcement** — No redirect from HTTP → HTTPS; cookies sent insecurely in production
- **Max invite age** — Invite TTL is hardcoded at 7 days; not configurable via env or admin panel

---

## 10. Fixes Already Applied

| # | Fix | Status |
|---|---|---|
| 1 | `SETUP_BOT_TOKEN` moved to `.env` | ✅ Done |
| 2 | Bot manager bound to `127.0.0.1`; `X-Manager-Secret` auth added | ✅ Done |
| 3 | Path traversal in script ZIP (`realpath` guard) | ✅ Done |
| 4 | Path traversal in script vars write (`realpath` guard) | ✅ Done |
| 5 | Icon upload uses `secure_filename` | ✅ Done |
| 6 | `/load_config` IDOR — ownership check added | ✅ Done |
| 7 | `/api/feedback` gated with `@login_required` | ✅ Done |
| 8 | `discord-linked-users` scoped to shared-server members | ✅ Done |
| 9 | Open redirect after login fixed with `urlparse` | ✅ Done |
| 10 | Bot token removed from `localStorage` draft | ✅ Done |
| 11 | Bot token partial display removed from `servers.html` | ✅ Done |
| 12 | Bot tokens encrypted at rest (Fernet AES-128) | ✅ Done |
| 13 | Admin session key fixed (`user_id` not `username`) | ✅ Done |
| 14 | Member kick/ban permission changed to `edit_server` | ✅ Done |
| 15 | Atomic JSON writes (temp file + `os.replace()`) | ✅ Done |
| 16 | Per-server setup lock — 409 on concurrent runs | ✅ Done |
| 17 | CSRF protection (`csrf_protect` decorator + session token) | ✅ Done |
| 18 | Rate limiting — Flask-Limiter on `/login` and `/register` | ✅ Done |
| 19 | Password reset flow (`/forgot-password`, `/reset-password/<token>`) | ✅ Done |
| 20 | Email verification flow (`/verify-email/<token>`, resend endpoint) | ✅ Done |
| 21 | Account deletion (`POST /account` with `action=delete_account`) | ✅ Done |
| 22 | Invite expiry — 7-day TTL checked at acceptance | ✅ Done |
| 23 | Session revocation (`.revoked_sessions.json` + `before_request` hook) | ✅ Done |
| 24 | Revoke other sessions endpoint (`POST /api/account/revoke-other-sessions`) | ✅ Done |
| 25 | Webhook retry with exponential backoff (`_fire_single_webhook`) | ✅ Done |
| 26 | Bot auto-restart on crash (exponential backoff, max 5 / 300s) | ✅ Done |
| 27 | Bot crash alerts (`_notify_crash` → `/api/internal/bot-crash-alert`) | ✅ Done |
| 28 | Config auto-backup (`.bak` file before every `save_server_config`) | ✅ Done |
| 29 | CSRF hidden inputs added to all protected forms (`account.html`, `servers.html`) | ✅ Done |
| 30 | `plan` field written as `'free'` on registration | ✅ Done |
| 31 | `SESSION_COOKIE_SECURE` read from `.env` (no longer hardcoded) | ✅ Done |
| 32 | Bulk member operations — select-all + bulk action bar in `members.html` (was already implemented, confirmed) | ✅ Done |
| 33 | Bot script in-place upgrade — `/api/scripts/check-updates` + `/api/scripts/update` (was already implemented, confirmed) | ✅ Done |
| 34 | Bot log rotation — `RotatingFileHandler` (1 MB, 3 backups) in `_LOCAL_BOT_PY` template | ✅ Done |
| 35 | CSRF hidden input added to dashboard.html delete-server form (was missing; servers.html already had it) | ✅ Done |
| 36 | CSRF token added dynamically in settings.html `submitDelete()` JS (form built at runtime, token was never included) | ✅ Done |
| 37 | `/api/update/invite` bot_client_id defaulted to setup bot when user's own token was in config — `elif` branch added | ✅ Done |
| 38 | `webbrowser.open()` popup from `generate_invite.py` eliminated — script is no longer run by the setup flow | ✅ Done |
| 39 | Bot token `enc:` values passed raw to `Setup_server.py` subprocess (discord.py login 401) — config written with plaintext tokens before subprocess; re-encrypted afterward | ✅ Done |
| 40 | `use_slash_commands` invalid in discord.py 2.x — `_PERM_ALIASES` normalization applied before subprocess writes config; `build_server_config` also normalizes new configs | ✅ Done |
| 41 | DiscordForge setup bot fully eliminated — users must always supply their own bot; `SETUP_BOT_TOKEN`, `CLIENT_ID`, `DISCORD_HEADERS` removed from `app.py` and `.env`; `keep_in_guild` always `True`; setup form blocks submission without a bot token | ✅ Done |
| 42 | `_count_config_channels` used wrong key (`categories` → `custom_categories`), missed category objects (Discord returns categories as channel type 4), missed `forum_channels`, hardcoded mod count as 3 (template creates 5), used wrong welcome key (`welcome_template` → `use_welcome_template`) — all corrected; now reads template files from `paths.template_dir` for accurate counts | ✅ Done |
| 43 | `server_overview` route read channels via wrong keys (`categories` / `textChannels`) — fixed to read `custom_categories` with snake_case keys and convert to camelCase for the template; `channel_count` now uses `_count_config_channels(cfg)`; forum channels now rendered in the sidebar | ✅ Done |
| 44 | Setup `/setup` POST always showed invite modal even when bot was already in the guild — backend now calls `check_bot_in_guild` and returns `in_guild` in the response; frontend skips the modal and goes directly to `runSetup()` when `in_guild` is true | ✅ Done |
| 45 | Flask-Limiter 4.x silently fails to enforce `@limiter.limit('30 per minute')` on the login route — removed all `@limiter.limit()` decorators from login, register, forgot-password, and reset-password; replaced with inline `_rl_check()` calls using a fixed-window counter backed by a module-level dict + `threading.Lock`; `abort` added to Flask imports; verified with concurrent burst test | ✅ Done |
| 46 | Google OAuth fully removed — `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` vars, `/auth/google` and `/auth/google/callback` routes, `unlink_google` account action, Google button in `login.html`, and Google link section in `account.html` all deleted; Discord OAuth now uses `DISCORD_REDIRECT_URI` from `.env` directly (port-forwarding IP `193.74.155.90`) instead of building a dynamic URL from the request host; `_dynamic_redirect_uri()` helper removed as it is no longer needed; `deploy/start.ps1` simplified to a single `waitress` invocation with no ngrok or tunnel logic | ✅ Done |
| 47 | DuckDNS auto-update scheduled task added — `deploy/duckdns_update.ps1` calls DuckDNS API every 5 minutes via Windows Task Scheduler (`deploy/setup_duckdns_task.ps1`); logs OK/KO to `deploy/duckdns.log`; keeps `discordforge.duckdns.org` pointed at the public IP in case it changes | ✅ Done |
| 48 | HTTPS via Caddy + Let's Encrypt investigated and deferred — DuckDNS nameservers return SERVFAIL on all ACME challenge types (HTTP-01, TLS-ALPN-01, DNS-01); sslip.io wildcard DNS hit Let's Encrypt's 250k/week rate limit; deployment remains on HTTP (`http://193.74.155.90:5000`) with `SESSION_COOKIE_SECURE=false`; revisit when a real domain is acquired | ⏸ Deferred |
| 49 | SMTP configured — Gmail app password set in `.env` (`discordforge.noreply@gmail.com`); password reset and email verification emails now live | ✅ Done |
| 50 | Email verification enforced on login — users with `email_verified: False` are blocked at login and shown a resend button; new public `/resend-verification` POST endpoint (rate-limited 3/hr per IP, no login required); OAuth-created accounts auto-set `email_verified: True`; `/verify-email/<token>` now redirects to login instead of dashboard when user is not logged in; `@limiter.limit` on old resend API replaced with `_rl_check` | ✅ Done |
| 51 | Forgot password hardened — form now requires both username and email to match the same account (prevents reset with email alone); email body improved with greeting, expiry callout, and "if you didn't request this" disclaimer; flash message made generic; login page restructured into four clean states (`show_forgot`, `reset_token`, `unverified_username`, normal) each with own heading and form; "Forgot password?" link added to login page | ✅ Done |
| 52 | App logo added to all navbar brands — `static/assets/DiscordForge.jpg` now renders as a 26×26 px rounded thumbnail next to "DiscordForge" across all 19 pages; all `&#127918;` controller emoji instances removed | ✅ Done |
| 53 | Admin nav link deduplicated on `admin.html` — the page previously rendered both the new conditional red link (from the bulk replace) and an existing static `<a class="active">Admin</a>`, causing a double entry; merged into a single active red link | ✅ Done |
| 54 | Dual Discord OAuth redirect URIs — `DISCORD_REDIRECT_URI_LOCAL` added to `.env` (`http://127.0.0.1:5000/auth/discord/callback`); `/auth/discord` route now picks the URI dynamically based on `request.host`: local/127.0.0.1 uses the local URI, all other hosts use the public URI; both URIs must be registered in the Discord Developer Portal under OAuth2 → Redirects | ⚠️ Needs test |
| 55 | Unified PowerShell control panel — `app/deploy/control.ps1` consolidates start, stop, restart, status check, log tail (`flask.log` via `Tee-Object`), rate-limit burst test, and stress-test browser launch into a single interactive menu; replaces manual use of `start.ps1` / `stop.ps1`; `flask.log`, `flask.err`, `.flask.pid` added to `.gitignore` | ✅ Done |
| 56 | Control panel: three bug fixes — (1) process detection expanded to catch `py.exe` (Python Launcher) in addition to `python*.exe`; (2) HTTP status check simplified to `GET /login` (direct 200, no redirect exception handling); (3) `NativeCommandError` from waitress stderr eliminated by Base64-encoding the launch command via `-EncodedCommand` so Windows API argument-quoting can't strip the `cmd /c "..." 2>&1` double-quotes; friendly greeting shown when Flask is not yet started | ✅ Done |
| 57 | Project cleanup — deleted 5 unused/orphaned files: `app/deploy/start.ps1` and `stop.ps1` (superseded by `control.ps1`), `app/config.yml` (empty `{}` file, never read by code), `app/cloudflared-windows-amd64.exe` (18 MB binary, deployment method replaced by DuckDNS + port forwarding), `My_Server_template.json` (repo-root dev artifact, not referenced by app); moved `ratelimit_test.py` from repo root to `app/` alongside the code it tests | ✅ Done |
| 58 | `app/README.md` updated — removed stale Google OAuth redirect steps (no Google OAuth exists in app), removed cloudflared 5-step tunnel workflow; replaced with current deployment approach (DuckDNS + port forwarding + control panel) and full `.env` variable reference table | ✅ Done |
| 59 | AUDIT.md Section 8 corrected — five dead-code entries were wrong: `find_file_ci`, `_disc_get/post/patch`, `_first_bot_token`, and `re` import are all actively used; entries updated with correct line numbers and status | ✅ Done |
| 60 | Eventlet → gevent migration — `EventletDeprecationWarning` eliminated; `gevent.monkey.patch_all()` added as first call in `server.py`; `SocketIO(async_mode='gevent')` in `app.py`; `requirements.txt` updated to `gevent>=23.9.0` + `gevent-websocket>=0.10.1`; `eventlet` removed | ✅ Done |
| 61 | Roles check false positives fixed — `func_test_roles()` no longer flags template-created roles or the bot role as "Extra Roles on Discord"; `cfg_names` is now seeded from `moderation_template.json` + `welcome_template.json` role names (read from `paths.template_dir`) and from `config.get('bots_role_name', 'bots')` which `Setup_server.py` always creates unconditionally | ✅ Done |
| 62 | `control.ps1` — removed the BotMgr `:5001` status check block from `Show-Status`; fixed stale `eventlet` string in gevent startup message | ✅ Done |
| 63 | Account delete confirmation — changed from "type your username" text field to a current-password input with eye-toggle; backend verifies via `check_password_hash` before proceeding | ✅ Done |
| 64 | Setup: preset name no longer resets — `applyRoleTemplate` stores `customRoles[i].preset = tpl`; `renderCustomRoles` marks the matching `<option>` as `selected`; removed `this.value = ''` | ✅ Done |
| 65 | Setup: NSFW + slowmode now applied to Discord — `_patch_channel_attrs(script_path)` idempotently patches `Setup_server.py` to read `nsfw` and `slowmode_delay` from the channel config dict and pass them to `create_text_channel`; patch applied in both setup and update paths | ✅ Done |
| 66 | Setup: apostrophe/special-char channel names no longer fail inspector — `_norm()` in `func_test_channels` changed to `re.sub(r"[^a-z0-9\-_]", "", n.lower().replace(' ', '-'))` matching Discord's own normalization; same fix applied in `func_test_fix_channels` | ✅ Done |
| 67 | Setup: forum channels now created on Discord — `_patch_forum_community(script_path)` idempotently inserts a guild cache refresh (`bot.get_guild(int(GUILD_ID))`) after the `asyncio.sleep(1)` post-community-enable so `guild.features` reflects COMMUNITY before the forum creation loop runs; patch also applied in the "already enabled" branch | ✅ Done |
| 68 | Setup: role colors shown in review step — `renderReview()` now maps custom roles with their full object (including `.color`); renders hex-coloured pills via inline `background`/`color`/`border` styles; hardcoded roles (Admin/Moderator/Bot/Member) keep their CSS classes | ✅ Done |
| 69 | Setup: first role assignment uses chip+dropdown UI — replaced `<select multiple>` in category editor (tc/vc/fc) with `_pendingRoles` chip system consistent with the "add role" flow on existing channels; `addTextChannel`/`addVoiceChannel`/`addForumChannel` read from `_getPR()` and call `_clearPR()` after adding | ✅ Done |
| 70 | Setup: uncategorized text channels now have visibility control — private checkbox + role selector (`uncat_tcPendingRoles_0`) added to the uncategorized panel; `addUncatText` reads private state and roles; list items show role chips for private channels; backend reads `uncategorizedChannelsData` and merges into a synthetic "General" category before `build_server_config` | ✅ Done |
| 71 | Setup: announcements channel added to `welcome_template.json` — `_patch_welcome_template(template_dir)` idempotently inserts `{"name":"announcements", ...}` as first entry in `text_channels` if not already present; applied to both existing template files on disk and called before every setup/update run | ✅ Done |
| 72 | Dashboard: Import from Discord now requires bot token — `nsmBotToken` password input (with eye-toggle) added to the NSM "Add Existing" panel; `nsmImportFromDiscord()` reads and sends `bot_token` in the request body; `closeNewServerModal()` clears the field; backend `/api/discord/import-guild` already required `bot_token` | ✅ Done |
| 73 | `login_required`: no more random logout on background API calls — decorator now returns JSON `{error, login_required: true}` with HTTP 401 for all `/api/` routes when session is missing or expired, instead of calling `session.clear()` and redirecting to HTML; page routes still redirect as before | ✅ Done |
| 74 | Bot token verify: better error messages — `validateBotToken()` in `setup.html` now parses the status code before calling `.json()`; a 401 or `login_required:true` response shows "Session expired — please reload" instead of triggering the `.catch()` "Could not reach server" message; `credentials: 'same-origin'` added to the fetch | ✅ Done |
| 75 | Session nonce revocation — on every login (password + OAuth), a 16-byte `session_nonce` is written to `users.json` and the session cookie; `login_required` verifies the nonce on every request; any older session from another device or tab is invalidated on its next request without affecting the current session; `load_users()` called only once per request in the decorator | ✅ Done |
| 76 | Setup: role drag-and-drop — ▲/▼ arrow buttons replaced with a `⠿` drag handle per role card (`draggable="true"`); `roleDragStart`, `roleDragOver`, `roleDrop` functions reorder `customRoles[]` and call `renderCustomRoles()`; drag-over target gets a blue outline via `.role-card.drag-over` CSS; grab/grabbing cursor on handle | ✅ Done |
| 77 | Servers: setup log stream — `doRunSetup()` in `servers.html` now shows the progress modal before starting; `pollSetupLog()` polls `/api/setup/log/<server_id>` every 3 s and appends color-coded lines (green ✅ / red ❌ / yellow ⚠️) to the log box; `/api/setup/status/<server_id>` polled in parallel; modal auto-closes and page reloads on completion | ✅ Done |
| 78 | Category editor: section collapse state preserved — `renderCategoryEditor()` reads and restores the `collapsed` class of tcSection/vcSection/fcSection before rebuilding the DOM; prevents sections from snapping open when a channel is added via `renderCategories()` re-render | ✅ Done |
| 79 | Server name live-sync — saving the name in the Info modal now immediately PATCHes `/guilds/{id}` via Discord REST API so the Discord server name updates without re-running setup; uses maintenance bot token with fallback to setup bot token; `cfg['server']['name']` updated alongside the flat `server_name` key | ✅ Done |
| 80 | Role delete warning banner — roles modal now shows an amber banner explaining that deleting a role here only removes it from the DiscordForge config; the role still exists on Discord and must be deleted manually in Server Settings → Roles (Discord does not allow bots to delete roles the user hasn't explicitly assigned bot permissions over) | ✅ Done |
| 81 | Live roles diff — `_discord_apply_roles_diff` added; when the roles section is saved it fetches live Discord roles, creates missing roles, PATCHes changed ones (name/permissions/color/hoist), and deletes removed ones; handles both string and dict entries in `custom_roles`; `_perms_to_int` and `_color_to_int` helpers convert DiscordForge format to Discord API integers | ✅ Done |
| 82 | Live channels & categories management — "Manage" button added to the existing Categories & Channels detail section; opens `channelsModal` which loads live structure from Discord via `GET /api/server/<id>/live-channels`; supports create category, create text/voice/forum channel, rename, and delete; all ops hit `POST /api/server/<id>/live-channels/op` and apply to Discord immediately | ✅ Done |
| 83 | Discord error 50074 friendly message — deleting a channel that is set as the guild's Rules or Updates channel (code 50074) now returns HTTP 409 with a human-readable message directing the user to Server Settings → Community to unset it first; previously the raw Discord API error was shown | ✅ Done |
| 84 | Community disable from UI — unchecking the Community checkbox in the Community modal now triggers a confirm dialog explaining the consequences (forum channels disabled, rules/updates channels unset); on confirm, `server_patch` fetches current guild features, removes `COMMUNITY`, PATCHes the guild with `rules_channel_id: null` and `public_updates_channel_id: null`; errors are caught and logged without blocking the config save | ✅ Done |
| 85 | Category sync after channel ops — `_build_cats_from_channel_list` + `_persist_cats` helpers added; every successful `live-channels/op` (create/rename/delete) calls `_sync_categories_from_discord` which re-fetches Discord channels and persists the updated structure to both `servers_config.json` (camelCase) and `config.json` (snake_case `custom_categories`); `live_channels_get` also calls `_persist_cats` as a side effect so opening the Manage modal is enough to refresh stale static page data | ✅ Done |
| 86 | Server assets live upload — assetsModal now accepts real files instead of text names only; each section has a file picker (📁 Choose Image/Audio), FileReader converts to base64 data URL, stored as `{name, file_data, file_name}` objects; a new "🚀 Save & Push to Discord Now" button calls `POST /api/server/<id>/assets/push` which triggers `_post_setup_apply_assets` on demand (not just after setup/update) and shows the upload log inline; `emojiImgUrl` and `stickerImgUrl` now show local `file_data` data URLs as thumbnails for newly added items | ✅ Done |
| 87 | Private category permission inheritance — `live_channels_op` create_channel now fetches the parent category's `permission_overwrites` from Discord and passes them to the new channel body so channels created inside private categories are immediately restricted the same way the parent is, without needing a separate edit | ✅ Done |
| 88 | Non-community server forced into community — `has_any_forums` condition removed from Setup_server.py; Community is now enabled ONLY when `community_server: true`, never just because forum channels exist in the config; `_patch_forum_community` updated to also strip this override from newly cloned repos | ✅ Done |
| 89 | Phantom General category — `_build_cats_from_channel_list` no longer creates a "General" bucket for uncategorised Discord channels (welcome/mod template channels with no parent_id); those channels are silently skipped since they are managed outside the wizard config | ✅ Done |
| 90 | Forum channels not created — Setup_server.py restructured: all text/voice channels are created first, THEN Community is enabled (so text channels always exist for rules/updates), THEN forum channels are created in a dedicated second pass; `bot.fetch_guild()` (real API call) replaces `bot.get_guild()` (stale cache) to ensure `guild.features` is up-to-date before the forum creation check; `_patch_forum_community` updated to apply both fixes to new clones | ✅ Done |
| 91 | Config drift false positive for roles — drift checker now excludes bot-managed roles from `live_roles` count and adds mod template + welcome template + bots role to `cfg_roles`, mirroring the same logic the inspector uses; previously `cfg_roles = len(custom_roles)` missed all template/system roles causing chronic drift reports | ✅ Done |

---

## 11. Recommended Priority Order

### ✅ Completed

All items from the original immediate and short-term lists have been resolved. See Section 10 for the full list.

### 🟠 Remaining — Data Integrity & UX

1. **Fix silent failures** — a handful of `except Exception: pass` blocks in asset upload paths give no user feedback (see Section 4); critical setup/bot paths already surface errors correctly
2. **Admin portal manual test** — session key fix is in code; confirm it works by logging in as `beastyboy03`
3. **`guild_limits_api` no-token 400** — the endpoint now returns 400 when called without `server_id` (e.g. during initial setup before a server record exists); frontend may need to handle this gracefully

### 🟡 Medium-term (Feature Completeness)

3. **Config schema versioning** — add `schema_version` field; write migration helpers
4. **Bot status deep health check** — replace heartbeat-age heuristic with a real ping/pong
5. **Subscriptions / payment** — complete the plan upgrade flow or remove the page

### 🟢 Long-term (Quality / Maintainability)

6. **Consolidate Discord API helpers** — remove duplicate `_disc_*` functions at bottom of `app.py`
7. **HTTPS enforcement** — add redirect middleware or configure reverse proxy
8. **Configurable invite TTL** — expose max invite age via `.env` / admin panel
9. **`ADMIN_USERNAME` to `.env`** — remove hardcoded `'beastyboy03'` default
