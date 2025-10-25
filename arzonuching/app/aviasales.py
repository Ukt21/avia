
from __future__ import annotations
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any
import aiohttp

TP_TOKEN  = os.getenv("TP_TOKEN", "")
TP_MARKER = os.getenv("TP_MARKER", "")
SUB_ID    = os.getenv("SUB_ID", "")
CURRENCY  = os.getenv("DEFAULT_CURRENCY", "usd")
LOCALE    = os.getenv("DEFAULT_LOCALE", "ru")

import requests
from datetime import datetime

def ensure_iata(code: str) -> str:
    c = code.strip().upper()
    if len(c) != 3 or not c.isalpha():
        raise ValueError(f"IATA ожидалось из 3 букв, получил: {code}")
    return c

def tp_search_prices_for_date(origin: str, destination: str, date: str):
    o = ensure_iata(origin)
    d = ensure_iata(destination)

    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise ValueError("Дата должна быть в формате YYYY-MM-DD")

    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
    params = {
        "origin": o,
        "destination": d,
        "departure_at": date,
        "currency": CURRENCY,
        "locale": LOCALE,
        "limit": 5
    }
    headers = {"X-Access-Token": TP_TOKEN}

    r = requests.get(url, params=params, headers=headers, timeout=15)
    print("TP request:", r.url, "status:", r.status_code)
    print("TP response:", r.text[:1000])

    if r.status_code != 200:
        return []

    data = r.json().get("data", [])
    if not isinstance(data, list):
        return []
    return data[:5]

def tp_deeplink(origin: str, destination: str, date: str) -> str:
    o = ensure_iata(origin)
    d = ensure_iata(destination)
    base = "https://tp.media/r"
    qs = f"marker={TP_MARKER}&locale={LOCALE}&currency={CURRENCY}&origin={o}&destination={d}&depart_date={date}"
    if SUB_ID:
        qs += f"&sub_id={SUB_ID}"
    return f"{base}?{qs}"

TP_TOKEN = os.getenv("TRAVELPAYOUTS_TOKEN", "")
AFFILIATE_MARKER = os.getenv("AFFILIATE_MARKER", "YOUR_MARKER")

async def fetch_cheapest(session: aiohttp.ClientSession, origin: str, dest: str, dep_date: datetime, days_flex: int = 0, currency: str = "UZS") -> List[Dict[str,Any]]:
    results: List[Dict[str,Any]] = []
    headers = {"Accept": "application/json"}
    base_url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
    for shift in range(-days_flex, days_flex+1):
        d = dep_date + timedelta(days=shift)
        params = {
            "origin": origin,
            "destination": dest,
            "departure_at": d.strftime("%Y-%m-%d"),
            "currency": currency,
            "sorting": "price",
            "limit": 7,
            "token": TP_TOKEN,
        }
        async with session.get(base_url, params=params, headers=headers, timeout=20) as r:
            if r.status == 200:
                data = await r.json()
                for it in data.get("data", []):
                    dep = it.get("departure_at")
                    price = it.get("price")
                    transfers = it.get("transfers", 0)
                    flight = it.get("flight_number","")
                    # Ссылка на покупку (маркер внутри)
                    # Формат поиска может отличаться; этот вариант демонстрационный
                    date_ddmm = datetime.fromisoformat(dep.replace("Z","")).strftime("%d%m")
                    link = f"https://www.aviasales.com/search/{origin}{dest}{date_ddmm}?marker={AFFILIATE_MARKER}"
                    results.append({
                        "price": price,
                        "airline": it.get("airline",""),
                        "flight_number": flight,
                        "departure_at": dep,
                        "transfers": transfers,
                        "origin": origin,
                        "destination": dest,
                        "link": link,
                    })
    # Сортировка и уникализация
    seen = set(); filtered = []
    for x in sorted(results, key=lambda z: z["price"] or 9e12):
        key = (x["departure_at"], x["flight_number"])
        if key not in seen:
            seen.add(key); filtered.append(x)
    return filtered[:10]
