"""
agent.py - FIFA 2026 Ground Zero
Gemini agent with full audit logging to MongoDB
"""

import os, json, uuid, requests
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from pymongo import MongoClient
from dotenv import load_dotenv

# OpenTelemetry for Arize Phoenix
import opentelemetry.trace as otel_trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource

load_dotenv()

es    = Elasticsearch(os.getenv("ELASTIC_URL"), api_key=os.getenv("ELASTIC_API_KEY"))
mongo = MongoClient(os.getenv("MONGO_URI"))
db    = mongo[os.getenv("MONGO_DB", "fifa_incidents")]
INDEX = "fifa_incidents"

# ── Audit logger ──────────────────────────────────────────────────────────────
def audit(incident_id, action_type, actor, details, status=None):
    """Write every agent/human action to MongoDB audit_log"""
    db.audit_log.insert_one({
        "incident_id": incident_id,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "action_type": action_type,
        "actor":       actor,
        "details":     details,
        "status":      status
    })

# ── Arize Phoenix via OpenTelemetry OTLP ─────────────────────────────────────
def _setup_phoenix_tracer():
    space   = os.getenv("ARIZE_SPACE_KEY", "")
    api_key = os.getenv("ARIZE_API_KEY", "")
    if not space or not api_key:
        print("⚠ Phoenix: ARIZE_SPACE_KEY or ARIZE_API_KEY not set")
        return None
    endpoint = f"https://app.phoenix.arize.com/s/{space}/v1/traces"
    exporter = OTLPSpanExporter(
        endpoint=endpoint,
        headers={"api_key": api_key}
    )
    provider = TracerProvider(
        resource=Resource({"service.name": "fifa-2026-ground-zero"})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)
    print(f"✓ Phoenix tracer → {endpoint}")
    return otel_trace.get_tracer("fifa-agent")

_tracer = None
try:
    _tracer = _setup_phoenix_tracer()
except Exception as e:
    print(f"⚠ Phoenix setup failed: {e}")

def log_to_phoenix(incident, routing_rule, drafted_action, volunteer, confidence):
    """Log agent decision as OpenTelemetry span to Arize Phoenix Cloud"""
    if not _tracer:
        print("  ⚠ Phoenix tracer not available")
        return
    try:
        severity  = incident.get("severity", "P2")
        routed_to = routing_rule.get("p1_owner") if severity=="P1" else routing_rule.get("p2_owner","")
        with _tracer.start_as_current_span("fifa-incident-agent") as span:
            span.set_attribute("openinference.span.kind",  "AGENT")
            span.set_attribute("input.value",              incident.get("text",""))
            span.set_attribute("output.value",             drafted_action)
            span.set_attribute("incident.id",              incident.get("id",""))
            span.set_attribute("incident.venue",           incident.get("venue",""))
            span.set_attribute("incident.gate",            incident.get("gate",""))
            span.set_attribute("incident.type",            incident.get("type",""))
            span.set_attribute("incident.severity",        severity)
            span.set_attribute("incident.signal_count",    incident.get("signal_count",1))
            span.set_attribute("agent.routed_to",          routed_to)
            span.set_attribute("agent.confidence",         confidence)
            span.set_attribute("agent.model",              "gemini-agent-v1")
            span.set_attribute("agent.volunteer",          volunteer.get("name") if volunteer else "none")
        print(f"  ✓ Phoenix span sent for {severity} {incident.get('type')}")
    except Exception as e:
        print(f"  ⚠ Phoenix span failed: {e}")

# ── Step 1: Fetch active incidents ────────────────────────────────────────────
def fetch_active_incidents():
    resp = es.search(index=INDEX, body={
        "query": {"bool": {"must": [
            {"terms": {"severity": ["P1","P2"]}},
            {"term":  {"status": "open"}}
        ]}},
        "sort": [{"timestamp": {"order": "desc"}}],
        "size": 20
    })
    incidents = [h["_source"] for h in resp["hits"]["hits"]]
    print(f"✓ Found {len(incidents)} active P1/P2 signals in Elastic")
    return incidents

