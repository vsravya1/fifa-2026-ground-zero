"""
setup_elastic.py
1. Creates the Elastic index with correct mapping
2. Ingests synthetic signals from data/synthetic_signals.json
3. Pulls live NewsAPI articles about FIFA 2026
4. Pulls live OpenWeatherMap alerts for all 5 host cities
Usage: python setup_elastic.py
"""

import os
import json
import requests
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()

# ── Elastic client ────────────────────────────────────────────────────────────
es = Elasticsearch(
    os.getenv("ELASTIC_URL"),
    api_key=os.getenv("ELASTIC_API_KEY")
)
INDEX = "fifa_incidents"

# ── Host city coords for weather ──────────────────────────────────────────────
HOST_CITIES = [
    {"name": "Dallas, TX",          "venue": "ATT Stadium Dallas",     "lat": 32.748, "lon": -97.093},
    {"name": "East Rutherford, NJ", "venue": "MetLife Stadium NJ",     "lat": 40.813, "lon": -74.074},
    {"name": "Inglewood, CA",       "venue": "SoFi Stadium LA",        "lat": 33.953, "lon": -118.339},
    {"name": "Santa Clara, CA",     "venue": "Levi's Stadium SF",      "lat": 37.403, "lon": -121.970},
    {"name": "Miami Gardens, FL",   "venue": "Hard Rock Stadium Miami","lat": 25.958, "lon": -80.239},
]

# ── 1. Create index mapping ───────────────────────────────────────────────────
def create_index():
    if es.indices.exists(index=INDEX):
        es.indices.delete(index=INDEX)
        print(f"Deleted existing index: {INDEX}")

    mapping = {
        "mappings": {
            "properties": {
                "id":            {"type": "keyword"},
                "text":          {"type": "text"},
                "venue":         {"type": "keyword"},
                "gate":          {"type": "keyword"},
                "type":          {"type": "keyword"},
                "source":        {"type": "keyword"},
                "severity":      {"type": "keyword"},
                "signal_count":  {"type": "integer"},
                "status":        {"type": "keyword"},
                "temperature_c": {"type": "float"},
                "weather_desc":  {"type": "text"},
                "timestamp":     {"type": "date"},
                "ingested_at":   {"type": "date"},
                "cluster_id":    {"type": "keyword"},
                "drafted_action":{"type": "text"},
                "routed_to":     {"type": "keyword"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "5s"
        }
    }
    es.indices.create(index=INDEX, body=mapping)
    print(f"✓ Created index: {INDEX}")

# ── 2. Ingest synthetic signals ───────────────────────────────────────────────
def ingest_synthetic():
    data_path = os.path.join(os.path.dirname(__file__), "../data/synthetic_signals.json")
    with open(data_path) as f:
        signals = json.load(f)

    now = datetime.now(timezone.utc).isoformat()
    for s in signals:
        s["ingested_at"] = now
        s["severity"] = "calm"
        s["signal_count"] = 1
        s["status"] = "open"
        es.index(index=INDEX, id=s["id"], document=s)

    print(f"✓ Ingested {len(signals)} synthetic signals")

# ── 3. Pull live NewsAPI ──────────────────────────────────────────────────────
def ingest_news():
    api_key = os.getenv("NEWS_API_KEY")
    if not api_key:
        print("⚠ NEWS_API_KEY not set, skipping")
        return

    url = "https://newsapi.org/v2/everything"
    params = {
        "q": "FIFA World Cup 2026 incident OR complaint OR delay OR crowd",
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": 20,
        "apiKey": api_key
    }
    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        print(f"⚠ NewsAPI error: {resp.status_code}")
        return

    articles = resp.json().get("articles", [])
    count = 0
    for i, a in enumerate(articles):
        if not a.get("title"):
            continue
        doc = {
            "id":          f"news_{i:04d}",
            "text":        f"{a['title']}. {a.get('description', '')}".strip(),
            "venue":       "General",
            "gate":        "General",
            "type":        "fan_complaint",
            "source":      "newsapi",
            "severity":    "calm",
            "signal_count": 1,
            "status":      "open",
            "timestamp":   a.get("publishedAt", datetime.now(timezone.utc).isoformat()),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        es.index(index=INDEX, id=doc["id"], document=doc)
        count += 1

    print(f"✓ Ingested {count} NewsAPI articles")

# ── 4. Pull live OpenWeatherMap ───────────────────────────────────────────────
def ingest_weather():
    api_key = os.getenv("OWM_API_KEY")
    if not api_key:
        print("⚠ OWM_API_KEY not set, skipping")
        return

    count = 0
    for city in HOST_CITIES:
        url = "https://api.openweathermap.org/data/2.5/weather"
        params = {
            "lat":   city["lat"],
            "lon":   city["lon"],
            "appid": api_key,
            "units": "metric"
        }
        resp = requests.get(url, params=params, timeout=10)
        if resp.status_code != 200:
            print(f"⚠ OWM error for {city['name']}: {resp.status_code}")
            continue

        data = resp.json()
        temp = data["main"]["temp"]
        weather_desc = data["weather"][0]["description"]
        feels_like = data["main"]["feels_like"]

        # Only create an incident if heat is dangerous or weather is severe
        weather_main = data["weather"][0]["main"].lower()
        is_alert = temp > 35 or any(w in weather_main for w in ["thunder", "storm", "rain", "snow"])

        doc = {
            "id":            f"weather_{city['name'].replace(', ', '_').replace(' ', '_').lower()}",
            "text":          f"Weather alert for {city['name']}: {weather_desc}, {temp:.1f}°C (feels like {feels_like:.1f}°C)",
            "venue":         city["venue"],
            "gate":          "General",
            "type":          "weather_event",
            "source":        "openweathermap",
            "severity":      "P1" if temp > 38 else ("P2" if is_alert else "calm"),
            "signal_count":  1,
            "status":        "open" if is_alert else "monitoring",
            "temperature_c": temp,
            "weather_desc":  weather_desc,
            "timestamp":     datetime.now(timezone.utc).isoformat(),
            "ingested_at":   datetime.now(timezone.utc).isoformat(),
        }
        es.index(index=INDEX, id=doc["id"], document=doc)
        count += 1
        alert_flag = "🔴" if is_alert else "✓"
        print(f"  {alert_flag} {city['name']}: {temp:.1f}°C — {weather_desc}")

    print(f"✓ Ingested weather for {count} host cities")

# ── MAIN ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n── Setting up Elastic ──")
    create_index()
    ingest_synthetic()
    ingest_news()
    ingest_weather()

    count = es.count(index=INDEX)["count"]
    print(f"\n── Done. Total documents in {INDEX}: {count} ──")
    print("Next: open Kibana → Discover → select fifa_incidents index to verify")
