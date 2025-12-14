import os
import time
import json
import base64
import requests

X_BEARER = os.environ["X_BEARER_TOKEN"].strip()
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"].strip()

HEADERS = {"Authorization": f"Bearer {X_BEARER}"}

SLEEP_BETWEEN_ACCOUNTS = 5
MAX_RESULTS = 3

accounts = [a.strip().lstrip("@") for a in open("accounts.txt") if a.strip()]
print("Accounts:", accounts)

def safe_get(url, params=None):
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    if r.status_code == 429:
        print("429 hit — backing off and skipping")
        return None
    if r.status_code != 200:
        print(f"Non-200 response: {r.status_code}")
        return None
    return r.json()

def post_to_discord(username, tweet):
    payload = {
        "username": "Captain Hook",
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "author": {"name": f"@{username}", "url": f"https://x.com/{username}"},
                "description": tweet["text"][:3900],
                "url": f"https://x.com/{username}/status/{tweet['id']}"
            }
        ]
    }
    d = requests.post(DISCORD_WEBHOOK, json=payload, timeout=20)
    print(f"Discord status: {d.status_code}")

for acct in accounts:
    print(f"\nProcessing @{acct}")

    user = safe_get(f"https://api.x.com/2/users/by/username/{acct}")
    if not user:
        continue

    user_id = user["data"]["id"]

    timeline = safe_get(
        f"https://api.x.com/2/users/{user_id}/tweets",
        params={"max_results": MAX_RESULTS}
    )
    if not timeline:
        continue

    tweets = timeline.get("data", [])
    if not tweets:
        print("No tweets")
        continue

    # Post only the most recent tweet
    post_to_discord(acct, tweets[0])

    time.sleep(SLEEP_BETWEEN_ACCOUNTS)

print("Run complete.")
