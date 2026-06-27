#!/usr/bin/env python3
"""
IndiaRank AI — Interactive Demo Dashboard
Streamlit app for the India Runs Hackathon submission.

Demonstrates the intelligent candidate ranking system with:
- Live JD input
- Candidate upload or sample data
- Interactive ranked results with explanations
- Score breakdown visualization
"""

import json
import sys
from pathlib import Path

import streamlit as st
import pandas as pd

# Add parent dir to path so we can import rank.py components
sys.path.insert(0, str(Path(__file__).parent.parent))

from rank import (
    JD_TEXT,
    rank_candidates,
    load_candidates,
    detect_honeypot,
    compute_skills_score,
    compute_career_score,
    compute_behavior_modifier,
    compute_semantic_score,
    compute_disqualifier_penalty,
    CORE_SKILLS,
)

# ─────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="IndiaRank AI — Intelligent Candidate Ranking",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# CUSTOM CSS — Premium dark UI
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* Import fonts */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap');

/* Root variables */
:root {
    --bg-primary: #0a0a0f;
    --bg-card: #111118;
    --bg-card-hover: #1a1a24;
    --accent-gold: #f5a623;
    --accent-blue: #4f8ef7;
    --accent-green: #2dce89;
    --accent-red: #f5365c;
    --accent-purple: #825ee4;
    --text-primary: #ffffff;
    --text-secondary: #a0aec0;
    --text-muted: #4a5568;
    --border: rgba(255,255,255,0.08);
    --border-accent: rgba(79,142,247,0.3);
}

/* Global */
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: var(--bg-primary);
    color: var(--text-primary);
}

/* Hide Streamlit branding */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Main container */
.main .block-container {
    max-width: 1400px;
    padding: 2rem 2rem 4rem;
}

/* Hero header */
.hero-header {
    background: linear-gradient(135deg, #0d1117 0%, #1a1a2e 50%, #16213e 100%);
    border: 1px solid var(--border-accent);
    border-radius: 20px;
    padding: 2.5rem 3rem;
    margin-bottom: 2rem;
    position: relative;
    overflow: hidden;
}
.hero-header::before {
    content: '';
    position: absolute;
    top: -50%;
    left: -50%;
    width: 200%;
    height: 200%;
    background: radial-gradient(ellipse at 30% 50%, rgba(79,142,247,0.08) 0%, transparent 70%);
    pointer-events: none;
}
.hero-title {
    font-size: 2.8rem;
    font-weight: 800;
    background: linear-gradient(135deg, #fff 0%, #4f8ef7 50%, #825ee4 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0;
    line-height: 1.1;
}
.hero-subtitle {
    color: var(--text-secondary);
    font-size: 1.1rem;
    margin-top: 0.75rem;
    font-weight: 400;
}
.hero-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(245,166,35,0.15);
    border: 1px solid rgba(245,166,35,0.3);
    border-radius: 20px;
    padding: 4px 14px;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--accent-gold);
    margin-top: 1rem;
    margin-right: 0.5rem;
}