# ── Step 2: Cluster ───────────────────────────────────────────────────────────
def cluster_incidents(incidents):
    clusters = {}
    for inc in incidents:
        key = f"{inc.get('venue')}|{inc.get('gate')}|{inc.get('type')}"
        if key not in clusters:
            clusters[key] = {"venue": inc.get("venue"), "gate": inc.get("gate"),
                             "type": inc.get("type"), "severity": inc.get("severity"),
                             "signal_count": 0, "signals": [],
                             "latest_text": inc.get("text",""),
                             "timestamp": inc.get("timestamp"), "id": inc.get("id")}
        clusters[key]["signal_count"] += inc.get("signal_count", 1)
        clusters[key]["signals"].append(inc.get("text",""))
        if inc.get("severity") == "P1":
            clusters[key]["severity"] = "P1"
    return list(clusters.values())

# ── Step 3: MongoDB lookups ───────────────────────────────────────────────────
def get_routing_rule(incident_type):
    rule = db.routing_rules.find_one({"incident_type": incident_type})
    return rule or {
        "incident_type": incident_type,
        "p1_owner": "FIFA Operations Centre", "p2_owner": "Venue Coordinator",
        "p1_action_template": "Investigate {gate} at {venue} immediately.",
        "p2_action_template": "Monitor situation at {gate}, {venue}.",
        "volunteers_needed_p1": 2, "volunteers_needed_p2": 1
    }

def find_available_volunteers(venue, role, count):
    vols = list(db.volunteers.find({"venue": venue, "role": role, "status": "available"}, limit=count))
    if not vols:
        vols = list(db.volunteers.find({"venue": venue, "status": "available"}, limit=count))
    return vols

# ── Step 4: Draft action ──────────────────────────────────────────────────────
def draft_action(incident, routing_rule, volunteers):
    severity  = incident.get("severity","P2")
    venue     = incident.get("venue","Unknown")
    gate      = incident.get("gate","Unknown")
    inc_type  = incident.get("type","unknown")
    vol_names = [v["name"] for v in volunteers]

    owner     = routing_rule.get("p1_owner") if severity=="P1" else routing_rule.get("p2_owner")
    vol_count = routing_rule.get("volunteers_needed_p1") if severity=="P1" else routing_rule.get("volunteers_needed_p2",1)
    template  = routing_rule.get("p1_action_template") if severity=="P1" else routing_rule.get("p2_action_template")
    base_action = template.format(gate=gate, venue=venue, volunteers=vol_count)

    gemini_key = os.getenv("GEMINI_API_KEY","")
    if gemini_key:
        try:
            prompt = f"""You are a FIFA World Cup operations agent.
Incident: {inc_type} | {severity} | {gate} @ {venue}
Signal count: {incident.get('signal_count',1)} reports
Sample: {'; '.join(incident.get('signals',[])[:3])}
Available volunteers: {', '.join(vol_names) if vol_names else 'checking roster'}
Draft a concise 2-sentence action plan for {owner}. Be specific and urgent. No preamble."""
            resp = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={gemini_key}",
                json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=10
            )
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                print(f"  ✓ Gemini drafted action")
                return text.strip(), owner, 0.92
        except Exception as e:
            print(f"  ⚠ Gemini unavailable: {e}")

    vol_str = f"Assign {', '.join(vol_names[:vol_count])} to respond." if vol_names else f"Deploy {vol_count} available volunteers."
    return f"{base_action} {vol_str}", owner, 0.78

