
"""
streamlit_app.py
Human-in-the-loop approval UI for FIFA 2026 Ground Zero.
Shows pending incidents with drafted actions.
Approve → resolves in MongoDB + Elastic.
Override → lets human edit the action before saving.
"""

import os
import sys
import streamlit as st
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from pymongo import MongoClient
from dotenv import load_dotenv

# Add parent dir to path for agent import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.agent import run_agent

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="FIFA 2026 Ground Zero",
    page_icon="⚽",
    layout="wide"
)

# ── Clients ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_clients():
    es = Elasticsearch(
        os.getenv("ELASTIC_URL"),
        api_key=os.getenv("ELASTIC_API_KEY")
    )
    mongo = MongoClient(os.getenv("MONGO_URI"))
    db = mongo[os.getenv("MONGO_DB", "fifa_incidents")]
    return es, db

es, db = get_clients()

# ── Helpers ───────────────────────────────────────────────────────────────────
def get_pending_incidents():
    return list(db.incident_log.find(
        {"status": "awaiting_approval"},
        sort=[("created_at", -1)]
    ))

def get_resolved_incidents():
    return list(db.incident_log.find(
        {"status": "resolved"},
        sort=[("approved_at", -1)],
        limit=10
    ))

def approve_incident(incident_id, action, approved_by="Operations Commander"):
    now = datetime.now(timezone.utc).isoformat()

    # Update MongoDB
    db.incident_log.update_one(
        {"incident_id": incident_id},
        {"$set": {
            "status":      "resolved",
            "approved_at": now,
            "approved_by": approved_by,
            "resolution":  action
        }}
    )

    # Update Elastic
    es.update_by_query(index="fifa_incidents", body={
        "script": {
            "source": "ctx._source.status = 'resolved'",
            "lang": "painless"
        },
        "query": {"term": {"cluster_id": incident_id}}
    })
    es.indices.refresh(index="fifa_incidents")

def override_incident(incident_id, new_action, approved_by="Operations Commander"):
    approve_incident(incident_id, new_action, approved_by)

def get_elastic_stats():
    try:
        total    = es.count(index="fifa_incidents")["count"]
        p1_count = es.count(index="fifa_incidents", body={"query": {"term": {"severity": "P1"}}})["count"]
        p2_count = es.count(index="fifa_incidents", body={"query": {"term": {"severity": "P2"}}})["count"]
        resolved = es.count(index="fifa_incidents", body={"query": {"term": {"status": "resolved"}}})["count"]
        return total, p1_count, p2_count, resolved
    except:
        return 0, 0, 0, 0

# ── Severity badge ────────────────────────────────────────────────────────────
def severity_badge(severity):
    colors = {"P1": "🔴", "P2": "🟡", "calm": "🟢"}
    return colors.get(severity, "⚪")

# ── UI ────────────────────────────────────────────────────────────────────────
st.title("⚽ FIFA 2026 Ground Zero")
st.caption("Real-Time Incident Intelligence — Human Approval Console")

# ── Top stats bar ─────────────────────────────────────────────────────────────
total, p1, p2, resolved = get_elastic_stats()
pending = get_pending_incidents()

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Signals",   total)
col2.metric("🔴 P1 Critical",  p1,  delta=f"+{p1}" if p1 > 0 else None, delta_color="inverse")
col3.metric("🟡 P2 Watch",     p2,  delta=f"+{p2}" if p2 > 0 else None, delta_color="inverse")
col4.metric("✅ Resolved",     resolved)
col5.metric("⏳ Awaiting Approval", len(pending))

st.divider()

# ── Agent controls ────────────────────────────────────────────────────────────
col_a, col_b = st.columns([1, 3])
with col_a:
    if st.button("🤖 Run Agent", type="primary", use_container_width=True):
        with st.spinner("Agent scanning Elastic, querying MongoDB, drafting actions..."):
            results = run_agent()
        if results:
            st.success(f"✓ Agent queued {len(results)} incidents for approval")
            st.rerun()
        else:
            st.info("No active P1/P2 incidents found. Try injecting signals first.")

with col_b:
    st.caption("Agent reads P1/P2 clusters from Elastic → looks up routing rules & volunteers from MongoDB → drafts action → waits for your approval below")

st.divider()

# ── Pending approval queue ────────────────────────────────────────────────────
st.subheader(f"⏳ Pending Approval ({len(pending)})")

if not pending:
    st.info("No incidents awaiting approval. Run the agent after injecting signals.")
else:
    for inc in pending:
        severity = inc.get("severity", "P2")
        badge    = severity_badge(severity)

        border_color = "#E24B4A" if severity == "P1" else "#BA7517"

        with st.container(border=True):
            # Header row
            h1, h2, h3 = st.columns([2, 2, 1])
            with h1:
                st.markdown(f"### {badge} {inc['incident_id']} — {severity}")
                st.markdown(f"**{inc.get('type', '').replace('_', ' ').title()}** · {inc.get('venue')} · {inc.get('gate')}")
            with h2:
                st.markdown(f"**Routed to:** {inc.get('routed_to', 'Unknown')}")
                st.markdown(f"**Signal count:** {inc.get('signal_count', 1)} · **Confidence:** {int(inc.get('confidence', 0.8) * 100)}%")
                if inc.get("volunteers"):
                    st.markdown(f"**Volunteers:** {', '.join(inc['volunteers'][:3])}")
            with h3:
                created = inc.get("created_at", "")[:16].replace("T", " ")
                st.caption(f"Created: {created}")

            # Drafted action
            st.markdown("**📋 Drafted Action:**")
            action_key = f"action_{inc['incident_id']}"
            edited_action = st.text_area(
                label="Action (editable)",
                value=inc.get("drafted_action", ""),
                height=80,
                key=action_key,
                label_visibility="collapsed"
            )

            # Action buttons
            b1, b2, b3 = st.columns([1, 1, 3])
            with b1:
                if st.button(f"✅ Approve", key=f"approve_{inc['incident_id']}", type="primary", use_container_width=True):
                    approve_incident(inc["incident_id"], edited_action)
                    st.success(f"✓ {inc['incident_id']} approved and resolved!")
                    st.rerun()
            with b2:
                if st.button(f"✏️ Override & Save", key=f"override_{inc['incident_id']}", use_container_width=True):
                    override_incident(inc["incident_id"], edited_action)
                    st.warning(f"⚠ {inc['incident_id']} overridden and resolved")
                    st.rerun()
            with b3:
                st.caption("Approve = accept drafted action · Override = save your edited version")

st.divider()

# ── Resolved incidents log ────────────────────────────────────────────────────
resolved_list = get_resolved_incidents()
st.subheader(f"✅ Recently Resolved ({len(resolved_list)})")

if not resolved_list:
    st.caption("No resolved incidents yet.")
else:
    for inc in resolved_list:
        with st.expander(f"✅ {inc['incident_id']} — {inc.get('type','').replace('_',' ').title()} @ {inc.get('venue')} · Resolved by {inc.get('approved_by','unknown')}"):
            st.markdown(f"**Resolution:** {inc.get('resolution', 'N/A')}")
            st.markdown(f"**Approved at:** {inc.get('approved_at','')[:16].replace('T',' ')}")

st.divider()

# ── Footer ────────────────────────────────────────────────────────────────────
st.caption("FIFA 2026 Ground Zero · Built with Gemini + Elastic + MongoDB + Arize Phoenix · Hackathon Demo")

# Auto-refresh every 10 seconds
st.markdown("""
<script>
setTimeout(function() { window.location.reload(); }, 10000);
</script>
""", unsafe_allow_html=True)