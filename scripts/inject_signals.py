"""
inject_signals.py
The live demo trigger — injects signals in 3 batches to show
cluster turning green → amber (P2) → red (P1) in Kibana.

Usage:
  python inject_signals.py --batch 1   # 2 signals  → stays green
  python inject_signals.py --batch 2   # +3 signals → amber P2
  python inject_signals.py --batch 3   # +6 signals + heat alert → red P1

Keep Kibana open with auto-refresh set to 5s before running.
"""

import os
import sys
import argparse
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from dotenv import load_dotenv

load_dotenv()

es = Elasticsearch(
    os.getenv("ELASTIC_URL"),
    api_key=os.getenv("ELASTIC_API_KEY")
)
INDEX = "fifa_incidents"
VENUE = "ATT Stadium Dallas"
GATE  = "Gate 7"

# ── Demo signal batches ───────────────────────────────────────────────────────
BATCHES = {
    1: [
        {"id": "demo_001", "text": "Gate 7 queue seems a bit slow today", "severity": "calm"},
        {"id": "demo_002", "text": "Waiting at Gate 7, not too bad yet",  "severity": "calm"},
    ],
    2: [
        {"id": "demo_003", "text": "Gate 7 is getting really crowded now",          "severity": "calm"},
        {"id": "demo_004", "text": "Queue at Gate 7 not moving at all!",             "severity": "calm"},
        {"id": "demo_005", "text": "Gate 7 completely blocked, people pushing hard", "severity": "calm"},
    ],
    3: [
        {"id": "demo_006", "text": "Gate 7 CRITICAL — crowd surge happening NOW",    "severity": "calm"},
        {"id": "demo_007", "text": "Someone fainted at Gate 7, need medical team",   "severity": "calm"},
        {"id": "demo_008", "text": "Gate 7 dangerous crush, kids at risk",           "severity": "calm"},
        {"id": "demo_009", "text": "EMERGENCY at Gate 7, security overwhelmed",      "severity": "calm"},
        {"id": "demo_010", "text": "Gate 7 needs backup NOW, fans panicking",        "severity": "calm"},
        {"id": "demo_011", "text": "Gate 7 still no help, situation deteriorating",  "severity": "calm"},
        # weather signal makes it worse
        {"id": "demo_weather", "text": f"Heat index 41°C at {VENUE}, fans collapsing in queue", "severity": "calm", "type": "weather_event", "temperature_c": 41.0},
    ],
}

SEVERITY_MAP = {
    range(0, 5):  ("calm", "green",  "P3 — Monitoring"),
    range(5, 10): ("P2",   "amber",  "P2 — Watch"),
    range(10, 99):("P1",   "red",    "P1 — CRITICAL"),
}

def get_severity(count):
    for r, (sev, color, label) in SEVERITY_MAP.items():
        if count in r:
            return sev, color, label
    return "P1", "red", "P1 — CRITICAL"

def count_existing_demo_signals():
    resp = es.count(index=INDEX, body={
        "query": {"bool": {"must": [
            {"term":  {"venue": VENUE}},
            {"term":  {"gate":  GATE}},
            {"prefix":{"id":    "demo_"}}
        ]}}
    })
    return resp["count"]

