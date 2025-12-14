import os
import requests

X_BEARER = os.environ["X_BEARER_TOKEN"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

HEADERS = {"Authorization": f"Bearer {X_BEARER}"}

accounts = [a.strip().lstrip("@") for a in open("accounts.txt") if a.strip()]
print("Accounts:", accounts)

def get_user_id(username):
    r = requests.get(
        f"https://api.x.com/2/users/by/username/{username}",
        headers=HEADERS,
        timeout=20
    )
    print("User lookup:", r.status_code)
    r.raise_for_status()
    return r.json()["data"]["id"]

for acct in accounts:
    print(f"Processing @{acct}")
    user_id = get_user_id(acct)

    r = requests.get(
        f"https://api.x.com/2/users/{user_id}/tweets",
        headers=HEADERS,
        params={"max_results": 5},
        timeout=20
    )
    print("Timeline status:", r.status_code)
    r.raise_for_status()

    tweets = r.json().get("data", [])
    if not tweets:
        print("No tweets found")
        continue

    t = tweets[0]
    msg = f"🛰️ **@{acct}**\n{t['text']}\nhttps://x.com/{acct}/status/{t['id']}"

    d = requests.post(DISCORD_WEBHOOK, json={"content": msg[:2000]}, timeout=20)
    print("Discord status:", d.status_code)
