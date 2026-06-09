"""
agent.py
Gemini agent that:
1. Reads P1/P2 incidents from Elastic
2. Looks up routing rules + available volunteers from MongoDB
3. Drafts an action plan
4. Logs every decision to Arize Phoenix for observability
"""

import os
import json
import uuid
import requests
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

# ── Clients ───────────────────────────────────────────────────────────────────
es = Elasticsearch(
    os.getenv("ELASTIC_URL"),
    api_key=os.getenv("ELASTIC_API_KEY")
)

mongo = MongoClient(os.getenv("MONGO_URI"))
db = mongo[os.getenv("MONGO_DB", "fifa_incidents")]

INDEX = "fifa_incidents"

# ── Arize Phoenix tracing ─────────────────────────────────────────────────────
PHOENIX_ENDPOINT = os.getenv("PHOENIX_COLLECTOR_ENDPOINT", "https://app.phoenix.arize.com")
PHOENIX_API_KEY  = os.getenv("ARIZE_API_KEY", "")
PHOENIX_SPACE    = os.getenv("ARIZE_SPACE_KEY", "")

def log_to_phoenix(incident, routing_rule, drafted_action, volunteer, confidence):
    """Log agent decision trace to Arize Phoenix"""
    try:
        trace = {
            "trace_id":       str(uuid.uuid4()),
            "incident_id":    incident.get("id", "unknown"),
            "input": {
                "venue":      incident.get("venue"),
                "gate":       incident.get("gate"),
                "type":       incident.get("type"),
                "severity":   incident.get("severity"),
                "signal_count": incident.get("signal_count", 1),
                "text":       incident.get("text", "")
            },
            "output": {
                "drafted_action": drafted_action,
                "routed_to":      routing_rule.get("p1_owner") if incident.get("severity") == "P1" else routing_rule.get("p2_owner"),
                "volunteer_assigned": volunteer.get("name") if volunteer else None,
            },
            "metadata": {
                "confidence":  confidence,
                "model":       "gemini-agent-v1",
                "timestamp":   datetime.now(timezone.utc).isoformat(),
            }
        }

        headers = {
            "Content-Type": "application/json",
            "api_key": PHOENIX_API_KEY,
            "space_id": PHOENIX_SPACE
        }

        resp = requests.post(
            f"{PHOENIX_ENDPOINT}/v1/traces",
            headers=headers,
            json=trace,
            timeout=5
        )
        if resp.status_code in [200, 201]:
            print(f"  ✓ Logged to Arize Phoenix: trace {trace['trace_id'][:8]}...")
        else:
            print(f"  ⚠ Phoenix log status: {resp.status_code}")
    except Exception as e:
        print(f"  ⚠ Phoenix logging failed: {e}")

# ── Step 1: Fetch unprocessed P1/P2 incidents from Elastic ────────────────────
def fetch_active_incidents():
    resp = es.search(index=INDEX, body={
        "query": {
            "bool": {
                "must": [
                    {"terms": {"severity": ["P1", "P2"]}},
                    {"term":  {"status": "open"}}
                ]
            }
        },
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": 20
    })
    hits = resp["hits"]["hits"]
    incidents = [h["_source"] for h in hits]
    print(f"✓ Found {len(incidents)} active P1/P2 incidents in Elastic")
    return incidents

# ── Step 2: Cluster signals by venue+gate+type ────────────────────────────────
def cluster_incidents(incidents):
    clusters = {}
    for inc in incidents:
        key = f"{inc.get('venue')}|{inc.get('gate')}|{inc.get('type')}"
        if key not in clusters:
            clusters[key] = {
                "venue":        inc.get("venue"),
                "gate":         inc.get("gate"),
                "type":         inc.get("type"),
                "severity":     inc.get("severity"),
                "signal_count": 0,
                "signals":      [],
                "latest_text":  inc.get("text", ""),
                "timestamp":    inc.get("timestamp"),
                "id":           inc.get("id")
            }
        clusters[key]["signal_count"] += inc.get("signal_count", 1)
        clusters[key]["signals"].append(inc.get("text", ""))
        # Keep highest severity
        if inc.get("severity") == "P1":
            clusters[key]["severity"] = "P1"

    result = list(clusters.values())
    print(f"✓ Clustered into {len(result)} unique incidents")
    return result

