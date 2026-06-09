"""
streamlit_app.py — FIFA 2026 Ground Zero
Clean UI: no scrolling ticker, auto-refresh, no sidebar scroll issue
"""

import os, sys, time
import streamlit as st
from datetime import datetime, timezone
from elasticsearch import Elasticsearch
from pymongo import MongoClient
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from agent.agent import run_agent, audit

load_dotenv()

st.set_page_config(page_title="FIFA 2026 Ground Zero", page_icon="⚽", layout="wide")

st.markdown("""
<style>
.stApp { background-color: #0a0e1a; }
.main .block-container { padding-top: 1rem; max-width: 1400px; }

/* Hide sidebar entirely — we put everything inline */
[data-testid="stSidebar"] { display: none; }

.dash-header {
    background: linear-gradient(135deg,#1a1f35 0%,#0d1117 100%);
    border:1px solid #2d3561; border-radius:12px;
    padding:1rem 1.5rem; margin-bottom:1rem;
    display:flex; align-items:center;
}
.incident-p1 {
    background:linear-gradient(135deg,#1a0a0a 0%,#111827 100%);
    border:1.5px solid #dc2626; border-radius:12px;
    padding:1.2rem; margin-bottom:0.8rem;
    box-shadow:0 0 20px rgba(220,38,38,0.15);
}
.incident-p2 {
    background:linear-gradient(135deg,#1a1500 0%,#111827 100%);
    border:1.5px solid #d97706; border-radius:12px;
    padding:1.2rem; margin-bottom:0.8rem;
    box-shadow:0 0 20px rgba(217,119,6,0.15);
}
.vol-chip {
    display:inline-block; background:#1e3a5f; color:#60a5fa;
    border:1px solid #2563eb; border-radius:20px;
    padding:2px 10px; font-size:11px; margin:2px;
}
.vol-chip-dispatched {
    display:inline-block; background:#064e3b; color:#34d399;
    border:1px solid #059669; border-radius:20px;
    padding:2px 10px; font-size:11px; margin:2px;
}
.vol-chip-absent {
    display:inline-block; background:#4a1942; color:#f472b6;
    border:1px solid #db2777; border-radius:20px;
    padding:2px 10px; font-size:11px; margin:2px;
}
.audit-entry {
    background:#111827; border-left:3px solid #374151;
    border-radius:0 8px 8px 0; padding:0.6rem 1rem; margin-bottom:6px;
}
.audit-agent  { border-left-color:#6366f1; }
.audit-human  { border-left-color:#10b981; }
.audit-system { border-left-color:#f59e0b; }

/* Status bar — simple, no animation */
.status-bar {
    background:#0d1117; border:1px solid #1f2937;
    border-radius:8px; padding:0.5rem 1.2rem;
    font-size:12px; color:#9ca3af; margin-bottom:1rem;
    display:flex; align-items:center; gap:16px; flex-wrap:wrap;
}
.status-item { display:flex; align-items:center; gap:6px; }

/* Blinking dot */
@keyframes blink {
    0%,100% { opacity:1; box-shadow:0 0 6px #10b981; }
    50%      { opacity:0.2; box-shadow:none; }
}
.live-dot {
    width:9px; height:9px; background:#10b981;
    border-radius:50%; display:inline-block;
    animation:blink 1.4s infinite; vertical-align:middle;
}
@keyframes blink-red {
    0%,100% { opacity:1; box-shadow:0 0 8px #ef4444; }
    50%      { opacity:0.2; box-shadow:none; }
}
.live-dot-red {
    width:9px; height:9px; background:#ef4444;
    border-radius:50%; display:inline-block;
    animation:blink-red 1s infinite; vertical-align:middle;
}

h1,h2,h3 { color:#f9fafb !important; }
p,li { color:#d1d5db; }
.stTextArea textarea { background:#1f2937; color:#f9fafb; border:1px solid #374151; }
.stButton button { border-radius:8px; font-weight:600; }
.stTabs [data-baseweb="tab-list"] { background:#111827; border-radius:10px; padding:4px; }
.stTabs [data-baseweb="tab"] { color:#9ca3af; border-radius:8px; }
.stTabs [aria-selected="true"] { background:#1f2937; color:#f9fafb !important; }
</style>
""", unsafe_allow_html=True)

