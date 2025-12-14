import os
import json
import time
import requests

X_BEARER = os.environ["X_BEARER_TOKEN"].strip()
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"].strip()

HEADERS = {"Authorization": f"Bearer {X_BEARER}"}
STATE_FILE = "state.json"

# --- Load / Save state (persists via GitHub Actions cache) ---
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"users": {}}  # users[username] = {"id": "...", "last_tweet_id": "..."}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

state = load_state()

# --- Helpers ---
def get_user_id(username: str) -> str:
    # cache user IDs so we don't burn rate limits every run
    cached = state["users"].get(username, {}).get("id")
    if cached:
        return cached

    r = requests.get(
        f"https://api.x.com/2/users/by/username/{username}",
        headers=HEADERS,
        timeout=20
    )
    if r.status_code == 429:
        # backoff once
        time.sleep(10)
        r = requests.get(f"https://api.x.com/2/users/by/username/{username}", headers=HEADERS, timeout=20)

    r.raise_for_status()
    uid = r.json()["data"]["id"]
    state["users"].setdefault(username, {})["id"] = uid
    return uid

def fetch_new_tweets(username: str, user_id: str, since_id: str | None):
    params = {"max_results": 5}
    if since_id:
        params["since_id"] = since_id  # only fetch tweets newer than last posted

    r = requests.get(
        f"https://api.x.com/2/users/{user_id}/tweets",
        headers=HEADERS,
        params=params,
        timeout=20
    )

    if r.status_code == 429:
        # backoff once; if still 429, skip this account for this run
        time.sleep(12)
        r = requests.get(
            f"https://api.x.com/2/users/{user_id}/tweets",
            headers=HEADERS,
            params=params,
            timeout=20
        )
        if r.status_code == 429:
            print(f"Rate limited on @{username} — skipping this run.")
            return []

    r.raise_for_status()
    return r.json().get("data", []) or []

def post_to_discord(username: str, tweet_id: str, text: str):
    tweet_url = f"https://x.com/{username}/status/{tweet_id}"

    payload = {
        # Clean formatting: one embed, no duplicated plaintext
        "username": "Captain Hook",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "author": {"name": f"@{username}", "url": f"https://x.com/{username}"},
                "description": text[:3900],  # Discord embed description limit safety
                "url": tweet_url
            }
        ]
    }

    d = requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)
    # Discord webhooks typically return 204 on success
    if d.status_code not in (200, 204):
        raise RuntimeError(f"Discord webhook failed: {d.status_code} {d.text[:300]}")

# --- Main ---
accounts = [a.strip().lstrip("@") for a in open("accounts.txt", "r", encoding="utf-8") if a.strip()]
print("Accounts:", accounts)

for acct in accounts:
    try:
        user_id = get_user_id(acct)
        last_id = state["users"].get(acct, {}).get("last_tweet_id")

        tweets = fetch_new_tweets(acct, user_id, last_id)

        if not tweets:
            # nothing new (duplicate protection working)
            continue

        # Oldest -> newest so Discord reads clean
        tweets_sorted = sorted(tweets, key=lambda t: int(t["id"]))

        # Optional: cap posts per run per account (keeps rate limits safe)
        for t in tweets_sorted[:2]:
            post_to_discord(acct, t["id"], t["text"])
            # small delay to reduce Discord/X burstiness
            time.sleep(1.5)

        # Update last posted tweet id to the newest one we saw
        newest_id = tweets_sorted[-1]["id"]
        state["users"].setdefault(acct, {})["last_tweet_id"] = newest_id

        # Rate-limit protection between accounts
        time.sleep(3)

    except Exception as e:
        print(f"Error on @{acct}: {e}")
        # keep going so one account doesn't kill the whole run
        time.sleep(3)
        continue

save_state(state)
print("State saved.")