def inject_batch(batch_num):
    signals = BATCHES.get(batch_num)
    if not signals:
        print(f"Unknown batch: {batch_num}. Use 1, 2, or 3.")
        sys.exit(1)

    # Warn if starting at batch 1 but old demo signals exist
    if batch_num == 1:
        existing = count_existing_demo_signals()
        if existing > 0:
            print(f"⚠ Warning: {existing} old demo signals found at {GATE}.")
            print(f"  Run --reset first for a clean demo, or continue to add on top.")
            print(f"  Continuing in 2 seconds...")
            import time; time.sleep(2)

    now = datetime.now(timezone.utc).isoformat()
    for s in signals:
        doc = {
            "id":           s["id"],
            "text":         s["text"],
            "venue":        VENUE,
            "gate":         GATE,
            "type":         s.get("type", "crowd_surge"),
            "source":       "demo_inject",
            "severity":     "calm",
            "signal_count": 1,
            "status":       "open",
            "timestamp":    now,
            "ingested_at":  now,
            "temperature_c": s.get("temperature_c", None),
        }
        es.index(index=INDEX, id=s["id"], document=doc)

    # Count total demo signals now and update cluster severity
    total = count_existing_demo_signals()
    severity, color, label = get_severity(total)

    # Update ALL demo signals for this gate to new severity
    es.update_by_query(index=INDEX, body={
        "script": {
            "source": f"ctx._source.severity = '{severity}'; ctx._source.signal_count = {total};",
            "lang": "painless"
        },
        "query": {"bool": {"must": [
            {"term":  {"venue": VENUE}},
            {"term":  {"gate":  GATE}},
            {"prefix":{"id":    "demo_"}}
        ]}}
    })

    es.indices.refresh(index=INDEX)

    # Print clear visual feedback
    color_codes = {"green": "\033[92m", "amber": "\033[93m", "red": "\033[91m"}
    reset = "\033[0m"
    c = color_codes.get(color, "")

    print(f"\n{'='*50}")
    print(f"  Batch {batch_num} injected — {len(signals)} new signals")
    print(f"  Total signals at {GATE}: {total}")
    print(f"  {c}Cluster status: {label}{reset}")
    print(f"{'='*50}")
    print(f"\n  → Check Kibana dashboard now (auto-refresh 5s)")

    if severity == "P1":
        print(f"\n  🔴 P1 TRIGGERED — Streamlit approval queue should light up!")
    elif severity == "P2":
        print(f"\n  🟡 P2 WATCH — Agent is monitoring, escalation drafted")

def reset_demo():
    """Full demo reset — clears Elastic demo signals + MongoDB records + resets volunteers"""
    from pymongo import MongoClient
    mongo = MongoClient(os.getenv("MONGO_URI"))
    db    = mongo[os.getenv("MONGO_DB", "fifa_incidents")]

    # 1. Delete demo_ signals from Elastic
    r1 = es.delete_by_query(index=INDEX, body={"query": {"prefix": {"id": "demo_"}}})
    print(f"  Elastic: removed {r1.get('deleted', 0)} demo signals")

    # 2. Reset awaiting_approval + resolved signals back to open
    r2 = es.update_by_query(index=INDEX, body={
        "script": {
            "source": "ctx._source.status = 'open'; ctx._source.remove('cluster_id'); ctx._source.remove('drafted_action'); ctx._source.remove('routed_to');",
            "lang": "painless"
        },
        "query": {"terms": {"status": ["awaiting_approval", "resolved"]}}
    })
    print(f"  Elastic: reset {r2.get('updated', 0)} signals to open")
    es.indices.refresh(index=INDEX)

    # 3. Clear incident_log
    r3 = db.incident_log.delete_many({})
    print(f"  MongoDB: cleared {r3.deleted_count} incident_log records")

    # 4. Clear audit_log
    r4 = db.audit_log.delete_many({})
    print(f"  MongoDB: cleared {r4.deleted_count} audit_log entries")

    # 5. Reset dispatched volunteers to available
    r5 = db.volunteers.update_many(
        {"status": "dispatched"},
        {"$set": {"status": "available", "assigned_incident": None}}
    )
    print(f"  MongoDB: reset {r5.modified_count} dispatched volunteers → available")

    mongo.close()
    print("\n✅ Full reset complete — UI shows clean state (58 signals)")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FIFA Incident Demo Signal Injector")
    parser.add_argument("--batch", type=int, choices=[1, 2, 3], help="Batch to inject (1=green, 2=amber, 3=red)")
    parser.add_argument("--reset", action="store_true", help="Clear all demo signals for a fresh run")
    args = parser.parse_args()

    if args.reset:
        reset_demo()
    elif args.batch:
        inject_batch(args.batch)
    else:
        print("Usage:")
        print("  python inject_signals.py --batch 1   # green")
        print("  python inject_signals.py --batch 2   # amber P2")
        print("  python inject_signals.py --batch 3   # red P1")
        print("  python inject_signals.py --reset     # clear demo data")