# ── Step 3: Look up routing rule from MongoDB ─────────────────────────────────
def get_routing_rule(incident_type):
    rule = db.routing_rules.find_one({"incident_type": incident_type})
    if not rule:
        # Default fallback rule
        rule = {
            "incident_type":       incident_type,
            "p1_owner":            "FIFA Operations Centre",
            "p2_owner":            "Venue Coordinator",
            "p1_action_template":  "Investigate {gate} at {venue} immediately.",
            "p2_action_template":  "Monitor situation at {gate}, {venue}.",
            "volunteers_needed_p1": 2,
            "volunteers_needed_p2": 1
        }
    return rule

# ── Step 4: Find available volunteers from MongoDB ────────────────────────────
def find_available_volunteers(venue, role, count):
    volunteers = list(db.volunteers.find(
        {"venue": venue, "role": role, "status": "available"},
        limit=count
    ))
    if not volunteers:
        # Try any available volunteer at venue
        volunteers = list(db.volunteers.find(
            {"venue": venue, "status": "available"},
            limit=count
        ))
    return volunteers

# ── Step 5: Draft action using Gemini ─────────────────────────────────────────
def draft_action_with_gemini(incident, routing_rule, volunteers):
    """
    Call Gemini API to draft a human-readable action plan.
    Falls back to template if API unavailable.
    """
    severity   = incident.get("severity", "P2")
    venue      = incident.get("venue", "Unknown venue")
    gate       = incident.get("gate", "Unknown gate")
    inc_type   = incident.get("type", "unknown")
    signals    = incident.get("signals", [incident.get("text", "")])
    vol_names  = [v["name"] for v in volunteers] if volunteers else []

    owner = routing_rule.get("p1_owner") if severity == "P1" else routing_rule.get("p2_owner")
    vol_count = routing_rule.get("volunteers_needed_p1") if severity == "P1" else routing_rule.get("volunteers_needed_p2")
    template  = routing_rule.get("p1_action_template") if severity == "P1" else routing_rule.get("p2_action_template")

    # Format template action
    template_action = template.format(
        gate=gate,
        venue=venue,
        volunteers=vol_count
    )

    # Try Gemini API
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if gemini_key:
        try:
            prompt = f"""You are a FIFA World Cup operations agent. 
An incident has been detected:
- Type: {inc_type}
- Severity: {severity}  
- Location: {gate} at {venue}
- Signal count: {incident.get('signal_count', 1)} reports
- Sample reports: {'; '.join(signals[:3])}
- Available volunteers: {', '.join(vol_names) if vol_names else 'checking roster'}

Draft a concise 2-sentence action plan for {owner}.
Be specific, actionable, and urgent for {severity} severity.
Do not include preamble, just the action."""

            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=10
            )
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                print(f"  ✓ Gemini drafted action for {severity} {inc_type}")
                return text.strip(), owner, 0.92
        except Exception as e:
            print(f"  ⚠ Gemini unavailable ({e}), using template")

    # Fallback to template
    vol_str = f"Assign {', '.join(vol_names[:vol_count])} to respond." if vol_names else f"Deploy {vol_count} available volunteers."
    action = f"{template_action} {vol_str}"
    print(f"  ✓ Template action drafted for {severity} {inc_type}")
    return action, owner, 0.78