# ── Clients ───────────────────────────────────────────────────────────────────
@st.cache_resource
def get_clients():
    es = Elasticsearch(os.getenv("ELASTIC_URL"), api_key=os.getenv("ELASTIC_API_KEY"))
    mongo = MongoClient(os.getenv("MONGO_URI"))
    return es, mongo[os.getenv("MONGO_DB","fifa_incidents")]

es, db = get_clients()

# ── Auto-refresh every 10 seconds ─────────────────────────────────────────────
if "last_refresh" not in st.session_state:
    st.session_state.last_refresh = time.time()

if time.time() - st.session_state.last_refresh > 10:
    st.session_state.last_refresh = time.time()
    st.rerun()

# ── Data helpers ──────────────────────────────────────────────────────────────
def get_pending():  return list(db.incident_log.find({"status":"awaiting_approval"}, sort=[("created_at",-1)]))
def get_resolved(): return list(db.incident_log.find({"status":"resolved"}, sort=[("approved_at",-1)], limit=20))
def get_audit_for(incident_id): return list(db.audit_log.find({"incident_id":incident_id}, sort=[("timestamp",1)]))
def get_all_audit(): return list(db.audit_log.find({}, sort=[("timestamp",-1)], limit=50))

def get_stats():
    try:
        total    = es.count(index="fifa_incidents")["count"]
        p1       = es.count(index="fifa_incidents", body={"query":{"term":{"severity":"P1"}}})["count"]
        p2       = es.count(index="fifa_incidents", body={"query":{"term":{"severity":"P2"}}})["count"]
        resolved = es.count(index="fifa_incidents", body={"query":{"term":{"status":"resolved"}}})["count"]
        return total, p1, p2, resolved
    except: return 0,0,0,0

def get_volunteer_stats():
    available  = db.volunteers.count_documents({"status":"available"})
    dispatched = db.volunteers.count_documents({"status":"dispatched"})
    no_show    = db.volunteers.count_documents({"status":"no_show"})
    on_shift   = db.volunteers.count_documents({"status":"on_shift"})
    return available, dispatched, no_show, on_shift

def approve_incident(incident_id, action, by="Ops Commander"):
    now = datetime.now(timezone.utc).isoformat()
    inc = db.incident_log.find_one({"incident_id": incident_id})
    volunteer_names = inc.get("volunteers",[]) if inc else []

    db.incident_log.update_one({"incident_id":incident_id},
        {"$set":{"status":"resolved","approved_at":now,"approved_by":by,"resolution":action}})

    dispatched_count = 0
    if volunteer_names:
        db.volunteers.update_many(
            {"name":{"$in":volunteer_names}},
            {"$set":{"status":"dispatched","assigned_incident":incident_id}}
        )
        dispatched_count = len(volunteer_names)

    es.update_by_query(index="fifa_incidents", body={
        "script":{"source":"ctx._source.status='resolved'","lang":"painless"},
        "query":{"term":{"cluster_id":incident_id}}
    })
    es.indices.refresh(index="fifa_incidents")

    if volunteer_names:
        audit(incident_id, "volunteers_dispatched", "System", {
            "volunteers": volunteer_names, "count": len(volunteer_names),
            "venue": inc.get("venue") if inc else "", "gate": inc.get("gate") if inc else "",
            "new_status": "dispatched"
        }, status="resolved")

    action_type = "human_approved" if "override" not in by.lower() else "human_overridden"
    audit(incident_id, action_type, by, {
        "resolution": action, "approved_at": now,
        "volunteers_dispatched": dispatched_count
    }, status="resolved")

    audit(incident_id, "resolved", "System", {
        "elastic_updated": True, "mongodb_updated": True
    }, status="resolved")

    return dispatched_count

# ── Header ────────────────────────────────────────────────────────────────────
total, p1, p2, res_count = get_stats()
pending = get_pending()
avail, disp, nshow, onshift = get_volunteer_stats()
now_str = datetime.now().strftime('%H:%M:%S')

