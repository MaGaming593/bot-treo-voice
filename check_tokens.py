import sys
import json
from curl_cffi import requests

sys.stdout.reconfigure(encoding="utf-8")

with open("tokens.txt", "r", encoding="utf-8") as f:
    tokens = [l.strip() for l in f if l.strip() and not l.startswith("#")]

print(f"Tong so token: {len(tokens)}")

session = requests.Session(impersonate="chrome120")

for i, token in enumerate(tokens, 1):
    try:
        # Kiem tra User Token
        res = session.get("https://discord.com/api/v9/users/@me", headers={"Authorization": token})
        if res.status_code == 200:
            data = res.json()
            is_bot = data.get("bot", False)
            print(f"[{i}] USER TOKEN SONG: {data.get('username')}#{data.get('discriminator', '0')} (ID: {data.get('id')}) | IsBot: {is_bot}")
            continue

        # Kiem tra Bot Token
        res_bot = session.get("https://discord.com/api/v9/users/@me", headers={"Authorization": f"Bot {token}"})
        if res_bot.status_code == 200:
            data = res_bot.json()
            print(f"[{i}] BOT TOKEN SONG: {data.get('username')}#{data.get('discriminator', '0')} (ID: {data.get('id')})")
            continue

        print(f"[{i}] TOKEN LOI (Code: {res.status_code}): {res.text[:80]}")
    except Exception as e:
        print(f"[{i}] Loi ngoai le: {e}")