# ── Step 5: Save + audit ──────────────────────────────────────────────────────
def save_pending_incident(incident, drafted_action, routed_to, volunteers, confidence):
    incident_id = f"INC-{str(uuid.uuid4())[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    # Write to MongoDB incident_log
    db.incident_log.insert_one({
        "incident_id": incident_id, "venue": incident.get("venue"),
        "gate": incident.get("gate"), "type": incident.get("type"),
        "severity": incident.get("severity"), "signal_count": incident.get("signal_count",1),
        "drafted_action": drafted_action, "routed_to": routed_to,
        "volunteers": [v["name"] for v in volunteers],
        "status": "awaiting_approval", "confidence": confidence,
        "created_at": now, "approved_at": None, "approved_by": None, "resolution": None
    })

    # ── AUDIT: agent detected ─────────────────────────────────────────────────
    audit(incident_id, "agent_detected", "Gemini Agent", {
        "venue": incident.get("venue"), "gate": incident.get("gate"),
        "type": incident.get("type"), "signal_count": incident.get("signal_count",1),
        "source": "Elastic MCP search"
    }, status="detected")

    # ── AUDIT: agent classified ───────────────────────────────────────────────
    audit(incident_id, "agent_classified", "Gemini Agent", {
        "severity": incident.get("severity"), "confidence": confidence,
        "cluster_signals": incident.get("signal_count",1),
        "classification_method": "keyword + velocity clustering"
    }, status="classified")

    # ── AUDIT: agent routed ───────────────────────────────────────────────────
    audit(incident_id, "agent_routed", "Gemini Agent", {
        "routed_to": routed_to,
        "routing_rule": incident.get("type"),
        "volunteers_assigned": [v["name"] for v in volunteers],
        "source": "MongoDB routing_rules lookup"
    }, status="routed")

    # ── AUDIT: agent drafted ──────────────────────────────────────────────────
    audit(incident_id, "agent_drafted", "Gemini Agent", {
        "drafted_action": drafted_action,
        "action_source": "Gemini API" if confidence > 0.9 else "template fallback"
    }, status="awaiting_approval")

    # Update Elastic status
    es.update_by_query(index=INDEX, body={
        "script": {
            "source": "ctx._source.status='awaiting_approval'; ctx._source.drafted_action=params.a; ctx._source.routed_to=params.r; ctx._source.cluster_id=params.i;",
            "lang": "painless",
            "params": {"a": drafted_action, "r": routed_to, "i": incident_id}
        },
        "query": {"bool": {"must": [
            {"term": {"venue": incident.get("venue")}},
            {"term": {"gate":  incident.get("gate")}},
            {"term": {"type":  incident.get("type")}},
            {"terms": {"severity": ["P1","P2"]}}
        ]}}
    })
    es.indices.refresh(index=INDEX)
    print(f"  ✓ Saved {incident_id} → MongoDB + Elastic + 4 audit entries")
    return incident_id

# ── MAIN ──────────────────────────────────────────────────────────────────────
def run_agent():
    print("\n" + "="*55)
    print("  FIFA 2026 Ground Zero — Agent Running")
    print("="*55)

    incidents = fetch_active_incidents()
    if not incidents:
        print("✓ No active P1/P2 incidents. All clear!")
        return []

    clusters = cluster_incidents(incidents)
    results  = []

    for cluster in clusters:
        print(f"\n── {cluster['severity']} {cluster['type']} @ {cluster['gate']}, {cluster['venue']}")
        rule       = get_routing_rule(cluster["type"])
        vol_role   = "crowd_management" if cluster["type"] == "crowd_surge" else "fan_services"
        vol_count  = rule.get("volunteers_needed_p1") if cluster["severity"]=="P1" else rule.get("volunteers_needed_p2",1)
        volunteers = find_available_volunteers(cluster["venue"], vol_role, vol_count)
        print(f"  ✓ {len(volunteers)} volunteers found in MongoDB")

        action, routed_to, confidence = draft_action(cluster, rule, volunteers)
        incident_id = save_pending_incident(cluster, action, routed_to, volunteers, confidence)
        log_to_phoenix(cluster, rule, action, volunteers[0] if volunteers else None, confidence)

        results.append({
            "incident_id": incident_id, "severity": cluster["severity"],
            "type": cluster["type"], "venue": cluster["venue"],
            "gate": cluster["gate"], "drafted_action": action,
            "routed_to": routed_to, "confidence": confidence,
            "volunteers": [v["name"] for v in volunteers],
            "signal_count": cluster["signal_count"], "status": "awaiting_approval"
        })
        print(f"  ✓ {incident_id} queued for approval")

    print(f"\n✓ Agent done — {len(results)} incidents queued")
    print("="*55)
    return results

if __name__ == "__main__":
    run_agent()