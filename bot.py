import os
import requests

X_BEARER = os.environ["X_BEARER_TOKEN"]
DISCORD_WEBHOOK = os.environ["DISCORD_WEBHOOK_URL"]

accounts = open("accounts.txt").read().splitlines()

for acct in accounts:
    url = "https://api.x.com/2/tweets/search/recent"
    params = {
        "query": f"from:{acct} -is:retweet -is:reply",
        "max_results": 1
    }
    r = requests.get(
        url,
        headers={"Authorization": f"Bearer {X_BEARER}"},
        params=params
    )
    data = r.json().get("data", [])
    if not data:
        continue

    t = data[0]
    msg = f"🛰️ **@{acct}**\n{t['text']}\nhttps://x.com/{acct}/status/{t['id']}"
    requests.post(DISCORD_WEBHOOK, json={"content": msg[:2000]})