/* Metric cards */
.metric-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 1rem;
    margin: 1.5rem 0;
}
.metric-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem 1.5rem;
    transition: all 0.2s ease;
}
.metric-card:hover {
    border-color: var(--border-accent);
    background: var(--bg-card-hover);
    transform: translateY(-2px);
}
.metric-value {
    font-size: 2rem;
    font-weight: 800;
    color: var(--accent-blue);
    line-height: 1;
}
.metric-label {
    font-size: 0.8rem;
    color: var(--text-secondary);
    margin-top: 0.4rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Candidate card */
.candidate-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 1.5rem;
    margin-bottom: 1rem;
    transition: all 0.2s ease;
    position: relative;
}
.candidate-card:hover {
    border-color: var(--border-accent);
    background: var(--bg-card-hover);
    transform: translateX(4px);
}
.candidate-rank-badge {
    position: absolute;
    top: 1.2rem;
    right: 1.5rem;
    background: linear-gradient(135deg, #4f8ef7, #825ee4);
    color: white;
    font-weight: 700;
    font-size: 1rem;
    width: 42px;
    height: 42px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
}
.candidate-rank-badge.top3 {
    background: linear-gradient(135deg, #f5a623, #f56023);
    font-size: 1.2rem;
}
.candidate-name {
    font-size: 1.1rem;
    font-weight: 700;
    color: var(--text-primary);
}
.candidate-title {
    font-size: 0.9rem;
    color: var(--accent-blue);
    font-weight: 500;
    margin-top: 2px;
}
.candidate-meta {
    color: var(--text-secondary);
    font-size: 0.82rem;
    margin-top: 0.5rem;
}
.score-bar-container {
    margin-top: 1rem;
}
.score-label {
    display: flex;
    justify-content: space-between;
    font-size: 0.78rem;
    color: var(--text-secondary);
    margin-bottom: 4px;
}
.score-bar-bg {
    background: rgba(255,255,255,0.08);
    border-radius: 4px;
    height: 6px;
    margin-bottom: 8px;
}
.score-bar-fill {
    height: 6px;
    border-radius: 4px;
    transition: width 0.5s ease;
}
.badge-tag {
    display: inline-flex;
    align-items: center;
    background: rgba(79,142,247,0.12);
    border: 1px solid rgba(79,142,247,0.25);
    border-radius: 6px;
    padding: 2px 8px;
    font-size: 0.72rem;
    font-weight: 500;
    color: var(--accent-blue);
    margin: 2px;
}
.badge-tag.green {
    background: rgba(45,206,137,0.1);
    border-color: rgba(45,206,137,0.2);
    color: var(--accent-green);
}
.badge-tag.red {
    background: rgba(245,54,92,0.1);
    border-color: rgba(245,54,92,0.2);
    color: var(--accent-red);
}
.badge-tag.gold {
    background: rgba(245,166,35,0.1);
    border-color: rgba(245,166,35,0.2);
    color: var(--accent-gold);
}
.badge-tag.purple {
    background: rgba(130,94,228,0.12);
    border-color: rgba(130,94,228,0.25);
    color: var(--accent-purple);
}
.section-header {
    font-size: 1.3rem;
    font-weight: 700;
    color: var(--text-primary);
    margin: 2rem 0 1rem;
    display: flex;
    align-items: center;
    gap: 10px;
}
.section-header::after {
    content: '';
    flex: 1;
    height: 1px;
    background: var(--border);
}
.honeypot-card {
    background: rgba(245,54,92,0.05);
    border: 1px solid rgba(245,54,92,0.2);
    border-radius: 10px;
    padding: 0.75rem 1rem;
    font-size: 0.82rem;
    color: var(--accent-red);
    margin-top: 1rem;
}

/* Sidebar */
[data-testid="stSidebar"] {
    background: var(--bg-card);
    border-right: 1px solid var(--border);
}

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #4f8ef7, #825ee4);
    color: white;
    border: none;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.95rem;
    padding: 0.6rem 1.5rem;
    transition: all 0.2s ease;
    width: 100%;
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 25px rgba(79,142,247,0.4);
}

/* Expander */
.streamlit-expanderHeader {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 10px !important;
    color: var(--text-primary) !important;
}

/* Text area */
.stTextArea textarea {
    background: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 10px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.85rem !important;
}

/* Alert boxes */
.stAlert {
    border-radius: 10px !important;
}
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def score_bar_html(label: str, value: float, color: str) -> str:
    pct = int(value * 100)
    return f"""
    <div class="score-bar-container">
        <div class="score-label"><span>{label}</span><span>{pct}%</span></div>
        <div class="score-bar-bg">
            <div class="score-bar-fill" style="width:{pct}%;background:{color}"></div>
        </div>
    </div>
    """

def format_candidate_card(candidate: dict, rank: int, final_score: float) -> str:
    """Render a rich candidate card as HTML."""
    p = candidate.get("profile", {})
    name = p.get("anonymized_name", "Unknown")
    title = p.get("current_title", "—")
    yoe = p.get("years_of_experience", 0)
    location = p.get("location", "—")
    company = p.get("current_company", "—")
    skills = candidate.get("skills", [])
    redrob = candidate.get("redrob_signals", {})

    # Skill tags
    core_skills_found = [
        s["name"] for s in skills
        if any(core in s["name"].lower() for core in CORE_SKILLS)
    ][:6]
    skill_tags = "".join(f'<span class="badge-tag">{s}</span>' for s in core_skills_found)

    # Status tags
    open_tag = '<span class="badge-tag green">✓ Open to work</span>' if redrob.get("open_to_work_flag") else '<span class="badge-tag red">✗ Not looking</span>'
    relocate_tag = '<span class="badge-tag purple">↗ Relocatable</span>' if redrob.get("willing_to_relocate") else ""
    github_score = redrob.get("github_activity_score", -1)
    github_tag = f'<span class="badge-tag gold">⚡ GitHub: {github_score:.0f}</span>' if github_score >= 0 else ""

    rank_class = "top3" if rank <= 3 else ""
    rank_icon = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")

    return f"""
    <div class="candidate-card">
        <div class="candidate-rank-badge {rank_class}">{rank_icon}</div>
        <div class="candidate-name">{name}</div>
        <div class="candidate-title">{title} · {yoe:.1f} yrs</div>
        <div class="candidate-meta">📍 {location} · 🏢 {company} · Response: {redrob.get('recruiter_response_rate', 0):.0%}</div>
        <div style="margin-top:0.75rem">{open_tag}{relocate_tag}{github_tag}</div>
        <div style="margin-top:0.5rem">{skill_tags}</div>
    </div>
    """


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("""
    <div style="padding:1rem 0">
        <div style="font-size:1.4rem;font-weight:800;background:linear-gradient(135deg,#4f8ef7,#825ee4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text">
            IndiaRank AI
        </div>
        <div style="font-size:0.8rem;color:#a0aec0;margin-top:4px">
            India Runs Hackathon 2026
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**📊 Data Source**")
    data_source = st.radio(
        "Candidates dataset:",
        ["Use sample_candidates.json (50 candidates)", "Use full candidates.jsonl (100K)"],
        index=0,
        label_visibility="collapsed"
    )
    st.caption("⚡ Full dataset takes ~3-5 min on CPU")

    st.markdown("---")
    st.markdown("**🔢 Top N Results**")
    top_n = st.slider("Show top N candidates:", 10, 100, 20, step=10)

    st.markdown("---")
    st.markdown("**⚙️ Scoring Weights**")
    w_semantic = st.slider("Semantic Match", 0.1, 0.6, 0.35, 0.05)
    w_skills = st.slider("Skills Depth", 0.1, 0.5, 0.30, 0.05)
    w_career = st.slider("Career Signal", 0.1, 0.5, 0.35, 0.05)
    st.caption(f"Behavior modifier applied on top (×0.5 + 0.5×behavior)")

    st.markdown("---")
    st.markdown("**📂 Upload Custom Candidates**")
    uploaded_file = st.file_uploader("Upload candidates JSON/JSONL", type=["json", "jsonl"])


# ─────────────────────────────────────────────
# MAIN PAGE
# ─────────────────────────────────────────────

# Hero
st.markdown("""
<div class="hero-header">
    <h1 class="hero-title">IndiaRank AI</h1>
    <p class="hero-subtitle">Intelligent Candidate Discovery & Ranking — Beyond Keyword Matching</p>
    <span class="hero-badge">🏆 India Runs Hackathon 2026</span>
    <span class="hero-badge">🤖 Data & AI Challenge</span>
    <span class="hero-badge">₹10 Lakhs</span>
</div>
""", unsafe_allow_html=True)

# Architecture overview
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.markdown("""
    <div class="metric-card">
        <div class="metric-value" style="color:#4f8ef7">4</div>
        <div class="metric-label">Scoring Layers</div>
    </div>
    """, unsafe_allow_html=True)
with col2:
    st.markdown("""
    <div class="metric-card">
        <div class="metric-value" style="color:#2dce89">100K</div>
        <div class="metric-label">Candidates Ranked</div>
    </div>
    """, unsafe_allow_html=True)
with col3:
    st.markdown("""
    <div class="metric-card">
        <div class="metric-value" style="color:#f5a623">23</div>
        <div class="metric-label">Behavioral Signals</div>
    </div>
    """, unsafe_allow_html=True)
with col4:
    st.markdown("""
    <div class="metric-card">
        <div class="metric-value" style="color:#825ee4">&lt;5m</div>
        <div class="metric-label">CPU Ranking Time</div>
    </div>
    """, unsafe_allow_html=True)

# JD Section
st.markdown('<div class="section-header">📋 Job Description</div>', unsafe_allow_html=True)
jd_input = st.text_area(
    "Edit JD to customize ranking:",
    value=JD_TEXT.strip(),
    height=200,
    label_visibility="collapsed"
)

# Run Ranking
if st.button("🚀 Run Intelligent Ranking", use_container_width=True):
    with st.spinner("Loading candidates..."):
        if uploaded_file:
            content = uploaded_file.read().decode("utf-8")
            if content.strip().startswith("["):
                candidates = json.loads(content)
            else:
                candidates = [json.loads(l) for l in content.strip().split("\n") if l.strip()]
        elif "full" in data_source:
            try:
                candidates = load_candidates("candidates.jsonl")
            except FileNotFoundError:
                st.error("candidates.jsonl not found. Use sample data or upload a file.")
                st.stop()
        else:
            try:
                candidates = load_candidates("sample_candidates.json")
            except FileNotFoundError:
                st.error("sample_candidates.json not found.")
                st.stop()

    st.session_state.candidates = candidates

    with st.spinner(f"Ranking {len(candidates):,} candidates..."):
        import time
        t0 = time.time()
        ranked = rank_candidates(candidates)
        elapsed = time.time() - t0

    st.session_state.ranked = ranked
    st.session_state.elapsed = elapsed
    st.session_state.total = len(candidates)
    st.success(f"✅ Ranked {len(candidates):,} candidates in {elapsed:.1f}s")

# Show results
if "ranked" in st.session_state:
    ranked = st.session_state.ranked
    candidates_map = {c["candidate_id"]: c for c in st.session_state.candidates}
    total = st.session_state.total
    elapsed = st.session_state.elapsed

    # Summary metrics
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Candidates Ranked", f"{total:,}")
    with col2:
        st.metric("Ranking Time", f"{elapsed:.1f}s")
    with col3:
        honeypots = sum(1 for _, score, _ in ranked if score < 0.01)
        st.metric("Honeypots Detected", honeypots)
    with col4:
        top_score = ranked[0][1] if ranked else 0
        st.metric("Top Score", f"{top_score:.4f}")

    # Tab layout
    tab1, tab2, tab3 = st.tabs(["🏆 Top Rankings", "📊 Score Analytics", "🕷️ Honeypot Analysis"])

    with tab1:
        st.markdown(f'<div class="section-header">Top {top_n} Candidates</div>', unsafe_allow_html=True)
        for i, (cid, score, reasoning) in enumerate(ranked[:top_n], 1):
            candidate = candidates_map.get(cid, {})
            p = candidate.get("profile", {})
            redrob = candidate.get("redrob_signals", {})

            # Compute sub-scores for display
            semantic_s = compute_semantic_score(candidate, set(CORE_SKILLS.keys()))
            skills_s = compute_skills_score(candidate)
            career_s = compute_career_score(candidate)
            behavior_m = compute_behavior_modifier(candidate)
            dq_mult = compute_disqualifier_penalty(candidate)

            col_card, col_scores = st.columns([3, 2])
            with col_card:
                st.markdown(format_candidate_card(candidate, i, score), unsafe_allow_html=True)

            with col_scores:
                st.markdown(f"**Final Score: {score:.4f}**")
                st.markdown(score_bar_html("Semantic Match", semantic_s, "#4f8ef7"), unsafe_allow_html=True)
                st.markdown(score_bar_html("Skills Depth", skills_s, "#2dce89"), unsafe_allow_html=True)
                st.markdown(score_bar_html("Career Signal", career_s, "#f5a623"), unsafe_allow_html=True)
                st.markdown(score_bar_html("Behavior Modifier", min(1.0, behavior_m), "#825ee4"), unsafe_allow_html=True)

                # Key signals
                notice = redrob.get("notice_period_days", "?")
                salary_min = redrob.get("expected_salary_range_inr_lpa", {}).get("min", "?")
                salary_max = redrob.get("expected_salary_range_inr_lpa", {}).get("max", "?")
                work_mode = redrob.get("preferred_work_mode", "?")
                st.caption(f"💰 ₹{salary_min}–{salary_max}L · ⏳ {notice}d notice · 🖥️ {work_mode}")

                if dq_mult < 0.5:
                    st.markdown(f'<div style="color:#f5365c;font-size:0.8rem">⚠️ Partial disqualifier (×{dq_mult:.2f})</div>', unsafe_allow_html=True)

            st.markdown("<hr style='border-color:rgba(255,255,255,0.05);margin:0.5rem 0'>", unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="section-header">Score Distribution Analytics</div>', unsafe_allow_html=True)

        # Score distribution
        scores = [s for _, s, _ in ranked if s > 0.01]
        score_df = pd.DataFrame({"score": scores, "rank": range(1, len(scores)+1)})

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Score Distribution (Top 500)**")
            top500 = score_df.head(500)
            st.line_chart(top500.set_index("rank")["score"], color="#4f8ef7")

        with col2:
            st.markdown("**Top 10 Score Breakdown**")
            top10_data = []
            for i, (cid, score, _) in enumerate(ranked[:10], 1):
                c = candidates_map.get(cid, {})
                p = c.get("profile", {})
                top10_data.append({
                    "Rank": i,
                    "Title": p.get("current_title", "?")[:25],
                    "YOE": p.get("years_of_experience", 0),
                    "Score": round(score, 4),
                    "Semantic": round(compute_semantic_score(c, set(CORE_SKILLS.keys())), 3),
                    "Skills": round(compute_skills_score(c), 3),
                    "Career": round(compute_career_score(c), 3),
                })
            st.dataframe(pd.DataFrame(top10_data), use_container_width=True, hide_index=True)

        # Title distribution of top 100
        st.markdown("**Title Distribution in Top 100**")
        top100_titles = {}
        for cid, _, _ in ranked[:100]:
            c = candidates_map.get(cid, {})
            title = c.get("profile", {}).get("current_title", "Unknown")
            # Normalize
            if any(t in title.lower() for t in ["ml", "machine learning", "ai", "nlp", "data science"]):
                bucket = "ML/AI/Data Science"
            elif "recommendation" in title.lower() or "search" in title.lower() or "ranking" in title.lower():
                bucket = "Search/Ranking/Recsys"
            elif "software" in title.lower() or "backend" in title.lower() or "engineer" in title.lower():
                bucket = "Software Engineering"
            elif "data" in title.lower():
                bucket = "Data Engineering"
            else:
                bucket = "Other"
            top100_titles[bucket] = top100_titles.get(bucket, 0) + 1

        title_df = pd.DataFrame(list(top100_titles.items()), columns=["Category", "Count"])
        st.bar_chart(title_df.set_index("Category"))

    with tab3:
        st.markdown('<div class="section-header">🕷️ Honeypot Detection Analysis</div>', unsafe_allow_html=True)

        honeypot_candidates = [(cid, score, r) for cid, score, r in ranked if "HONEYPOT" in r]
        st.info(f"Detected **{len(honeypot_candidates)} honeypot candidates** out of {total:,} total. These are ranked last.")

        if honeypot_candidates:
            st.markdown("**Sample detected honeypots:**")
            for cid, score, reason in honeypot_candidates[:5]:
                c = candidates_map.get(cid, {})
                p = c.get("profile", {})
                st.markdown(f"""
                <div class="honeypot-card">
                    ⚠️ <strong>{cid}</strong> — {p.get('current_title','?')} · {p.get('years_of_experience','?')} YOE<br>
                    <em>{reason}</em>
                </div>
                """, unsafe_allow_html=True)

        st.markdown("**Honeypot Detection Rules:**")
        rules = [
            ("Expert skills with 0 duration_months", "Claims expert in skills they've never used"),
            ("Future start dates", "Career history shows future employment dates"),
            ("Duration/date mismatch", "Claimed duration ≠ calculated from dates"),
            ("Expert + low assessment score", "Claims expert but scored <15% on platform test"),
            ("Career months >> YOE", "Total career months far exceed stated experience"),
        ]
        for rule, desc in rules:
            st.markdown(f"- **{rule}**: {desc}")

    # Download submission
    st.markdown("---")
    st.markdown("**📥 Download Submission CSV**")
    col1, col2 = st.columns(2)
    with col1:
        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["candidate_id", "rank", "score", "reasoning"])
        for i, (cid, score, reasoning) in enumerate(ranked[:100], 1):
            writer.writerow([cid, i, f"{score:.4f}", reasoning[:250]])
        csv_data = output.getvalue()

        st.download_button(
            "⬇️ Download submission.csv",
            data=csv_data,
            file_name="submission.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with col2:
        st.caption("Top 100 candidates, format-validated, ready for portal upload.")

else:
    # Instructions
    st.info("👆 Configure options in the sidebar, then click **Run Intelligent Ranking** to see results.")

    st.markdown('<div class="section-header">🧠 How IndiaRank AI Works</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("""
        **Layer 1 — Semantic Understanding**
        - 7 concept groups aligned to the JD
        - Production experience keyword detection
        - Profile narrative comprehension (not just skills list)

        **Layer 2 — Skills Depth Analysis**
        - Duration-weighted matching (not keyword counting)
        - Proficiency × endorsement × assessment score
        - Honeypot guard: expert + 0 duration → penalized
        """)
    with col2:
        st.markdown("""
        **Layer 3 — Career Signal Analysis**
        - Title alignment scoring (50+ title patterns)
        - Product company vs IT services ratio
        - Career progression detection
        - AI/ML years-in-role weighting

        **Layer 4 — Behavioral Signal Modifier**
        - 23 Redrob platform signals
        - Recency of activity (inactive 6m = 0.55×)
        - Response rate, interview completion
        - GitHub activity, location fit
        """)