st.markdown(f"""
<div class="dash-header">
    <span style="font-size:26px">⚽</span>
    <span style="font-weight:700;color:#f9fafb;font-size:1.3rem;margin-left:10px;">FIFA 2026 Ground Zero</span>
    <span style="color:#6b7280;font-size:0.8rem;margin-left:10px;">Real-Time Incident Intelligence</span>
    <span style="margin-left:auto;display:flex;align-items:center;gap:8px;">
        <span class="live-dot"></span>
        <span style="color:#10b981;font-size:12px;font-weight:700;letter-spacing:0.08em;">LIVE</span>
        <span style="color:#374151;font-size:12px;margin-left:8px;">🕐 {now_str} UTC</span>
    </span>
</div>
""", unsafe_allow_html=True)

# ── Stats row ─────────────────────────────────────────────────────────────────
c1,c2,c3,c4,c5,c6 = st.columns(6)
c1.metric("📊 Total Signals",   total)
c2.metric("🔴 P1 Critical",     p1,   delta=f"+{p1}"   if p1>0  else None, delta_color="inverse")
c3.metric("🟡 P2 Watch",        p2,   delta=f"+{p2}"   if p2>0  else None, delta_color="inverse")
c4.metric("✅ Resolved",        res_count)
c5.metric("⏳ Pending",         len(pending))
c6.metric("🔵 Dispatched Vols", disp, delta=f"+{disp}" if disp>0 else None, delta_color="normal")

# ── Simple status bar (no scrolling) ─────────────────────────────────────────
alert_dot  = '<span class="live-dot-red"></span>' if pending else '<span class="live-dot"></span>'
alert_text = f'<span style="color:#ef4444;font-weight:600;">{len(pending)} incident(s) awaiting approval</span>' if pending else '<span style="color:#10b981;">All clear</span>'

st.markdown(f"""
<div class="status-bar">
    <div class="status-item">{alert_dot} &nbsp;{alert_text}</div>
    <div class="status-item">🏟️ 5 venues monitored</div>
    <div class="status-item">⚡ Elastic MCP connected</div>
    <div class="status-item">👥 {avail} available · {disp} dispatched · {nshow} no-show</div>
    <div class="status-item" style="margin-left:auto;color:#4b5563;">↻ auto-refresh 10s</div>
</div>
""", unsafe_allow_html=True)

# ── Info row: data sources + venues inline (replaces sidebar) ─────────────────
with st.expander("ℹ️  System info — data sources, venues, MCP", expanded=False):
    i1, i2, i3 = st.columns(3)
    with i1:
        st.markdown("**📡 Data Sources**")
        for s in ["🟢 Elastic MCP — live","🟢 MongoDB — live",
                  "🟢 Arize Phoenix — live","🟢 OpenWeatherMap","🟢 NewsAPI"]:
            st.caption(s)
    with i2:
        st.markdown("**🏟️ Active Venues**")
        for v in ["AT&T Stadium Dallas","MetLife Stadium NJ",
                  "SoFi Stadium LA","Hard Rock Miami","Levi's Stadium SF"]:
            st.caption(f"📍 {v}")
    with i3:
        st.markdown("**🔗 MCP Integration**")
        st.caption("Primary: Elastic MCP Server v0.3.1")
        st.caption("Protocol: streamable-HTTP")
        st.caption("Tools: search, update_by_query")

st.divider()

# ── Agent run ─────────────────────────────────────────────────────────────────
col_btn, col_desc = st.columns([1,4])
with col_btn:
    run_btn = st.button("🤖  Run Agent", type="primary", use_container_width=True)
with col_desc:
    st.markdown(
        '<div style="padding:8px 0;color:#9ca3af;font-size:13px;">'
        'Reads P1/P2 from <b style="color:#f59e0b">Elastic MCP</b> → '
        'routing rules + volunteers from <b style="color:#10b981">MongoDB</b> → '
        'drafts with <b style="color:#6366f1">Gemini</b> → '
        'logs to <b style="color:#f97316">Arize Phoenix</b> → '
        'every step in <b style="color:#06b6d4">audit trail</b></div>',
        unsafe_allow_html=True)

if run_btn:
    with st.spinner("🤖 Agent running..."):
        results = run_agent()
    if results:
        st.success(f"✓ {len(results)} incident(s) queued for approval")
        time.sleep(0.5); st.rerun()
    else:
        st.info("No active P1/P2 incidents. Inject signals first.")

st.divider()

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab1, tab2, tab3, tab4 = st.tabs([
    f"⏳  Pending  ({len(pending)})",
    f"✅  Resolved  ({res_count})",
    f"👥  Volunteers  ({disp} dispatched)",
    "📋  Audit Trail"
])

