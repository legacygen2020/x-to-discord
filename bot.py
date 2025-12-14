import os
import time
import requests

# ----------------------------
# SECRETS
# ----------------------------
X_BEARER = os.environ["X_BEARER_TOKEN"].strip()
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"].strip()
HEADERS = {"Authorization": f"Bearer {X_BEARER}"}

# ----------------------------
# TUNING (rate-limit safety)
# ----------------------------
MAX_RESULTS_PER_ACCOUNT = 3          # pull up to 3 newest tweets each run
MAX_POSTS_PER_ACCOUNT_PER_RUN = 1    # post at most 1 per account per run (safe)
SLEEP_BETWEEN_ACCOUNTS = 5           # seconds
SLEEP_AFTER_POST = 1.5              # seconds
BACKOFF_ON_429 = 12                  # seconds

# ----------------------------
# INPUT: accounts.txt (one handle per line, no @)
# ----------------------------
def load_accounts():
    with open("accounts.txt", "r", encoding="utf-8") as f:
        return [line.strip().lstrip("@") for line in f if line.strip()]

# ----------------------------
# X API helpers
# ----------------------------
def safe_get_json(url, params=None):
    """Return (status_code, json_or_none). Never raises."""
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=20)
        if r.status_code == 200:
            return 200, r.json()
        return r.status_code, None
    except Exception:
        return 0, None

def get_user_id(username):
    """Username -> user_id (skips on rate limit or error)."""
    url = f"https://api.x.com/2/users/by/username/{username}"
    code, data = safe_get_json(url)
    if code == 429:
        print(f"429 on user lookup @{username} — backing off then skipping")
        time.sleep(BACKOFF_ON_429)
        return None
    if code != 200 or not data or "data" not in data:
        print(f"User lookup failed @{username}: {code}")
        return None
    return data["data"]["id"]

def fetch_timeline(username, user_id, max_results=3):
    """Fetch recent tweets for user_id. Skips on 429."""
    url = f"https://api.x.com/2/users/{user_id}/tweets"
    params = {"max_results": max_results}

    code, data = safe_get_json(url, params=params)

    if code == 429:
        print(f"429 on timeline @{username} — backing off then skipping")
        time.sleep(BACKOFF_ON_429)
        return []
    if code != 200 or not data:
        print(f"Timeline failed @{username}: {code}")
        return []

    return data.get("data", []) or []

# ----------------------------
# Discord helper (clean embed)
# ----------------------------
def post_to_discord(username, tweet_id, text):
    tweet_url = f"https://x.com/{username}/status/{tweet_id}"

    payload = {
        "username": "Captain Hook",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "author": {"name": f"@{username}", "url": f"https://x.com/{username}"},
                "description": text[:3900],
                "url": tweet_url
            }
        ]
    }

    r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)
    print(f"Discord status: {r.status_code}")
    return r.status_code in (200, 204)

# ----------------------------
# MAIN
# ----------------------------
accounts = load_accounts()
print("Accounts:", accounts)

# simple in-run duplicate guard (prevents double-posting same tweet ID in one run)
posted_ids = set()

for acct in accounts:
    print(f"\nProcessing @{acct}")

    user_id = get_user_id(acct)
    if not user_id:
        time.sleep(SLEEP_BETWEEN_ACCOUNTS)
        continue

    tweets = fetch_timeline(acct, user_id, max_results=MAX_RESULTS_PER_ACCOUNT)
    if not tweets:
        time.sleep(SLEEP_BETWEEN_ACCOUNTS)
        continue

    # Sort oldest -> newest and post at most N tweets per run
    tweets_sorted = sorted(tweets, key=lambda t: int(t["id"]))[:MAX_POSTS_PER_ACCOUNT_PER_RUN]

    for t in tweets_sorted:
        tid = t["id"]
        if tid in posted_ids:
            continue

        ok = post_to_discord(acct, tid, t["text"])
        if ok:
            posted_ids.add(tid)
        time.sleep(SLEEP_AFTER_POST)

    time.sleep(SLEEP_BETWEEN_ACCOUNTS)

print("Run complete.")
