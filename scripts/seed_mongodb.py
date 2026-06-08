"""
seed_mongodb.py
Run once to populate MongoDB with volunteers, routing rules, and empty incident log.
Usage: python seed_mongodb.py
"""

import os
from datetime import datetime
from pymongo import MongoClient
from dotenv import load_dotenv

load_dotenv()

client = MongoClient(os.getenv("MONGO_URI"))
db = client[os.getenv("MONGO_DB", "fifa_incidents")]

# ── 1. ROUTING RULES ─────────────────────────────────────────────────────────
db.routing_rules.drop()
routing_rules = [
    {
        "incident_type": "crowd_surge",
        "p1_threshold": 10,
        "p2_threshold": 5,
        "p1_owner": "Stadium Security Lead",
        "p2_owner": "Crowd Management Coordinator",
        "p1_action_template": "Deploy {volunteers} crowd-management volunteers to {gate}. Open overflow gate. Alert medical team standby.",
        "p2_action_template": "Send {volunteers} volunteers to monitor {gate}. Prepare overflow plan.",
        "volunteers_needed_p1": 5,
        "volunteers_needed_p2": 2
    },
    {
        "incident_type": "ticketing_failure",
        "p1_threshold": 8,
        "p2_threshold": 3,
        "p1_owner": "FIFA Operations Centre",
        "p2_owner": "Venue Tech Support",
        "p1_action_template": "Activate manual ticket verification at {gate}. Deploy {volunteers} staff with handheld scanners. Notify FIFA IT.",
        "p2_action_template": "Alert FIFA IT helpdesk. Station {volunteers} staff at {gate} to assist fans.",
        "volunteers_needed_p1": 4,
        "volunteers_needed_p2": 2
    },
    {
        "incident_type": "weather_event",
        "p1_threshold": 3,
        "p2_threshold": 1,
        "p1_owner": "City Safety Operations",
        "p2_owner": "Venue Operations Manager",
        "p1_action_template": "Initiate weather delay protocol. Direct fans to covered areas. Contact match officials.",
        "p2_action_template": "Monitor weather feed. Brief stadium safety team. Prepare delay announcement.",
        "volunteers_needed_p1": 10,
        "volunteers_needed_p2": 4
    },
    {
        "incident_type": "volunteer_gap",
        "p1_threshold": 3,
        "p2_threshold": 1,
        "p1_owner": "Volunteer Coordinator",
        "p2_owner": "Venue Operations Manager",
        "p1_action_template": "Reassign {volunteers} available volunteers from low-traffic gates to {gate}. Activate standby list.",
        "p2_action_template": "Dispatch {volunteers} on-call volunteers to {gate}.",
        "volunteers_needed_p1": 3,
        "volunteers_needed_p2": 1
    },
    {
        "incident_type": "fan_complaint",
        "p1_threshold": 20,
        "p2_threshold": 8,
        "p1_owner": "FIFA Fan Experience Team",
        "p2_owner": "City Helpdesk",
        "p1_action_template": "Escalate to FIFA communications. Issue public statement. Deploy fan liaison team.",
        "p2_action_template": "Log complaints. Notify city helpdesk supervisor.",
        "volunteers_needed_p1": 2,
        "volunteers_needed_p2": 1
    }
]
db.routing_rules.insert_many(routing_rules)
print(f"✓ Inserted {len(routing_rules)} routing rules")

# ── 2. VOLUNTEERS ─────────────────────────────────────────────────────────────
db.volunteers.drop()
venues = [
    "ATT Stadium Dallas",
    "MetLife Stadium NJ",
    "SoFi Stadium LA",
    "Levi's Stadium SF",
    "Hard Rock Stadium Miami"
]
roles = ["crowd_management", "ticketing_support", "medical_liaison", "fan_services", "security_support"]
statuses = ["available", "available", "available", "on_shift", "no_show"]  # weighted toward available

volunteers = []
for i in range(1, 51):
    venue_idx = (i - 1) % len(venues)
    role_idx = (i - 1) % len(roles)
    status_idx = (i - 1) % len(statuses)
    gate_num = ((i - 1) % 12) + 1
    volunteers.append({
        "volunteer_id": f"VOL-{i:04d}",
        "name": f"Volunteer {i}",
        "venue": venues[venue_idx],
        "gate": f"Gate {gate_num}",
        "role": roles[role_idx],
        "shift_start": "18:00",
        "shift_end": "23:00",
        "status": statuses[status_idx],
        "phone": f"+1-555-{i:04d}",
        "flagged_at": None,
        "assigned_incident": None
    })

db.volunteers.insert_many(volunteers)
print(f"✓ Inserted {len(volunteers)} volunteers")

# ── 3. VENUE MAP ──────────────────────────────────────────────────────────────
db.venues.drop()
venue_data = [
    {"venue": "ATT Stadium Dallas",    "city": "Dallas, TX",      "capacity": 80000, "gates": 14, "lat": 32.748, "lon": -97.093},
    {"venue": "MetLife Stadium NJ",    "city": "East Rutherford, NJ", "capacity": 82500, "gates": 12, "lat": 40.813, "lon": -74.074},
    {"venue": "SoFi Stadium LA",       "city": "Inglewood, CA",   "capacity": 70240, "gates": 10, "lat": 33.953, "lon": -118.339},
    {"venue": "Levi's Stadium SF",     "city": "Santa Clara, CA", "capacity": 68500, "gates": 10, "lat": 37.403, "lon": -121.970},
    {"venue": "Hard Rock Stadium Miami","city": "Miami Gardens, FL","capacity": 65326, "gates": 10, "lat": 25.958, "lon": -80.239}
]
db.venues.insert_many(venue_data)
print(f"✓ Inserted {len(venue_data)} venues")

# ── 4. INCIDENT LOG (empty — agent writes here) ───────────────────────────────
db.incident_log.drop()
db.incident_log.create_index("incident_id", unique=True)
print("✓ Created incident_log collection (empty, ready for agent writes)")

# ── SUMMARY ───────────────────────────────────────────────────────────────────
print("\n── MongoDB collections ready ──")
for col in db.list_collection_names():
    print(f"  {col}: {db[col].count_documents({})} documents")

client.close()