# ── TAB 1: Pending ────────────────────────────────────────────────────────────
with tab1:
    if not pending:
        st.markdown("""
        <div style="background:#111827;border:1px dashed #374151;border-radius:10px;
                    padding:2rem;text-align:center;color:#6b7280;margin-top:1rem;">
            <div style="font-size:2rem">✅</div>
            <div style="margin-top:8px;">No incidents awaiting approval</div>
            <div style="font-size:12px;margin-top:4px;">Inject signals then click Run Agent</div>
        </div>""", unsafe_allow_html=True)
    else:
        for inc in pending:
            sev  = inc.get("severity","P2")
            icon = "🔴" if sev=="P1" else "🟡"
            card = f"incident-{sev.lower()}"
            vol_names = inc.get("volunteers",[])
            vol_chips = "".join([f'<span class="vol-chip">👤 {v}</span>' for v in vol_names]) if vol_names else "<span style='color:#6b7280;font-size:11px;'>No volunteers assigned</span>"

            st.markdown(f"""
            <div class="{card}">
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">
                    <span style="font-size:20px">{icon}</span>
                    <span style="font-weight:700;color:#f9fafb;font-size:15px;">{inc['incident_id']}</span>
                    <span style="background:{'#dc2626' if sev=='P1' else '#d97706'};color:white;
                                 padding:2px 10px;border-radius:20px;font-size:11px;">{sev}</span>
                    <span style="color:#6b7280;font-size:12px;margin-left:auto;">
                        {inc.get('created_at','')[:16].replace('T',' ')} UTC
                    </span>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:10px;">
                    <div>
                        <div style="color:#9ca3af;font-size:11px;text-transform:uppercase;">Incident</div>
                        <div style="color:#f9fafb;font-weight:500;">{inc.get('type','').replace('_',' ').title()}</div>
                        <div style="color:#6b7280;font-size:12px;">{inc.get('venue')} · {inc.get('gate')}</div>
                    </div>
                    <div>
                        <div style="color:#9ca3af;font-size:11px;text-transform:uppercase;">Routed to</div>
                        <div style="color:#f9fafb;font-weight:500;">{inc.get('routed_to','Unknown')}</div>
                        <div style="color:#6b7280;font-size:12px;">
                            {inc.get('signal_count',1)} signals · {int(inc.get('confidence',0.8)*100)}% confidence
                        </div>
                    </div>
                </div>
                <div>
                    <div style="color:#9ca3af;font-size:11px;text-transform:uppercase;margin-bottom:4px;">
                        Volunteers to dispatch ({len(vol_names)})
                    </div>
                    {vol_chips}
                </div>
            </div>""", unsafe_allow_html=True)

            edited = st.text_area("📋 Drafted Action:",
                value=inc.get("drafted_action",""), height=80,
                key=f"act_{inc['incident_id']}")

            b1,b2,b3 = st.columns([1,1,3])
            with b1:
                if st.button("✅ Approve", key=f"app_{inc['incident_id']}",
                             type="primary", use_container_width=True):
                    n = approve_incident(inc["incident_id"], edited)
                    st.success(f"✓ Approved! {n} volunteer(s) dispatched 🔵")
                    time.sleep(0.5); st.rerun()
            with b2:
                if st.button("✏️ Override", key=f"ov_{inc['incident_id']}",
                             use_container_width=True):
                    n = approve_incident(inc["incident_id"], edited, "Ops Commander (override)")
                    st.warning(f"⚠ Overridden. {n} volunteer(s) dispatched.")
                    time.sleep(0.5); st.rerun()
            with b3:
                st.caption("Approve = accept drafted action · Override = save your edited version")
            st.divider()

