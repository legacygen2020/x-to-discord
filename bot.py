import os
import time
import json
import base64
import requests

# ----------------------------
# REQUIRED SECRETS / SETTINGS
# ----------------------------
X_BEARER = os.environ["X_BEARER_TOKEN"].strip()
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"].strip()

# For saving duplicate-protection state back into the repo (one-file solution)
# Create a GitHub token and save as GH_TOKEN secret.
GH_TOKEN = os.environ.get("GH_TOKEN", "").strip()

# Your repo info (edit if you rename repo)
GITHUB_OWNER = "legacygen2020"
GITHUB_REPO = "x-to-discord"
STATE_PATH = "state.json"     # stored in repo root

# Rate-limit safety
SLEEP_BETWEEN_ACCOUNTS = 3
SLEEP_AFTER_POST = 1.5
BACKOFF_ON_429 = 12
MAX_POSTS_PER_ACCOUNT_PER_RUN = 2
MAX_RESULTS_PER_CALL = 5

# ----------------------------
# HELPERS
# ----------------------------
X_HEADERS = {"Authorization": f"Bearer {X_BEARER}"}

def gh_headers():
    if not GH_TOKEN:
        return None
    return {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github+json",
    }

def gh_get_file(path: str):
    """Read a file from the repo via GitHub API. Returns (content_str, sha) or (None, None)."""
    h = gh_headers()
    if not h:
        return None, None

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    r = requests.get(url, headers=h, timeout=20)
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    j = r.json()
    content_b64 = j["content"]
    sha = j["sha"]
    content = base64.b64decode(content_b64).decode("utf-8")
    return content, sha

def gh_put_file(path: str, content_str: str, sha: str | None):
    """Write/update a file in the repo via GitHub API."""
    h = gh_headers()
    if not h:
        return False

    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"
    payload = {
        "message": "Update state for duplicate protection",
        "content": base64.b64encode(content_str.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=h, json=payload, timeout=20)
    r.raise_for_status()
    return True

def load_accounts():
    with open("accounts.txt", "r", encoding="utf-8") as f:
        return [line.strip().lstrip("@") for line in f if line.strip()]

def load_state():
    """
    State structure:
    {
      "users": {
        "elonmusk": {"id":"...", "last_tweet_id":"..."},
        ...
      }
    }
    """
    # Prefer repo-backed state (cross-run duplicate protection)
    content, sha = gh_get_file(STATE_PATH)
    if content:
        try:
            return json.loads(content), sha
        except:
            pass

    # fallback: empty state
    return {"users": {}}, sha

def save_state(state, sha):
    content_str = json.dumps(state, indent=2)
    ok = gh_put_file(STATE_PATH, content_str, sha)
    if ok:
        print("State saved to repo.")
    else:
        print("State NOT saved (missing GH_TOKEN). Duplicate protection will be per-run only.")

def get_user_id(username, state):
    cached = state["users"].get(username, {}).get("id")
    if cached:
        return cached

    r = requests.get(
        f"https://api.x.com/2/users/by/username/{username}",
        headers=X_HEADERS,
        timeout=20
    )
    if r.status_code == 429:
        time.sleep(BACKOFF_ON_429)
        r = requests.get(f"https://api.x.com/2/users/by/username/{username}", headers=X_HEADERS, timeout=20)

    r.raise_for_status()
    uid = r.json()["data"]["id"]
    state["users"].setdefault(username, {})["id"] = uid
    return uid

def fetch_new_tweets(username, user_id, since_id):
    params = {"max_results": MAX_RESULTS_PER_CALL}
    if since_id:
        params["since_id"] = since_id

    r = requests.get(
        f"https://api.x.com/2/users/{user_id}/tweets",
        headers=X_HEADERS,
        params=params,
        timeout=20
    )

    if r.status_code == 429:
        print(f"429 for @{username} timeline — backing off...")
        time.sleep(BACKOFF_ON_429)
        r = requests.get(
            f"https://api.x.com/2/users/{user_id}/tweets",
            headers=X_HEADERS,
            params=params,
            timeout=20
        )
        if r.status_code == 429:
            print(f"Still 429 for @{username} — skipping this run.")
            return []

    r.raise_for_status()
    return r.json().get("data", []) or []

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

    d = requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)
    if d.status_code not in (200, 204):
        raise RuntimeError(f"Discord webhook failed: {d.status_code} {d.text[:200]}")
    return d.status_code

# ----------------------------
# MAIN
# ----------------------------
accounts = load_accounts()
print("Accounts:", accounts)

state, state_sha = load_state()

for acct in accounts:
    try:
        print(f"\nProcessing @{acct}")

        user_id = get_user_id(acct, state)
        last_id = state["users"].get(acct, {}).get("last_tweet_id")

        tweets = fetch_new_tweets(acct, user_id, last_id)
        if not tweets:
            print(f"No new tweets for @{acct}")
            time.sleep(SLEEP_BETWEEN_ACCOUNTS)
            continue

        # oldest -> newest, then limit to keep rate limits safe
        tweets_sorted = sorted(tweets, key=lambda t: int(t["id"]))[:MAX_POSTS_PER_ACCOUNT_PER_RUN]

        for t in tweets_sorted:
            status = post_to_discord(acct, t["id"], t["text"])
            print(f"Posted @{acct} tweet {t['id']} (Discord {status})")
            state["users"].setdefault(acct, {})["last_tweet_id"] = t["id"]
            time.sleep(SLEEP_AFTER_POST)

        time.sleep(SLEEP_BETWEEN_ACCOUNTS)

    except Exception as e:
        print(f"Error on @{acct}: {e}")
        time.sleep(SLEEP_BETWEEN_ACCOUNTS)
        continue

# Save state back to repo (cross-run duplicate protection)
save_state(state, state_sha)
print("Done.")