# ── Step 6: Write pending incident to MongoDB + update Elastic ────────────────
def save_pending_incident(incident, drafted_action, routed_to, volunteers, confidence):
    incident_id = f"INC-{str(uuid.uuid4())[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    # Write to MongoDB incident_log
    db.incident_log.insert_one({
        "incident_id":      incident_id,
        "venue":            incident.get("venue"),
        "gate":             incident.get("gate"),
        "type":             incident.get("type"),
        "severity":         incident.get("severity"),
        "signal_count":     incident.get("signal_count", 1),
        "drafted_action":   drafted_action,
        "routed_to":        routed_to,
        "volunteers":       [v["name"] for v in volunteers],
        "status":           "awaiting_approval",
        "confidence":       confidence,
        "created_at":       now,
        "approved_at":      None,
        "approved_by":      None,
        "resolution":       None
    })

    # Update Elastic status to awaiting_approval
    es.update_by_query(index=INDEX, body={
        "script": {
            "source": f"""
                ctx._source.status = 'awaiting_approval';
                ctx._source.drafted_action = params.action;
                ctx._source.routed_to = params.routed_to;
                ctx._source.cluster_id = params.incident_id;
            """,
            "lang": "painless",
            "params": {
                "action":      drafted_action,
                "routed_to":   routed_to,
                "incident_id": incident_id
            }
        },
        "query": {"bool": {"must": [
            {"term": {"venue": incident.get("venue")}},
            {"term": {"gate":  incident.get("gate")}},
            {"term": {"type":  incident.get("type")}},
            {"terms": {"severity": ["P1", "P2"]}}
        ]}}
    })
    es.indices.refresh(index=INDEX)

    print(f"  ✓ Saved pending incident {incident_id} → MongoDB + Elastic updated")
    return incident_id

# ── MAIN AGENT LOOP ───────────────────────────────────────────────────────────
def run_agent():
    print("\n" + "="*55)
    print("  FIFA 2026 Ground Zero — Agent Running")
    print("="*55)

    # 1. Fetch active incidents
    incidents = fetch_active_incidents()
    if not incidents:
        print("✓ No active P1/P2 incidents. All clear!")
        return []

    # 2. Cluster
    clusters = cluster_incidents(incidents)

    results = []
    for cluster in clusters:
        print(f"\n── Processing: {cluster['severity']} {cluster['type']} @ {cluster['gate']}, {cluster['venue']}")

        # 3. Get routing rule from MongoDB
        rule = get_routing_rule(cluster["type"])

        # 4. Find volunteers from MongoDB
        vol_role  = "crowd_management" if cluster["type"] == "crowd_surge" else "fan_services"
        vol_count = rule.get("volunteers_needed_p1") if cluster["severity"] == "P1" else rule.get("volunteers_needed_p2", 1)
        volunteers = find_available_volunteers(cluster["venue"], vol_role, vol_count)
        print(f"  ✓ Found {len(volunteers)} available volunteers at {cluster['venue']}")

        # 5. Draft action with Gemini
        action, routed_to, confidence = draft_action_with_gemini(cluster, rule, volunteers)

        # 6. Save to MongoDB + update Elastic
        incident_id = save_pending_incident(cluster, action, routed_to, volunteers, confidence)

        # 7. Log to Arize Phoenix
        log_to_phoenix(cluster, rule, action, volunteers[0] if volunteers else None, confidence)

        results.append({
            "incident_id":    incident_id,
            "severity":       cluster["severity"],
            "type":           cluster["type"],
            "venue":          cluster["venue"],
            "gate":           cluster["gate"],
            "drafted_action": action,
            "routed_to":      routed_to,
            "confidence":     confidence,
            "volunteers":     [v["name"] for v in volunteers],
            "signal_count":   cluster["signal_count"],
            "status":         "awaiting_approval"
        })

        print(f"  ✓ Incident {incident_id} ready for human approval")
        print(f"  📋 Action: {action[:100]}...")

    print(f"\n✓ Agent complete — {len(results)} incidents queued for approval")
    print("="*55)
    return results

if __name__ == "__main__":
    run_agent()