import json, os, subprocess, sys, urllib.parse, urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).parent
STATE = HERE / "state.json"
ENV = HERE / ".env"
if ENV.exists():
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

TOKEN = os.environ.get("TRAVELPAYOUTS_TOKEN") or (HERE / "token.txt").read_text().strip()
TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT_ID", "")

ORIGIN, DEST = "NQZ", "NHA"
FROM, TO = date(2027, 1, 5), date(2027, 1, 20)
CURRENCY = "kzt"
PAX = 2


def fetch():
    q = urllib.parse.urlencode({
        "origin": ORIGIN, "destination": DEST, "departure_at": "2027-01",
        "one_way": "true", "sorting": "price", "limit": 1000,
        "currency": CURRENCY, "market": "kz",
    })
    req = urllib.request.Request(
        "https://api.travelpayouts.com/aviasales/v3/prices_for_dates?" + q,
        headers={"X-Access-Token": TOKEN},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("data", [])


def in_window(item):
    d = date.fromisoformat(item["departure_at"][:10])
    return FROM <= d <= TO


def fmt(item):
    link = item.get("link", "").replace("NHA1", f"NHA{PAX}", 1)
    return (f'{item["departure_at"][:10]}  {item["price"] * PAX:,} {CURRENCY.upper()} за {PAX}  '
            f'{item.get("airline", "?")}  пересадок: {item.get("transfers", "?")}  '
            f'https://www.aviasales.kz{link}')


def notify(text):
    if sys.platform == "darwin":
        mac_notify(text)
    if TG_TOKEN and TG_CHAT:
        body = urllib.parse.urlencode({"chat_id": TG_CHAT, "text": text}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", body, timeout=30)


def mac_notify(text):
    short = text.split("  https://")[0].replace("\\", "").replace('"', "")
    subprocess.run(["osascript", "-e",
                    f'display notification "{short}" with title "Билеты NQZ-NHA"'])


def main():
    items = sorted(filter(in_window, fetch()), key=lambda i: i["price"])
    if not items:
        print("Нет билетов в окне 5-20 января")
        return
    for it in items[:10]:
        print(fmt(it))
    best = items[0]
    prev = json.loads(STATE.read_text()) if STATE.exists() else {}
    if "price" not in prev or best["price"] < prev["price"]:
        notify("Дешевле: " + fmt(best))
        STATE.write_text(json.dumps({"price": best["price"], "date": best["departure_at"][:10]}))


if __name__ == "__main__":
    sys.exit(main())