# ── TAB 2: Resolved ───────────────────────────────────────────────────────────
with tab2:
    resolved_list = get_resolved()
    if not resolved_list:
        st.info("No resolved incidents yet.")
    else:
        for inc in resolved_list:
            sev  = inc.get("severity","P2")
            icon = "🔴" if sev=="P1" else "🟡"
            vol_names = inc.get("volunteers",[])

            with st.expander(
                f"✅  {inc['incident_id']}  ·  {icon} {sev}  ·  "
                f"{inc.get('type','').replace('_',' ').title()}  ·  "
                f"{inc.get('venue')} · {inc.get('gate')}  ·  "
                f"Resolved {inc.get('approved_at','')[:16].replace('T',' ')} UTC"
            ):
                r1,r2 = st.columns(2)
                with r1:
                    st.markdown(f"**Resolution:** {inc.get('resolution','N/A')}")
                    st.markdown(f"**Approved by:** {inc.get('approved_by','unknown')}")
                    st.markdown(f"**Signals:** {inc.get('signal_count',1)} · **Confidence:** {int(inc.get('confidence',0.8)*100)}%")
                with r2:
                    if vol_names:
                        st.markdown("**👥 Volunteers Dispatched:**")
                        live_vols = list(db.volunteers.find({"name":{"$in":vol_names}}))
                        vol_html = ""
                        for v in live_vols:
                            status = v.get("status","unknown")
                            chip   = "vol-chip-dispatched" if status=="dispatched" else "vol-chip-absent" if status=="no_show" else "vol-chip"
                            icon_v = "🔵" if status=="dispatched" else "🔴" if status=="no_show" else "👤"
                            vol_html += f'<span class="{chip}">{icon_v} {v["name"]} · {status}</span> '
                        st.markdown(vol_html, unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("**📋 Audit Trail:**")
                for entry in get_audit_for(inc["incident_id"]):
                    atype  = entry.get("action_type","")
                    actor  = entry.get("actor","")
                    ts     = entry.get("timestamp","")[:16].replace("T"," ")
                    css    = "audit-agent" if "agent" in atype else ("audit-human" if "human" in atype else "audit-system")
                    icon_a = "🤖" if "agent" in atype else ("👤" if "human" in atype else "⚙️")
                    if atype == "volunteers_dispatched": icon_a = "🔵"
                    st.markdown(f"""
                    <div class="audit-entry {css}">
                        <span style="font-size:11px;color:#6b7280;">{ts} UTC</span>
                        <span style="margin-left:8px;">{icon_a}</span>
                        <span style="color:#f9fafb;font-weight:500;margin-left:4px;">{atype.replace('_',' ').title()}</span>
                        <span style="color:#9ca3af;font-size:11px;margin-left:8px;">by {actor}</span>
                        <div style="color:#6b7280;font-size:11px;margin-top:3px;">
                            {', '.join([f'{k}: {v}' for k,v in entry.get('details',{}).items() if k not in ['resolution','final_action','drafted_action']][:4])}
                        </div>
                    </div>""", unsafe_allow_html=True)

# ── TAB 3: Volunteers ─────────────────────────────────────────────────────────
with tab3:
    st.markdown("### 👥 Volunteer Roster")
    st.caption("Live from MongoDB — updates when incidents are approved")

    vs1,vs2,vs3,vs4 = st.columns(4)
    vs1.metric("🟢 Available",  avail)
    vs2.metric("🔵 Dispatched", disp,   delta=f"+{disp}" if disp>0 else None, delta_color="normal")
    vs3.metric("🟡 On Shift",   onshift)
    vs4.metric("🔴 No Show",    nshow,  delta=f"+{nshow}" if nshow>0 else None, delta_color="inverse")
    st.divider()

    if disp > 0:
        st.markdown("#### 🔵 Currently Dispatched")
        for v in db.volunteers.find({"status":"dispatched"}):
            inc_id     = v.get("assigned_incident","—")
            inc_detail = db.incident_log.find_one({"incident_id":inc_id})
            inc_type   = inc_detail.get("type","").replace("_"," ").title() if inc_detail else "—"
            inc_venue  = inc_detail.get("venue","—") if inc_detail else "—"
            inc_gate   = inc_detail.get("gate","—")  if inc_detail else "—"
            st.markdown(f"""
            <div style="background:#071a0f;border:1px solid #065f46;border-radius:8px;
                        padding:0.7rem 1rem;margin-bottom:6px;display:flex;align-items:center;gap:12px;">
                <span style="font-size:18px">🔵</span>
                <div style="flex:1;">
                    <span style="color:#f9fafb;font-weight:500;">{v['name']}</span>
                    <span style="color:#6b7280;font-size:12px;margin-left:8px;">{v.get('role','').replace('_',' ').title()}</span>
                    <div style="color:#34d399;font-size:11px;margin-top:2px;">
                        Dispatched → {inc_type} · {inc_venue} · {inc_gate}
                    </div>
                </div>
                <span style="color:#34d399;font-size:11px;background:#064e3b;padding:2px 8px;border-radius:10px;">dispatched</span>
            </div>""", unsafe_allow_html=True)
        st.divider()

    if nshow > 0:
        st.markdown("#### 🔴 No-Shows")
        for v in db.volunteers.find({"status":"no_show"}):
            st.markdown(f"""
            <div style="background:#1a0a0a;border:1px solid #7f1d1d;border-radius:8px;
                        padding:0.7rem 1rem;margin-bottom:6px;">
                <span>🔴</span>
                <span style="color:#f9fafb;font-weight:500;margin-left:8px;">{v['name']}</span>
                <span style="color:#6b7280;font-size:12px;margin-left:8px;">{v.get('role','').replace('_',' ').title()} · {v.get('venue','')}</span>
            </div>""", unsafe_allow_html=True)
        st.divider()

    st.markdown("#### 🟢 Availability by Venue")
    for venue in ["ATT Stadium Dallas","MetLife Stadium NJ","SoFi Stadium LA",
                  "Levi's Stadium SF","Hard Rock Stadium Miami"]:
        count   = db.volunteers.count_documents({"venue":venue,"status":"available"})
        total_v = db.volunteers.count_documents({"venue":venue})
        pct     = int((count/total_v)*100) if total_v else 0
        bar_color = "#10b981" if pct>60 else "#f59e0b" if pct>30 else "#ef4444"
        label = venue.replace(" Stadium","").replace("ATT ","AT&T ")
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
            <span style="color:#9ca3af;font-size:12px;min-width:170px;">{label}</span>
            <div style="flex:1;background:#1f2937;border-radius:4px;height:8px;">
                <div style="width:{pct}%;background:{bar_color};height:8px;border-radius:4px;"></div>
            </div>
            <span style="color:#f9fafb;font-size:12px;min-width:55px;">{count}/{total_v}</span>
        </div>""", unsafe_allow_html=True)

# ── TAB 4: Audit Trail ────────────────────────────────────────────────────────
with tab4:
    st.markdown("### 📋 Full Audit Log")
    st.caption("Every agent action and human decision — immutable record in MongoDB")

    f1,f2 = st.columns(2)
    with f1:
        actor_filter = st.selectbox("Filter by actor",
            ["All","Gemini Agent","Ops Commander","System"])
    with f2:
        type_filter = st.selectbox("Filter by action type",
            ["All","agent_detected","agent_classified","agent_routed","agent_drafted",
             "volunteers_dispatched","human_approved","human_overridden","resolved"])

    all_audit = get_all_audit()
    if actor_filter != "All":
        all_audit = [e for e in all_audit if actor_filter.lower() in e.get("actor","").lower()]
    if type_filter != "All":
        all_audit = [e for e in all_audit if e.get("action_type") == type_filter]

    st.caption(f"Showing {len(all_audit)} entries")
    st.divider()

    if not all_audit:
        st.info("No audit entries yet. Run the agent to start logging.")
    else:
        for entry in all_audit:
            atype  = entry.get("action_type","")
            actor  = entry.get("actor","")
            ts     = entry.get("timestamp","")[:19].replace("T"," ")
            inc_id = entry.get("incident_id","—")
            icon_a = "🤖" if "agent" in atype else ("👤" if "human" in atype else ("🔵" if atype=="volunteers_dispatched" else "⚙️"))
            with st.expander(f"{icon_a}  {atype.replace('_',' ').title()}  ·  {inc_id}  ·  {ts} UTC  ·  {actor}"):
                d1,d2 = st.columns(2)
                with d1:
                    st.markdown(f"**Incident:** `{inc_id}`")
                    st.markdown(f"**Action:** `{atype}`")
                    st.markdown(f"**Actor:** {actor}")
                    st.markdown(f"**Status:** `{entry.get('status','')}`")
                with d2:
                    st.markdown(f"**Time:** {ts} UTC")
                    for k,v in entry.get("details",{}).items():
                        if k not in ["resolution","final_action","drafted_action"]:
                            st.caption(f"• {k}: {v}")

st.divider()
st.caption("⚽ FIFA 2026 Ground Zero · Gemini + Elastic MCP + MongoDB + Arize Phoenix · AI Agents Hackathon 2026")