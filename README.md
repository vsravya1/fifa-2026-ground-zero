# FIFA 2026 Ground Zero — Real-Time Incident Intelligence Agent

> A human-in-the-loop AI agent that monitors, clusters, and routes real-time incidents across FIFA 2026 World Cup venues — built with Gemini, Elastic, MongoDB, and Arize.

---

## What it does

During a World Cup match, thousands of signals flood in simultaneously — fan complaints, crowd surges, ticketing failures, weather alerts, volunteer gaps. This agent:

1. **Ingests** signals from live APIs (NewsAPI, OpenWeatherMap) and a synthetic social feed
2. **Clusters** related signals by venue, gate, time window, and keyword — turning 14 fan posts into 1 incident
3. **Escalates** automatically: green → amber (P2) → red (P1) based on signal velocity
4. **Routes** each incident to the right human responder with a pre-drafted action plan
5. **Logs** every decision to Arize for agent observability and accuracy tracking

Humans stay in control — the agent handles the noise, the human makes the call.

---

## Architecture

```
Data Sources          Agent (Gemini)         Partners
─────────────         ──────────────         ────────
NewsAPI          →
OpenWeatherMap   →    Classify             → Elastic   (search + Kibana dashboard)
Synthetic feed   →    Cluster              → MongoDB   (state + audit log)
Volunteer DB     →    Route + Draft        → Arize     (agent observability)
                           ↓
                    Human Approval (Streamlit)
```

---

## Tech stack

| Layer | Tool |
|---|---|
| Agent | Gemini via Google Cloud Agent Builder |
| Search & alerting | Elasticsearch + Kibana |
| State & records | MongoDB Atlas |
| Observability | Arize |
| Approval UI | Streamlit |
| Live data | NewsAPI + OpenWeatherMap |

---

## Project structure

```
fifa-2026-ground-zero/
├── data/
│   └── synthetic_signals.json     # 33 pre-built fan posts + news snippets
├── scripts/
│   ├── setup_elastic.py           # Creates index + ingests all data
│   ├── seed_mongodb.py            # Seeds volunteers, routing rules, venues
│   └── inject_signals.py         # Demo trigger: green → amber → red
├── app/
│   └── streamlit_app.py           # Human approval UI (Day 2)
├── agent/
│   └── agent_prompt.py            # Gemini agent logic (Day 2)
├── .env.example
├── requirements.txt
└── README.md
```

---

## Quickstart

### 1. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/fifa-2026-ground-zero.git
cd fifa-2026-ground-zero
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your credentials (Elastic, MongoDB, NewsAPI, OWM, Arize)
```

### 3. Seed MongoDB

```bash
python scripts/seed_mongodb.py
```

### 4. Set up Elastic + ingest data

```bash
python scripts/setup_elastic.py
```

Open Kibana → Discover → select `fifa_incidents` index to verify.

### 5. Run the demo trigger

```bash
python scripts/inject_signals.py --batch 1   # green  (0-4 signals)
python scripts/inject_signals.py --batch 2   # amber  (5-9 signals, P2)
python scripts/inject_signals.py --batch 3   # red    (10+ signals, P1)
python scripts/inject_signals.py --reset     # clear demo data
```

### 6. Run the approval UI

```bash
streamlit run app/streamlit_app.py
```

---

## Data sources

| Source | Type | Used for |
|---|---|---|
| OpenWeatherMap API | Live | Heat and storm alerts at all 5 host cities |
| NewsAPI | Live | Real FIFA 2026 news articles |
| `synthetic_signals.json` | Generated | Fan social posts (simulates Twitter/Facebook) |
| MongoDB volunteers | Seeded | Shift gaps, no-show detection |

> In production, the synthetic feed adapter connects to Meta Webhooks, X Firehose, and FIFA's operations API. Agent logic is identical — only the data source adapters change.

---

## Hackathon track

**Partner:** Elastic (primary MCP integration)
**Challenge theme:** 2026 World Cup
**Event:** [Hackathon name on Devpost]

---

## License

MIT License — see [LICENSE](LICENSE)
