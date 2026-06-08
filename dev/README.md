# dev/

Dev-only tools and artifacts. Not part of the app — kept out of `app/` to avoid clutter.

| File | Purpose |
|---|---|
| `ratelimit_test.py` | Rate-limit breach tester — fires concurrent bursts at `/login` and `/register` to verify 429s; more thorough than the control panel's built-in test |
| `My_Server_template.json` | Ready-to-import server config for the test server (guild `1506746859018915870`); load via Setup → Import Config |

## Usage

```
# Rate-limit test (run from repo root or dev/)
python dev/ratelimit_test.py
python dev/ratelimit_test.py --url http://193.74.155.90:5000
python dev/ratelimit_test.py --login-only
```
