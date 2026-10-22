import html, json, os, re, subprocess, sys, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
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
FROM, TO = date(2027, 1, 1), date(2027, 1, 30)
CURRENCY = "kzt"
PAX = 2


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
    "DMK": "Бангкок", "PKX": "Пекин", "PEK": "Пекин", "CAN": "Гуанчжоу",
    "KUL": "Куала-Лумпур", "SZX": "Шэньчжэнь", "XIY": "Сиань", "CTU": "Чэнду",
    "DXB": "Дубай", "IST": "Стамбул", "SIN": "Сингапур", "ICN": "Сеул",
    "TAS": "Ташкент", "SVO": "Москва", "DME": "Москва",
}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]
WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
ARRIVAL_TZ = timezone(timedelta(hours=7))


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
    link = item.get("link", "").replace("NHA1", f"NHA{PAX}", 1)
    day = f"{dep.day} {MONTHS[dep.month - 1]} {dep.year}, {WEEKDAYS[dep.weekday()]}"
    lines = [
        f"<b>{html.escape(day)}</b>",
        f"🛫 Вылет {dep:%H:%M} Астана ({item.get('origin_airport', 'NQZ')})",
        f"🛬 Прилёт {arr:%H:%M}, {arr.day} {MONTHS[arr.month - 1]}, Нячанг ({item.get('destination_airport', 'CXR')})",
        f"⏱ В пути: {hm(item['duration'])}" if item.get("duration") else "",
        f"🔀 {html.escape(kind(item))}",
        f"✈️ {html.escape(airline)}",
        f"💰 <b>{money(item['price'])}</b> за билет, <b>{money(item['price'] * PAX)}</b> за {PAX}",
        f'<a href="https://www.aviasales.kz{html.escape(link)}">Открыть на Aviasales</a>',
    ]
    return "\n".join(l for l in lines if l)


TOP = 5
LOCAL_TZ = timezone(timedelta(hours=5))


def message(items):
    now = datetime.now(LOCAL_TZ)
    head = (f"✈️ <b>Астана → Нячанг, {FROM.day}-{TO.day} {MONTHS[TO.month - 1]} {TO.year}</b>\n"
            f"Самые дешёвые на {now:%H:%M}, {now.day} {MONTHS[now.month - 1]}. "
            f"В одну сторону, цена за 1 пассажира и за {PAX}.")
    cards = [f"<b>{n}.</b> " + card(it) for n, it in enumerate(items[:TOP], 1)]
    foot = f"Наличие {PAX} мест проверяйте на сайте."
    return "\n\n".join([head, *cards, foot])


def notify(text):
    if sys.platform == "darwin":
        mac_notify(text)
    if TG_TOKEN and TG_CHAT:
        body = urllib.parse.urlencode({
            "chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", body, timeout=30)


def mac_notify(text):
    plain = re.sub("<[^>]+>", "", text).replace("\\", "").replace('"', "")
    subprocess.run(["osascript", "-e",
                    f'display notification "{plain[:180]}" with title "Билеты NQZ-NHA"'])


def main():
    items = sorted(filter(in_window, fetch()), key=lambda i: i["price"])
    if not items:
        print("Нет билетов в выбранном окне")
        return
    text = message(items)
    print(re.sub("<[^>]+>", "", text))
    if "--dry" not in sys.argv:
        notify(text)


if __name__ == "__main__":
    sys.exit(main())
