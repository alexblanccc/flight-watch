import html, json, os, re, subprocess, sys, time, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
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

ORIGIN, DEST = "NHA", "NQZ"
ORIGIN_NAME, DEST_NAME = "Нячанг", "Астана"
FROM, TO = date(2026, 11, 10), date(2026, 12, 9)
CURRENCY = "kzt"
PAX = 1
ALERT_MAX = 100000
DIGEST_EVERY = 50 * 60
ALERT_REPEATS = 3
ALERT_GAP = 20


def months():
    y, m = FROM.year, FROM.month
    while (y, m) <= (TO.year, TO.month):
        yield f"{y}-{m:02d}"
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def fetch():
    items = []
    for month in months():
        q = urllib.parse.urlencode({
            "origin": ORIGIN, "destination": DEST, "departure_at": month,
            "one_way": "true", "sorting": "price", "limit": 1000,
            "currency": CURRENCY, "market": "kz",
        })
        req = urllib.request.Request(
            "https://api.travelpayouts.com/aviasales/v3/prices_for_dates?" + q,
            headers={"X-Access-Token": TOKEN},
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            items += json.load(r).get("data", [])
    return items


def in_window(item):
    d = date.fromisoformat(item["departure_at"][:10])
    return FROM <= d <= TO


AIRLINES = {
    "DV": "SCAT", "KC": "Air Astana", "VJ": "VietJet", "VN": "Vietnam Airlines",
    "CZ": "China Southern", "3U": "Sichuan Airlines", "FS": "FlyArystan",
    "HU": "Hainan Airlines", "CA": "Air China", "MU": "China Eastern",
    "TG": "Thai Airways", "SU": "Аэрофлот", "TK": "Turkish Airlines",
}
CITIES = {
    "NQZ": "Астана", "CXR": "Нячанг", "ALA": "Алматы", "HAN": "Ханой",
    "SGN": "Хошимин", "URC": "Урумчи", "TFU": "Чэнду", "BKK": "Бангкок",
    "DMK": "Бангкок", "PQC": "Фукуок", "DAD": "Дананг", "HKG": "Гонконг", "PKX": "Пекин", "PEK": "Пекин", "CAN": "Гуанчжоу",
    "KUL": "Куала-Лумпур", "SZX": "Шэньчжэнь", "XIY": "Сиань", "CTU": "Чэнду",
    "DXB": "Дубай", "IST": "Стамбул", "SIN": "Сингапур", "ICN": "Сеул",
    "TAS": "Ташкент", "SVO": "Москва", "DME": "Москва",
}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
ARRIVAL_TZ = timezone(timedelta(hours=5))


def stops(item):
    m = re.search(r"\d((?:[A-Z]{3}){2,})_", item.get("link", ""))
    if not m:
        return []
    codes = re.findall("[A-Z]{3}", m.group(1))
    return [CITIES.get(c, c) for c in codes[1:-1]]


def money(n):
    return f"{n:,}".replace(",", " ") + " ₸"


def hm(minutes):
    return f"{minutes // 60} ч {minutes % 60:02d} мин"


def kind(item):
    n = item.get("transfers", 0)
    if n == 0:
        return "Прямой рейс"
    where = ", ".join(stops(item))
    word = "пересадка" if n == 1 else "пересадки"
    return f"{n} {word}" + (f" ({where})" if where else "")


def card(item):
    dep = datetime.fromisoformat(item["departure_at"])
    arr = (dep + timedelta(minutes=item.get("duration", 0))).astimezone(ARRIVAL_TZ)
    code = item.get("airline", "?")
    airline = AIRLINES.get(code, code)
    link = item.get("link", "").replace(f"{DEST}1", f"{DEST}{PAX}", 1)
    day = f"{dep.day} {MONTHS[dep.month - 1]} {dep.year}, {WEEKDAYS[dep.weekday()]}"
    lines = [
        f"<b>{html.escape(day)}</b>",
        f"🛫 Вылет {dep:%H:%M} {ORIGIN_NAME} ({item.get('origin_airport', ORIGIN)})",
        f"🛬 Прилёт {arr:%H:%M}, {arr.day} {MONTHS[arr.month - 1]}, {DEST_NAME} ({item.get('destination_airport', DEST)})",
        f"⏱ В пути: {hm(item['duration'])}" if item.get("duration") else "",
        f"🔀 {html.escape(kind(item))}",
        f"✈️ {html.escape(airline)}",
        f"💰 <b>{money(item['price'])}</b> за билет" + (f", <b>{money(item['price'] * PAX)}</b> за {PAX}" if PAX > 1 else ""),
        f'<a href="https://www.aviasales.kz{html.escape(link)}">Открыть на Aviasales</a>',
    ]
    return "\n".join(l for l in lines if l)


TOP = 5
LOCAL_TZ = timezone(timedelta(hours=5))


def message(items):
    now = datetime.now(LOCAL_TZ)
    head = (f"✈️ <b>{ORIGIN_NAME} → {DEST_NAME}, {FROM.day} {MONTHS[FROM.month - 1]} - {TO.day} {MONTHS[TO.month - 1]} {TO.year}</b>\n"
            f"Самые дешёвые на {now:%H:%M}, {now.day} {MONTHS[now.month - 1]}. "
            "В одну сторону, цена за 1 пассажира" + (f" и за {PAX}." if PAX > 1 else "."))
    cards = [f"<b>{n}.</b> " + card(it) for n, it in enumerate(items[:TOP], 1)]
    foot = "Цену и наличие мест проверяйте на сайте."
    return "\n\n".join([head, *cards, foot])


def notify(text, repeats=1):
    if sys.platform == "darwin":
        mac_notify(text)
    chats = [c.strip() for c in TG_CHAT.split(",") if c.strip()]
    for n in range(repeats):
        if n:
            time.sleep(ALERT_GAP)
        for chat in chats:
            if not TG_TOKEN:
                return
            body = urllib.parse.urlencode({
                "chat_id": chat, "text": text, "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }).encode()
            try:
                urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", body, timeout=30)
            except Exception as e:
                print(f"Не отправилось в {chat}: {e}", file=sys.stderr)


def mac_notify(text):
    plain = re.sub("<[^>]+>", "", text).replace("\\", "").replace('"', "")
    subprocess.run(["osascript", "-e",
                    f'display notification "{plain[:180]}" with title "Билеты NHA-NQZ"'])


def alert_message(item):
    return (f"🚨 <b>Дёшево: до {money(ALERT_MAX)} за билет!</b>\n"
            f"{ORIGIN_NAME} → {DEST_NAME}\n\n{card(item)}\n\n"
            "Цену и наличие мест проверьте сразу.")


def key(item):
    return f'{item["departure_at"]}|{item.get("airline", "")}|{item["price"]}'


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def main():
    dry = "--dry" in sys.argv
    items = sorted(filter(in_window, fetch()), key=lambda i: i["price"])
    if not items:
        print("Нет билетов в выбранном окне")
        return
    state = load_state()
    changed = False

    direct = [i for i in items if i["price"] <= ALERT_MAX]
    seen = set(state.get("alerted", []))
    for it in direct:
        if key(it) not in seen:
            print("АЛЕРТ:", re.sub("<[^>]+>", "", alert_message(it)).replace("\n", " | "))
            if not dry:
                notify(alert_message(it), ALERT_REPEATS)
    current = sorted(key(i) for i in direct)
    if current != sorted(seen):
        state["alerted"] = current
        changed = True

    if time.time() - state.get("digest", 0) >= DIGEST_EVERY:
        text = message(items)
        print(re.sub("<[^>]+>", "", text))
        if not dry:
            notify(text)
            state["digest"] = int(time.time())
            changed = True
    else:
        print("Сводка уже отправлялась недавно, прямых до порога:", len(direct))

    if changed and not dry:
        STATE.write_text(json.dumps(state))


if __name__ == "__main__":
    sys.exit(main())
