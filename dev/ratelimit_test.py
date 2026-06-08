"""
DiscordForge — Rate-limit breach tester
Hammers /login and /register to verify the rate limiter kicks in.

Limits:
  /login    → 30 per minute  (expect 429 on request 31+)
  /register → 10 per hour    (expect 429 on request 11+)

Login requests are sent concurrently so they all land in the same
60-second window regardless of server response time.

Usage:
  python ratelimit_test.py              # both endpoints, localhost:5000
  python ratelimit_test.py --url http://localhost:5000
  python ratelimit_test.py --login-only
  python ratelimit_test.py --register-only
"""

import argparse
import sys
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL  = 'http://localhost:5000'
GREEN     = '\033[92m'
RED       = '\033[91m'
YELLOW    = '\033[93m'
CYAN      = '\033[96m'
RESET     = '\033[0m'
BOLD      = '\033[1m'


def bar(label, current, total, width=30):
    filled = int(width * current / max(total, 1))
    b = '█' * filled + '░' * (width - filled)
    return f'[{b}] {current}/{total}'


def attack_login(base, attempts=40):
    """Send bogus login POSTs concurrently — all land in the same window."""
    url = base + '/login'
    print(f'\n{BOLD}{CYAN}━━ /login  (limit: 30/min, burst mode) ━━{RESET}')
    print(f'   Firing {attempts} concurrent requests with bad credentials…\n')

    def _post(i):
        try:
            r = requests.post(url, data={
                'username': f'test_user_{i}',
                'password': 'wrongpassword',
            }, allow_redirects=False, timeout=10)
            return i, r.status_code, None
        except requests.ConnectionError:
            return i, None, 'connection refused'
        except requests.Timeout:
            return i, None, 'timeout'

    results = [None] * attempts
    with ThreadPoolExecutor(max_workers=attempts) as pool:
        futures = {pool.submit(_post, i): i for i in range(1, attempts + 1)}
        for future in as_completed(futures):
            idx, code, err = future.result()
            results[idx - 1] = (code, err)

    passed = failed = limited = errors = 0
    first_429_at = None

    for i, (code, err) in enumerate(results, 1):
        if err:
            errors += 1
            symbol = f'{RED}ERR{RESET}'
            print(f'  #{i:>3}  {symbol}  ({err})')
            if err == 'connection refused':
                break
            continue

        if code == 429:
            if first_429_at is None:
                first_429_at = i
            limited += 1
            symbol = f'{RED}429{RESET}'
        elif code in (200, 302):
            passed += 1
            symbol = f'{GREEN}{code}{RESET}'
        else:
            failed += 1
            symbol = f'{YELLOW}{code}{RESET}'

        print(f'  #{i:>3}  {symbol}  {bar("", i, attempts)}')

    print()
    if first_429_at:
        print(f'  {GREEN}✓ Rate limit triggered (429s received: {limited}){RESET}')
        if limited >= attempts - 30:
            print(f'  {GREEN}✓ Correct number of requests blocked{RESET}')
        else:
            print(f'  {YELLOW}⚠ Fewer blocks than expected{RESET}')
    else:
        print(f'  {RED}✗ No 429 received in {attempts} requests — rate limit may not be working!{RESET}')

    print(f'\n  Allowed: {passed}  |  Limited (429): {limited}  |  Other: {failed}  |  Errors: {errors}')
    return first_429_at is not None


def attack_register(base, attempts=15):
    """Send bogus registration POSTs — should 429 after 10."""
    url = base + '/register'
    print(f'\n{BOLD}{CYAN}━━ /register  (limit: 10/hr) ━━{RESET}')
    print(f'   Sending {attempts} requests with dummy accounts…\n')

    passed = failed = limited = errors = 0
    first_429_at = None

    for i in range(1, attempts + 1):
        try:
            r = requests.post(url, data={
                'username':         f'testaccount_{i}_{int(time.time())}',
                'password':         'Passw0rd!',
                'confirm_password': 'Passw0rd!',
                'email':            f'test{i}@example.com',
            }, allow_redirects=False, timeout=5)

            code = r.status_code

            if code == 429:
                if first_429_at is None:
                    first_429_at = i
                limited += 1
                symbol = f'{RED}429{RESET}'
            elif code in (200, 302):
                passed += 1
                symbol = f'{GREEN}{code}{RESET}'
            else:
                failed += 1
                symbol = f'{YELLOW}{code}{RESET}'

            print(f'  #{i:>3}  {symbol}  {bar("", i, attempts)}')

        except requests.ConnectionError:
            errors += 1
            print(f'  #{i:>3}  {RED}ERR{RESET}  (connection refused — is the server running?)')
            break
        except requests.Timeout:
            errors += 1
            print(f'  #{i:>3}  {YELLOW}TMO{RESET}  (timeout)')

    print()
    if first_429_at:
        print(f'  {GREEN}✓ Rate limit triggered at request #{first_429_at}{RESET}')
        if first_429_at <= 11:
            print(f'  {GREEN}✓ Within expected threshold (≤11){RESET}')
        else:
            print(f'  {YELLOW}⚠ Later than expected (got {first_429_at}, want ≤11){RESET}')
    else:
        print(f'  {RED}✗ No 429 received in {attempts} requests — rate limit may not be working!{RESET}')

    print(f'\n  Allowed: {passed}  |  Limited (429): {limited}  |  Other: {failed}  |  Errors: {errors}')
    return first_429_at is not None


def main():
    parser = argparse.ArgumentParser(description='DiscordForge rate-limit tester')
    parser.add_argument('--url',           default=BASE_URL, help='Base URL (default: http://localhost:5000)')
    parser.add_argument('--login-only',    action='store_true')
    parser.add_argument('--register-only', action='store_true')
    parser.add_argument('--login-attempts',    type=int, default=40,  help='Requests to send to /login (default 40)')
    parser.add_argument('--register-attempts', type=int, default=15,  help='Requests to send to /register (default 15)')
    args = parser.parse_args()

    print(f'\n{BOLD}DiscordForge — Rate-Limit Breach Tester{RESET}')
    print(f'Target: {args.url}')
    print('─' * 50)

    results = []

    if not args.register_only:
        results.append(('login',    attack_login(args.url,    args.login_attempts)))

    if not args.login_only:
        results.append(('register', attack_register(args.url, args.register_attempts)))

    print(f'\n{BOLD}{"─" * 50}')
    print('Summary')
    print('─' * 50)
    all_ok = True
    for name, ok in results:
        status = f'{GREEN}PASS{RESET}' if ok else f'{RED}FAIL{RESET}'
        print(f'  {name:<12} {status}')
        if not ok:
            all_ok = False

    print()
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
