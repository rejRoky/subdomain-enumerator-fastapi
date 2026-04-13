import os
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ── Config ─────────────────────────────────────────────────────────────────────

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")

st.set_page_config(
    page_title="Subdomain Enumerator",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── API helpers ────────────────────────────────────────────────────────────────

def api_start(domain: str, vt_api_key: str, resolve_dns: bool) -> dict:
    r = requests.post(
        f"{API_URL}/api/v1/enumerate",
        json={"domain": domain, "vt_api_key": vt_api_key or None, "resolve_dns": resolve_dns},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def api_get_job(job_id: str) -> dict:
    r = requests.get(f"{API_URL}/api/v1/jobs/{job_id}", timeout=10)
    r.raise_for_status()
    return r.json()


def api_list_jobs(limit: int = 20) -> list[dict]:
    r = requests.get(f"{API_URL}/api/v1/jobs", params={"limit": limit}, timeout=10)
    r.raise_for_status()
    return r.json().get("jobs", [])


def api_delete_job(job_id: str) -> None:
    requests.delete(f"{API_URL}/api/v1/jobs/{job_id}", timeout=10)


# ── Session state defaults ─────────────────────────────────────────────────────

if "job_id" not in st.session_state:
    st.session_state.job_id = None

# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔍 Subdomain\nEnumerator")
    st.caption(f"API: `{API_URL}`")
    st.markdown("---")

    st.subheader("Recent Jobs")
    try:
        jobs = api_list_jobs()
        if not jobs:
            st.caption("No jobs yet.")
        for job in jobs:
            icon = {"pending": "⏳", "running": "🔄", "completed": "✅", "failed": "❌"}.get(
                job["status"], "❓"
            )
            cols = st.columns([4, 1])
            with cols[0]:
                if st.button(
                    f"{icon} {job['domain']}",
                    key=f"btn_{job['job_id']}",
                    use_container_width=True,
                    help=job["status"],
                ):
                    st.session_state.job_id = job["job_id"]
                    st.rerun()
            with cols[1]:
                if st.button("🗑", key=f"del_{job['job_id']}", help="Delete"):
                    api_delete_job(job["job_id"])
                    if st.session_state.job_id == job["job_id"]:
                        st.session_state.job_id = None
                    st.rerun()
    except requests.exceptions.ConnectionError:
        st.warning("⚠️ Cannot reach API")

    st.markdown("---")
    st.markdown(
        f"[📖 API Docs]({API_URL}/docs)&nbsp;&nbsp;[🌸 Flower](http://localhost:5555)",
        unsafe_allow_html=True,
    )


# ── Main ───────────────────────────────────────────────────────────────────────

st.title("Subdomain Enumerator")

# ── Input form ─────────────────────────────────────────────────────────────────

with st.form("enumerate"):
    col1, col2 = st.columns([3, 2])
    with col1:
        domain = st.text_input("Domain", placeholder="example.com")
    with col2:
        vt_key = st.text_input("VirusTotal API Key", type="password", placeholder="Optional — free key")

    resolve = st.checkbox("Resolve DNS for each subdomain", value=True)
    submitted = st.form_submit_button("🚀 Start Enumeration", use_container_width=True, type="primary")

if submitted:
    if not domain.strip():
        st.error("Please enter a domain.")
    else:
        try:
            job = api_start(domain.strip(), vt_key.strip(), resolve)
            st.session_state.job_id = job["job_id"]
            st.rerun()
        except requests.exceptions.HTTPError as e:
            detail = e.response.json().get("detail", str(e))
            st.error(f"API error: {detail}")
        except requests.exceptions.ConnectionError:
            st.error("Cannot connect to the API.")

# ── Results ────────────────────────────────────────────────────────────────────

if not st.session_state.job_id:
    st.stop()

try:
    job = api_get_job(st.session_state.job_id)
except requests.exceptions.HTTPError as e:
    if e.response.status_code == 404:
        st.warning("Job not found — it may have been deleted.")
        st.session_state.job_id = None
    else:
        st.error(str(e))
    st.stop()
except requests.exceptions.ConnectionError:
    st.error("Cannot reach API.")
    st.stop()

status = job["status"]
STATUS_META = {
    "pending":   ("⏳", "Queued…"),
    "running":   ("🔄", job.get("progress", "Running…")),
    "completed": ("✅", "Done"),
    "failed":    ("❌", "Failed"),
}
icon, label = STATUS_META.get(status, ("❓", status))

st.markdown("---")
st.subheader(f"{icon} `{job['domain']}`")
cols = st.columns(4)
cols[0].caption(f"**Status:** {status.upper()}")
cols[1].caption(f"**Job ID:** `{job['job_id'][:8]}…`")
cols[2].caption(f"**Progress:** {label}")
if job.get("completed_at"):
    cols[3].caption(f"**Completed:** {job['completed_at'][:19].replace('T', ' ')} UTC")

# ── Polling ─────────────────────────────────────────────────────────────────────

if status in ("pending", "running"):
    pct = 0.15 if status == "pending" else 0.55
    st.progress(pct, text=label)
    time.sleep(2)
    st.rerun()

elif status == "failed":
    st.error(f"Enumeration failed: {job.get('error', 'Unknown error')}")
    st.stop()

# ── Completed — render results ─────────────────────────────────────────────────

result = job["result"]
live: dict  = result["live"]
dead: list  = result["dead"]
sources: dict = result["sources"]
summary: list = result["source_summary"]

# Metrics row
m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Subdomains", result["total"])
m2.metric("Live (resolved)", result["live_count"])
m3.metric("Dead / Unresolved", result["dead_count"])
m4.metric("Active Sources", sum(1 for s in summary if s["count"] > 0))

st.markdown("---")

tab_overview, tab_live, tab_dead, tab_sources = st.tabs(
    ["📊 Overview", f"✅ Live ({result['live_count']})", f"💀 Dead ({result['dead_count']})", "🔎 By Source"]
)

# ── Overview tab ───────────────────────────────────────────────────────────────
with tab_overview:
    df_summary = pd.DataFrame(summary)
    df_summary = df_summary[df_summary["count"] > 0].sort_values("count", ascending=False)

    if not df_summary.empty:
        fig = px.bar(
            df_summary,
            x="name",
            y="count",
            text="count",
            title="Subdomains Discovered per Source",
            color="count",
            color_continuous_scale="Blues",
            labels={"name": "Source", "count": "Subdomains"},
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, height=350, margin=dict(t=50))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No subdomains were found.")

# ── Live tab ───────────────────────────────────────────────────────────────────
with tab_live:
    if live:
        # Build rows with source tags
        rows = []
        for host, ip in live.items():
            src = [s for s, subs in sources.items() if host in subs]
            rows.append({"Subdomain": host, "IP Address": ip, "Sources": ", ".join(src)})
        df_live = pd.DataFrame(rows)
        st.dataframe(df_live, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download CSV",
            df_live.to_csv(index=False),
            file_name=f"{job['domain']}_live.csv",
            mime="text/csv",
        )
    else:
        st.info("No live subdomains (DNS resolution may have been disabled).")

# ── Dead tab ───────────────────────────────────────────────────────────────────
with tab_dead:
    if dead:
        df_dead = pd.DataFrame({"Subdomain": dead})
        st.dataframe(df_dead, use_container_width=True, hide_index=True)
        st.download_button(
            "⬇ Download CSV",
            df_dead.to_csv(index=False),
            file_name=f"{job['domain']}_dead.csv",
            mime="text/csv",
        )
    else:
        st.info("No dead/unresolved subdomains.")

# ── By Source tab ──────────────────────────────────────────────────────────────
with tab_sources:
    for src_name, subs in sorted(sources.items()):
        if subs:
            with st.expander(f"**{src_name}** — {len(subs)} subdomains"):
                st.dataframe(
                    pd.DataFrame({"Subdomain": subs}),
                    use_container_width=True,
                    hide_index=True,
                )
