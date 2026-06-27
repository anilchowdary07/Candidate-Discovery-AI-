#!/usr/bin/env python3
"""
IndiaRank AI — Intelligent Candidate Ranking System
====================================================
India Runs Hackathon 2026 — Data & AI Challenge

REPRODUCE COMMAND:
    python rank.py --candidates ./candidates.jsonl --out ./submission.csv

For best results, run embed.py first (offline pre-computation):
    python embed.py --candidates ./candidates.jsonl --out ./embeddings.npz
    python rank.py --candidates ./candidates.jsonl --embeddings ./embeddings.npz --out ./submission.csv

ARCHITECTURE:
    5 scoring layers, NDCG@10 optimized:

    Layer 1 — Honeypot Detection        → Score = 0.001 (ranked last)
    Layer 2 — Disqualifier Penalty      → Multiplier 0.05–1.0
    Layer 3 — Embedding Similarity      → 0.0–1.0 (BGE cosine sim, 40% weight)
    Layer 4 — Skills Depth              → 0.0–1.0 (30% weight)
    Layer 5 — Career Signal             → 0.0–1.0 (30% weight)
    Modifier — Behavioral Signal        → ×(0.4 + 0.6×behavior)

SCORING FORMULA:
    raw  = 0.40 × embedding_sim + 0.30 × skills_score + 0.30 × career_score
    final = raw × (0.4 + 0.6 × behavior_modifier) × disqualifier_mult

KEY INSIGHTS FROM THE JD:
    "The right answer involves reasoning about the gap between what the JD says
     and what the JD means."
    "A candidate who has all the AI keywords listed but title is Marketing Manager
     is not a fit."
    "A perfect-on-paper candidate who hasn't logged in for 6 months and has a 5%
     response rate is, for hiring purposes, not actually available."
"""

import argparse
import csv
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ============================================================
# JD TEXT (for reference + keyword fallback scoring)
# ============================================================

JD_TEXT = """
Senior AI/ML Engineer — Redrob Intelligence Layer

Role: Own the intelligence layer (ranking, retrieval, matching) of Redrob's product.
Experience: 5-9 years preferred (4-5 years in applied ML/AI at product companies).
Location: Pune/Noida preferred; Hyderabad, Mumbai, Delhi NCR welcome.
Notice period: Prefer sub-30-day. 30+ day candidates in scope but higher bar.

MUST HAVES:
- Production experience with embeddings-based retrieval systems (sentence-transformers,
  OpenAI embeddings, BGE, E5, or similar) deployed to real users.
  Handling embedding drift, index refresh, retrieval-quality regression in production.
- Production experience with vector databases / hybrid search (Pinecone, Weaviate,
  Qdrant, Milvus, OpenSearch, Elasticsearch, FAISS, or similar).
- Strong Python — code quality matters.
- Hands-on experience designing evaluation frameworks for ranking systems
  (NDCG, MRR, MAP, offline-to-online correlation, A/B test interpretation).

NICE TO HAVE:
- LLM fine-tuning (LoRA, QLoRA, PEFT)
- Learning-to-rank (XGBoost, neural LTR)
- HR-tech / recruiting / marketplace experience
- Open-source AI/ML contributions
- Distributed systems / large-scale inference

EXPLICIT DISQUALIFIERS:
- Pure research (no production deployment)
- AI experience = only <12-month LangChain/OpenAI wrappers
- Senior eng who hasn't written prod code in 18 months
- Entire career at IT services (TCS, Infosys, Wipro, Accenture, Cognizant, Capgemini)
  without product company experience
- Primary expertise CV/speech/robotics without significant NLP/IR

IDEAL PROFILE:
- 6-8 years total, 4-5 at applied ML at product companies
- Shipped end-to-end ranking/search/recommendation at scale
- Strong opinions: hybrid vs dense retrieval, offline vs online eval, fine-tune vs prompt
"""

# JD query for BGE embedding (optimized for retrieval)
JD_EMBEDDING_QUERY = """Senior ML engineer production embeddings retrieval vector search ranking 
recommendation system FAISS Elasticsearch Pinecone sentence-transformers NDCG evaluation 
Python NLP transformers LLM fine-tuning product company 6-8 years applied ML"""

# ============================================================
# SKILL TAXONOMY — weighted by JD importance
# ============================================================

CORE_SKILLS = {
    # Tier 1: Must-have (weight 4.0)
    "embeddings": 4.0, "embedding": 4.0, "dense retrieval": 4.0,
    "vector search": 4.0, "semantic search": 4.0, "hybrid search": 4.0,
    "information retrieval": 4.0, "retrieval": 4.0,
    "ranking systems": 4.0, "ranking": 3.5, "learning to rank": 4.0, "ltr": 3.5,
    "sentence transformers": 4.0, "sentence-transformers": 4.0,
    "faiss": 4.0, "ndcg": 4.0, "mrr": 3.5, "map": 3.0,
    "evaluation framework": 4.0, "offline evaluation": 3.5,

    # Tier 1: Vector databases (weight 3.5)
    "elasticsearch": 3.5, "opensearch": 3.5,
    "pinecone": 3.5, "weaviate": 3.5, "qdrant": 3.5, "milvus": 3.5,
    "vector database": 3.5, "vector db": 3.5,
    "bm25": 3.5, "inverted index": 3.0,

    # Tier 1: Recommendation (weight 3.5)
    "recommendation systems": 3.5, "recommendation": 3.0, "recsys": 3.5,
    "collaborative filtering": 3.0, "personalization": 2.5,

    # Tier 2: Core ML/NLP (weight 3.0)
    "nlp": 3.0, "natural language processing": 3.0,
    "transformers": 3.0, "bert": 2.5, "llm": 2.5, "large language models": 2.5,
    "rag": 2.5, "retrieval augmented": 3.0,
    "python": 3.0, "machine learning": 2.5, "deep learning": 2.5,

    # Tier 2: BGE / E5 / specific embedding models (weight 3.0)
    "bge": 3.0, "e5": 2.5, "openai embeddings": 3.0,
    "cross-encoder": 3.0, "bi-encoder": 3.0, "reranking": 3.5, "re-ranking": 3.5,

    # Tier 3: Nice-to-have (weight 2.0)
    "lora": 2.0, "qlora": 2.0, "peft": 2.0, "fine-tuning": 2.0, "fine tuning": 2.0,
    "xgboost": 2.0, "pytorch": 2.0, "tensorflow": 2.0,
    "a/b testing": 2.0, "ab testing": 2.0, "experimentation": 1.5,
    "mlops": 2.0, "model serving": 2.0, "model deployment": 2.0,
    "distributed systems": 2.0, "kafka": 1.5, "spark": 1.5,
    "open source": 1.5, "github": 1.5,

    # Tier 4: Supporting (weight 1.5)
    "data science": 1.5, "statistics": 1.5, "sql": 1.0,
    "aws": 1.0, "gcp": 1.0, "azure": 1.0,
    "docker": 1.0, "kubernetes": 1.0,
    "api": 0.8, "flask": 0.8, "fastapi": 0.8,
    "airflow": 1.0, "dbt": 0.8,
}

# Title alignment scores (how well does the title match the role?)
TITLE_SCORES = {
    # Perfect fit (1.0)
    "machine learning engineer": 1.0, "ml engineer": 1.0,
    "senior machine learning engineer": 1.0, "lead ml engineer": 1.0,
    "staff machine learning engineer": 1.0, "principal ml engineer": 1.0,
    "ai engineer": 0.95, "senior ai engineer": 0.95, "lead ai engineer": 0.95,
    "nlp engineer": 0.95, "senior nlp engineer": 0.95,
    "applied scientist": 0.90, "senior applied scientist": 0.90,
    "applied ml engineer": 0.95, "applied machine learning": 0.95,
    "research engineer": 0.85, "ml research engineer": 0.90,
    "search engineer": 0.95, "ranking engineer": 1.0,
    "recommendation engineer": 1.0, "recommendation systems engineer": 1.0,
    "information retrieval engineer": 1.0,
    "junior machine learning engineer": 0.70, "junior ml engineer": 0.70,

    # Good fit (0.6–0.8)
    "data scientist": 0.70, "senior data scientist": 0.75, "lead data scientist": 0.75,
    "backend engineer": 0.50, "senior backend engineer": 0.55,
    "software engineer": 0.45, "senior software engineer": 0.50,
    "staff engineer": 0.55, "principal engineer": 0.55,
    "ai researcher": 0.75, "ml researcher": 0.75, "research scientist": 0.75,
    "data engineer": 0.45, "senior data engineer": 0.50,
    "cloud engineer": 0.35, "devops engineer": 0.30,
    "full stack developer": 0.30, "full stack engineer": 0.30,

    # Partial fit (0.1–0.4)
    "software developer": 0.35, "developer": 0.30,
    "tech lead": 0.40, "engineering manager": 0.35,
    "product manager": 0.25, "project manager": 0.20,
    "analytics engineer": 0.40, "business intelligence": 0.25,
    "qa engineer": 0.20, "test engineer": 0.15,
    "java developer": 0.25, ".net developer": 0.20, "mobile developer": 0.15,

    # Hard disqualifier titles (0.0–0.1)
    "marketing manager": 0.0, "marketing": 0.0,
    "sales executive": 0.0, "sales manager": 0.0, "sales": 0.0,
    "hr manager": 0.0, "human resources": 0.0, "recruiter": 0.0,
    "content writer": 0.0, "content creator": 0.0,
    "graphic designer": 0.0, "ui designer": 0.0, "ux designer": 0.05,
    "accountant": 0.0, "finance": 0.05,
    "civil engineer": 0.0, "mechanical engineer": 0.0,
    "electrical engineer": 0.05, "chemical engineer": 0.0,
    "customer support": 0.0, "customer success": 0.05,
    "operations manager": 0.10, "business analyst": 0.15,
}

# IT services companies — career-long tenure without product company = disqualifier
IT_SERVICES_COMPANIES = {
    "tcs", "tata consultancy", "infosys", "wipro", "accenture", "cognizant",
    "capgemini", "hcl", "tech mahindra", "hexaware", "mphasis", "kpit",
    "l&t infotech", "ltimindtree", "mindtree", "igate", "mastech",
    "ntt data", "dxc technology", "unisys", "fujitsu", "cgi"
}

# Career description keywords that signal PRODUCTION ML experience
PRODUCTION_ML_KEYWORDS = [
    "deployed", "production", "shipped", "at scale", "real users", "live system",
    "latency", "throughput", "serving", "inference", "online", "A/B test",
    "experiment", "monitoring", "drift", "retraining", "pipeline",
    "recommendation", "ranking", "retrieval", "search", "embedding",
    "similarity", "vector", "index", "faiss", "elasticsearch", "pinecone",
]

# Computer vision / speech keywords — if ONLY these without NLP/IR = disqualifier
CV_SPEECH_ONLY = {
    "computer vision", "image classification", "object detection",
    "image segmentation", "yolo", "opencv", "video analysis",
    "speech recognition", "text-to-speech", "tts", "audio processing",
    "asr", "speech synthesis", "speaker identification",
    "robotics", "ros", "slam", "autonomous driving"
}
NLP_IR_KEYWORDS = {
    "nlp", "natural language", "retrieval", "ranking", "recommendation",
    "information retrieval", "semantic", "embedding", "bert", "transformers",
    "text", "language model", "llm", "rag", "search engine"
}

# ============================================================
# HONEYPOT DETECTION — 8 rules
# ============================================================

def detect_honeypot(candidate: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Detect honeypot candidates with impossible/inconsistent profiles.
    Returns (is_honeypot, reason).

    The spec says ~80 honeypots exist. We must NOT rank them top-10.
    8 detection rules cover the patterns described in the spec.
    """
    profile = candidate.get("profile", {})
    yoe = profile.get("years_of_experience", 0)
    skills = candidate.get("skills", [])
    career_history = candidate.get("career_history", [])
    redrob = candidate.get("redrob_signals", {})
    assessment_scores = redrob.get("skill_assessment_scores", {})

    flags = []
    today = date.today()

    # Rule 1: Expert in 5+ skills with 0 duration_months
    zero_dur_experts = [s for s in skills
                        if s.get("proficiency") in ("expert", "advanced")
                        and s.get("duration_months", 0) == 0]
    if len(zero_dur_experts) >= 5:
        flags.append(f"R1:{len(zero_dur_experts)} adv/expert skills with 0 duration")

    # Rule 2: Future start dates in career history
    for job in career_history:
        start = job.get("start_date", "")
        if start:
            try:
                sd = datetime.strptime(start, "%Y-%m-%d").date()
                if sd > today:
                    flags.append(f"R2:future start date {start}")
                    break
            except (ValueError, TypeError):
                pass

    # Rule 3: duration_months inconsistent with actual dates (>24-month gap)
    date_mismatch_count = 0
    for job in career_history:
        start = job.get("start_date", "")
        end = job.get("end_date", "")
        claimed = job.get("duration_months", 0)
        if start and end and claimed > 0:
            try:
                sd = datetime.strptime(start, "%Y-%m-%d").date()
                ed = datetime.strptime(end, "%Y-%m-%d").date()
                actual = max(0, (ed.year - sd.year) * 12 + (ed.month - sd.month))
                if abs(actual - claimed) > 24:
                    date_mismatch_count += 1
            except (ValueError, TypeError):
                pass
    if date_mismatch_count >= 2:
        flags.append(f"R3:{date_mismatch_count} jobs with >24mo date/duration mismatch")

    # Rule 4: Expert + platform assessment score < 15
    for s in skills:
        if s.get("proficiency") == "expert":
            sname = s.get("name", "").lower()
            for aname, score in assessment_scores.items():
                if aname.lower() in sname or sname in aname.lower():
                    if score < 15:
                        flags.append(f"R4:expert {s['name']} but assessment={score:.0f}")
                        break

    # Rule 5: Total skill duration months >> realistic (3 concurrent skills × YOE × 12)
    if yoe > 1:
        total_skill_months = sum(s.get("duration_months", 0) for s in skills)
        max_realistic = yoe * 12 * 4  # generous: 4 skills concurrently
        if total_skill_months > max(500, max_realistic) and len(skills) > 15:
            flags.append(f"R5:total_skill_months={total_skill_months} >> YOE={yoe}")

    # Rule 6: Career history total >> stated YOE (by large margin)
    if yoe > 0 and career_history:
        total_career_months = sum(j.get("duration_months", 0) for j in career_history)
        if total_career_months > yoe * 12 * 3:
            flags.append(f"R6:career_months={total_career_months} >> YOE={yoe}")

    # Rule 7: YOE stated as high but career history shows very recent start only
    if yoe >= 5 and career_history:
        all_starts = []
        for job in career_history:
            start = job.get("start_date", "")
            if start:
                try:
                    sd = datetime.strptime(start, "%Y-%m-%d").date()
                    all_starts.append(sd)
                except (ValueError, TypeError):
                    pass
        if all_starts:
            earliest = min(all_starts)
            career_years = (today - earliest).days / 365
            if career_years < yoe * 0.4:  # career history covers <40% of stated YOE
                flags.append(f"R7:career_span={career_years:.1f}yr but YOE={yoe}")

    # Rule 8: Skill proficiency all "expert" across diverse fields (impossible breadth)
    expert_skills = [s for s in skills if s.get("proficiency") == "expert"]
    if len(expert_skills) >= 12:
        flags.append(f"R8:{len(expert_skills)} expert skills claimed (impossible breadth)")

    # Decision: 2+ flags = honeypot
    if len(flags) >= 2:
        return True, f"HONEYPOT: {'; '.join(flags[:3])}"
    elif len(flags) == 1 and any(k in flags[0] for k in ["R2:", "R4:", "R8:"]):
        return True, f"HONEYPOT: {flags[0]}"  # single strong signal
    return False, ""


# ============================================================
# DISQUALIFIER CHECK
# ============================================================

def compute_disqualifier_multiplier(candidate: Dict[str, Any]) -> Tuple[float, str]:
    """
    Returns (multiplier, reason). Multiplier 0.05 = nearly disqualified, 1.0 = clean.
    Based on explicit JD disqualifiers.
    """
    profile = candidate.get("profile", {})
    career_history = candidate.get("career_history", [])
    skills = candidate.get("skills", [])

    current_title = profile.get("current_title", "").lower().strip()
    skill_names_lower = {s.get("name", "").lower() for s in skills}

    mult = 1.0
    reasons = []

    # Check 1: Title is a hard disqualifier
    title_score = _get_title_score(current_title)
    if title_score == 0.0:
        mult = min(mult, 0.05)
        reasons.append(f"hard-disqualifier title: {profile.get('current_title','?')}")
    elif title_score < 0.15:
        mult = min(mult, 0.25)
        reasons.append(f"off-domain title: {profile.get('current_title','?')}")

    # Check 2: Entire career in IT services companies
    if career_history:
        services_months = 0
        product_months = 0
        for job in career_history:
            co = job.get("company", "").lower()
            dur = job.get("duration_months", 0)
            is_services = any(s in co for s in IT_SERVICES_COMPANIES)
            if is_services:
                services_months += dur
            else:
                product_months += dur
        total = services_months + product_months
        if total > 0:
            services_ratio = services_months / total
            if services_ratio >= 0.95 and total >= 36:
                mult = min(mult, 0.45)
                reasons.append("career 95%+ IT services, no product company")
            elif services_ratio >= 0.80 and total >= 24:
                mult = min(mult, 0.70)

    # Check 3: CV/Speech only without any NLP/IR
    has_cv_speech = bool(cv_speech_lower := {s.lower() for s in CV_SPEECH_ONLY} & skill_names_lower)
    has_nlp_ir = any(kw in " ".join(skill_names_lower) for kw in NLP_IR_KEYWORDS)
    if has_cv_speech and not has_nlp_ir:
        mult = min(mult, 0.55)
        reasons.append("CV/speech-only domain without NLP/IR exposure")

    reason_str = "; ".join(reasons) if reasons else "no disqualifiers"
    return max(0.05, mult), reason_str


def _get_title_score(title_lower: str) -> float:
    """Look up or estimate title alignment score."""
    # Exact match
    if title_lower in TITLE_SCORES:
        return TITLE_SCORES[title_lower]
    # Partial match
    best = 0.0
    for known_title, score in TITLE_SCORES.items():
        if known_title in title_lower or title_lower in known_title:
            best = max(best, score)
    # Generic fallback
    if best == 0.0:
        if any(k in title_lower for k in ["engineer", "scientist", "developer", "architect"]):
            best = 0.30
        elif any(k in title_lower for k in ["analyst", "consultant", "specialist"]):
            best = 0.20
        elif any(k in title_lower for k in ["manager", "director", "head", "lead"]):
            best = 0.15
    return best


# ============================================================
# SKILLS SCORING
# ============================================================

def compute_skills_score(candidate: Dict[str, Any]) -> float:
    """
    Taxonomy-weighted, depth-aware skills scoring.
    Rewards: duration × proficiency × (1 + assessment_bonus + endorsement_bonus)
    Punishes: keyword stuffing (high proficiency + zero duration)
    """
    skills = candidate.get("skills", [])
    redrob = candidate.get("redrob_signals", {})
    assessment_scores = redrob.get("skill_assessment_scores", {})

    if not skills:
        return 0.0

    total = 0.0

    for skill in skills:
        name = skill.get("name", "").lower().strip()
        proficiency = skill.get("proficiency", "beginner")
        endorsements = min(100, skill.get("endorsements", 0))
        duration = skill.get("duration_months", 0)

        # Find best matching taxonomy weight
        weight = 0.0
        for core, w in CORE_SKILLS.items():
            if core in name or name in core:
                weight = max(weight, w)
            elif len(core) >= 4 and name.startswith(core[:4]):
                weight = max(weight, w * 0.8)
        if weight == 0:
            continue

        # Proficiency multiplier
        prof_mult = {
            "beginner": 0.25, "intermediate": 0.55,
            "advanced": 0.80, "expert": 1.00
        }.get(proficiency, 0.25)

        # Duration multiplier — log scale, cap at 60 months
        if duration == 0 and proficiency in ("advanced", "expert"):
            dur_mult = 0.05  # honeypot guard — claimed expert with zero use
        elif duration == 0:
            dur_mult = 0.15
        else:
            dur_mult = min(1.0, math.log1p(duration) / math.log1p(60))

        # Assessment score bonus (up to +35%)
        assess_bonus = 0.0
        for aname, ascore in assessment_scores.items():
            if aname.lower() in name or name in aname.lower():
                assess_bonus = (ascore / 100) * 0.35
                break

        # Endorsement bonus (up to +15%)
        endorse_bonus = (endorsements / 100) * 0.15

        contribution = weight * prof_mult * dur_mult * (1.0 + assess_bonus + endorse_bonus)
        total += contribution

    # Normalize against a fixed maximum achievable by an IDEAL candidate
    # Ideal: expert (1.0) × duration 60mo (1.0) × all Tier1 skills
    # Sum of top-12 Tier1 weights ≈ 48.0 → achievable by ideal candidate
    IDEAL_SCORE = 48.0
    raw = total / IDEAL_SCORE
    return min(1.0, raw)


# ============================================================
# CAREER SCORING
# ============================================================

def compute_career_score(candidate: Dict[str, Any]) -> float:
    """
    Holistic career signal analysis.
    Components:
    - Title alignment (30%)
    - YOE fit (20%)
    - Product vs IT-services ratio (20%)
    - AI/ML depth in career descriptions (20%)
    - Career progression signal (10%)
    """
    profile = candidate.get("profile", {})
    career_history = candidate.get("career_history", [])
    yoe = profile.get("years_of_experience", 0)
    current_title = profile.get("current_title", "").lower()

    score = 0.0

    # ── Title alignment (30%) ──
    title_score = _get_title_score(current_title)
    score += title_score * 0.30

    # ── YOE fit (20%) ──
    # JD: 5-9 years, ideal 6-8
    if 6 <= yoe <= 8:
        yoe_mult = 1.00
    elif 5 <= yoe < 6 or 8 < yoe <= 10:
        yoe_mult = 0.85
    elif 4 <= yoe < 5 or 10 < yoe <= 12:
        yoe_mult = 0.70
    elif 3 <= yoe < 4 or 12 < yoe <= 14:
        yoe_mult = 0.55
    elif 2 <= yoe < 3 or 14 < yoe <= 17:
        yoe_mult = 0.40
    elif yoe < 2:
        yoe_mult = 0.15
    else:  # >17
        yoe_mult = 0.35
    score += yoe_mult * 0.20

    # ── Product company ratio (20%) ──
    total_months = sum(j.get("duration_months", 0) for j in career_history)
    product_months = 0.0
    for job in career_history:
        co = job.get("company", "").lower()
        dur = job.get("duration_months", 0)
        industry = job.get("industry", "").lower()
        is_services = any(s in co for s in IT_SERVICES_COMPANIES)
        if not is_services:
            # Credit by industry type
            if any(pi in industry for pi in ["saas", "software", "technology", "fintech",
                                              "edtech", "healthtech", "ecommerce", "startup",
                                              "ai", "machine learning", "internet", "product"]):
                product_months += dur
            else:
                product_months += dur * 0.75  # partial credit

    product_ratio = (product_months / total_months) if total_months > 0 else 0.5
    score += product_ratio * 0.20

    # ── AI/ML depth in career descriptions (20%) ──
    ml_months = 0.0
    for job in career_history:
        desc = (job.get("description", "") + " " + job.get("title", "")).lower()
        prod_hits = sum(1 for kw in PRODUCTION_ML_KEYWORDS if kw in desc)
        ml_score_for_job = min(1.0, prod_hits / 6)  # 6+ hits = full credit
        ml_months += job.get("duration_months", 0) * ml_score_for_job

    ml_ratio = (ml_months / total_months) if total_months > 0 else 0.0
    score += ml_ratio * 0.20

    # ── Career progression (10%) ──
    seniority_kws = ["senior", "lead", "principal", "staff", "head", "director"]
    if len(career_history) >= 2:
        sorted_jobs = sorted(career_history, key=lambda j: j.get("start_date", ""))
        first_half = sorted_jobs[:len(sorted_jobs)//2]
        second_half = sorted_jobs[len(sorted_jobs)//2:]
        early_seniority = sum(1 for j in first_half if any(k in j.get("title","").lower() for k in seniority_kws))
        late_seniority = sum(1 for j in second_half if any(k in j.get("title","").lower() for k in seniority_kws))
        if late_seniority > early_seniority:
            score += 0.10  # progressed upward
        elif late_seniority > 0:
            score += 0.05  # maintained seniority

    return min(1.0, score)


# ============================================================
# BEHAVIORAL MODIFIER
# ============================================================

def compute_behavior_modifier(candidate: Dict[str, Any]) -> float:
    """
    Behavioral multiplier from 23 Redrob signals.
    Range: 0.05 (ghost candidate) to 1.30 (ideal availability).
    Applied as: final = raw × (0.4 + 0.6 × behavior_modifier)
    """
    redrob = candidate.get("redrob_signals", {})
    profile = candidate.get("profile", {})
    modifier = 1.0

    # ── Availability ──
    if not redrob.get("open_to_work_flag", False):
        modifier *= 0.78

    # Last active recency
    last_active = redrob.get("last_active_date", "")
    if last_active:
        try:
            la = datetime.strptime(last_active, "%Y-%m-%d").date()
            days = (date.today() - la).days
            if days <= 7:        modifier *= 1.18
            elif days <= 30:     modifier *= 1.08
            elif days <= 60:     modifier *= 1.00
            elif days <= 90:     modifier *= 0.92
            elif days <= 180:    modifier *= 0.78
            else:                modifier *= 0.52   # 6+ months inactive = effectively unavailable
        except (ValueError, TypeError):
            pass

    # ── Responsiveness ──
    rr = redrob.get("recruiter_response_rate", 0.5)
    if rr <= 0.05:   modifier *= 0.55   # effectively unreachable
    elif rr <= 0.15: modifier *= 0.80
    elif rr <= 0.30: modifier *= 0.92
    elif rr >= 0.70: modifier *= 1.07
    elif rr >= 0.85: modifier *= 1.12

    avg_rt = redrob.get("avg_response_time_hours", 24)
    if avg_rt <= 2:    modifier *= 1.06
    elif avg_rt <= 8:  modifier *= 1.02
    elif avg_rt > 72:  modifier *= 0.92
    elif avg_rt > 120: modifier *= 0.85

    # ── Interview track record ──
    icr = redrob.get("interview_completion_rate", 0.5)
    if icr < 0.30:   modifier *= 0.82
    elif icr < 0.50: modifier *= 0.92
    elif icr >= 0.85: modifier *= 1.04

    oar = redrob.get("offer_acceptance_rate", -1)
    if oar >= 0:
        if oar < 0.20:   modifier *= 0.90
        elif oar >= 0.70: modifier *= 1.03

    # ── Profile quality ──
    completeness = redrob.get("profile_completeness_score", 50)
    modifier *= 0.75 + 0.25 * (completeness / 100)

    verified = (redrob.get("verified_email", False) and redrob.get("verified_phone", False))
    if verified: modifier *= 1.03

    if redrob.get("linkedin_connected", False): modifier *= 1.02

    # ── Location fit ──
    country = profile.get("country", "India")
    location = profile.get("location", "").lower()
    preferred_locs = ["pune", "noida", "hyderabad", "mumbai", "delhi", "gurugram",
                      "gurgaon", "bengaluru", "bangalore", "ncr"]

    if country.lower() not in ("india",):
        modifier *= 0.72
        if not redrob.get("willing_to_relocate", False):
            modifier *= 0.70
    elif any(loc in location for loc in preferred_locs[:5]):
        modifier *= 1.07

    if redrob.get("willing_to_relocate", False) and country.lower() == "india":
        modifier *= 1.03

    # ── Notice period ──
    notice = redrob.get("notice_period_days", 60)
    if notice <= 15:     modifier *= 1.10  # immediate — very attractive
    elif notice <= 30:   modifier *= 1.05
    elif notice <= 60:   modifier *= 1.00
    elif notice <= 90:   modifier *= 0.93
    else:                modifier *= 0.85

    # ── External validation ──
    github = redrob.get("github_activity_score", -1)
    if github >= 60:      modifier *= 1.10
    elif github >= 30:    modifier *= 1.05
    elif github >= 10:    modifier *= 1.01
    elif github == -1:    modifier *= 0.97  # no GitHub linked

    # ── Recruiter interest signal ──
    saved = redrob.get("saved_by_recruiters_30d", 0)
    if saved >= 10:   modifier *= 1.06
    elif saved >= 5:  modifier *= 1.03

    return max(0.05, min(1.35, modifier))


# ============================================================
# EMBEDDING-BASED SEMANTIC SCORING
# ============================================================

def load_embeddings(embeddings_path: str) -> Optional[Tuple[Dict[str, int], np.ndarray, np.ndarray]]:
    """
    Load pre-computed embeddings from embeddings.npz.
    Returns (id_to_idx, embeddings_matrix, jd_embedding) or None if not found.
    """
    path = Path(embeddings_path)
    if not path.exists():
        return None
    try:
        data = np.load(path, allow_pickle=False)
        candidate_ids = data["candidate_ids"]
        embeddings = data["embeddings"].astype(np.float32)
        jd_embedding = data["jd_embedding"].astype(np.float32)
        id_to_idx = {cid: i for i, cid in enumerate(candidate_ids)}
        return id_to_idx, embeddings, jd_embedding
    except Exception as e:
        print(f"[WARNING] Could not load embeddings: {e}", file=sys.stderr)
        return None


def compute_embedding_similarity(
    candidate_id: str,
    id_to_idx: Dict[str, int],
    embeddings: np.ndarray,
    jd_embedding: np.ndarray
) -> float:
    """
    Cosine similarity between pre-computed candidate embedding and JD embedding.
    BGE-small on this corpus: cosine sims cluster in [0.62, 0.86].
    We normalize to [0, 1] using empirical floor=0.60 and stretch the range.
    """
    idx = id_to_idx.get(candidate_id)
    if idx is None:
        return 0.0
    # L2-normalized embeddings → dot product = cosine similarity
    raw_sim = float(np.dot(jd_embedding, embeddings[idx]))
    # Empirical range for BGE-small on candidate profiles vs JD:
    # irrelevant profiles: ~0.62, relevant profiles: ~0.85+
    # Floor at 0.60, scale so 0.60→0.0, 0.85→1.0
    FLOOR = 0.60
    CEIL = 0.87
    normalized = (raw_sim - FLOOR) / (CEIL - FLOOR)
    return min(1.0, max(0.0, normalized))


def compute_keyword_semantic_score(candidate: Dict[str, Any]) -> float:
    """
    Fallback semantic scoring when embeddings not available.
    Uses TF-IDF-inspired concept group matching over all profile text.
    """
    profile = candidate.get("profile", {})
    career_history = candidate.get("career_history", [])
    skills = candidate.get("skills", [])
    certs = candidate.get("certifications", [])

    weighted_texts = [
        (profile.get("summary", ""), 3.0),
        (profile.get("headline", ""), 2.5),
    ]
    for i, job in enumerate(career_history):
        w = 2.0 if i == 0 else (1.5 if i == 1 else 1.0)
        weighted_texts.append((job.get("description", "") + " " + job.get("title", ""), w))
    for cert in certs:
        weighted_texts.append((cert.get("name", ""), 1.0))

    full_text = " ".join(t for t, _ in weighted_texts).lower()

    # 8 concept groups aligned to the JD
    concept_groups = [
        # Search / Retrieval / Ranking (core of the role)
        {"retrieval", "search", "ranking", "relevance", "information retrieval",
         "bm25", "inverted index", "lucene", "elasticsearch", "semantic search",
         "hybrid search", "re-ranking", "reranking", "dense retrieval", "sparse"},
        # Embeddings / Vectors
        {"embedding", "embeddings", "vector", "sentence transformer", "bert",
         "bge", "e5", "dense vector", "semantic vector", "encode"},
        # Recommendation Systems
        {"recommendation", "collaborative filtering", "matrix factorization",
         "user-item", "personalization", "recsys"},
        # Production ML / MLOps
        {"production", "deployed", "serving", "inference", "scale", "latency",
         "mlops", "monitoring", "drift", "a/b test", "experiment", "online"},
        # NLP / LLM
        {"nlp", "natural language", "language model", "llm", "transformer",
         "fine-tun", "lora", "rag", "text classification", "ner"},
        # Evaluation / Metrics
        {"ndcg", "mrr", "map", "precision", "recall", "evaluation",
         "benchmark", "metric", "relevance judgment", "click-through"},
        # Python / Engineering
        {"python", "code quality", "unit test", "system design", "architecture"},
        # Vector Databases
        {"faiss", "pinecone", "weaviate", "qdrant", "milvus", "vector database",
         "opensearch", "annoy", "nmslib"},
    ]

    group_scores = []
    for group in concept_groups:
        hits = sum(w for text, w in weighted_texts
                   if any(concept in text.lower() for concept in group))
        group_scores.append(min(1.0, hits / 6.0))

    # Production experience bonus
    prod_bonus = min(0.25, sum(0.05 for kw in PRODUCTION_ML_KEYWORDS if kw in full_text))

    return min(1.0, np.mean(group_scores) + prod_bonus)


# ============================================================
# MAIN RANKING FUNCTION
# ============================================================

def rank_candidates(
    candidates: List[Dict[str, Any]],
    embedding_data: Optional[Tuple] = None,
    w_sem: float = 0.50,
    w_career: float = 0.20,
    w_behavior: float = 0.30
) -> List[Tuple[str, float, str]]:
    """
    Rank all candidates. Returns [(candidate_id, score, reasoning)] sorted by score desc.
    """
    use_embeddings = embedding_data is not None
    if use_embeddings:
        id_to_idx, embeddings_matrix, jd_embedding = embedding_data
        print(f"[IndiaRank AI] Using pre-computed BGE embeddings for semantic scoring ✓",
              file=sys.stderr)
    else:
        print(f"[IndiaRank AI] Using keyword semantic scoring (run embed.py for better results)",
              file=sys.stderr)

    results = []

    for candidate in candidates:
        cid = candidate.get("candidate_id", "")

        # ── Stage 1: Honeypot detection ──
        is_honeypot, hp_reason = detect_honeypot(candidate)
        if is_honeypot:
            reasoning = _build_reasoning(candidate, 0, 0, 0, 0, 0.001, hp_reason)
            results.append((cid, 0.001, reasoning))
            continue

        # ── Stage 2: Disqualifier check ──
        dq_mult, dq_reason = compute_disqualifier_multiplier(candidate)

        # Fast path for hard disqualifiers — skip heavy computation
        if dq_mult <= 0.10:
            behavior = compute_behavior_modifier(candidate)
            final = max(0.001, 0.05 * dq_mult * (0.4 + 0.6 * behavior))
            reasoning = _build_reasoning(candidate, 0, 0, 0, behavior, final, dq_reason)
            results.append((cid, final, reasoning))
            continue

        # ── Stage 3: Score computation ──
        if use_embeddings:
            sem_score = compute_embedding_similarity(cid, id_to_idx, embeddings_matrix, jd_embedding)
        else:
            sem_score = compute_keyword_semantic_score(candidate)

        skills_score = compute_skills_score(candidate)
        career_score = compute_career_score(candidate)
        behavior_mod = compute_behavior_modifier(candidate)

        # ── Stage 4: Weighted combination (NDCG@10 optimized) ──
        if use_embeddings:
            # Derive skills weight from the remainder
            w_skills = max(0.0, 1.0 - w_sem - w_career)
            raw = w_sem * sem_score + w_skills * skills_score + w_career * career_score
        else:
            w_skills = max(0.0, 1.0 - w_sem - w_career)
            raw = w_sem * sem_score + w_skills * skills_score + w_career * career_score

        # Apply behavioral modifier dynamically based on UI weight
        w_beh_base = max(0.0, 1.0 - w_behavior)
        final = raw * (w_beh_base + w_behavior * behavior_mod)

        # Apply disqualifier penalty
        final *= dq_mult

        final = max(0.001, min(0.999, final))
        reasoning = _build_reasoning(candidate, sem_score, skills_score, career_score,
                                     behavior_mod, final, dq_reason if dq_mult < 1.0 else "")
        results.append((cid, final, reasoning))

    # Sort: descending score, ascending candidate_id for ties
    results.sort(key=lambda x: (-x[1], x[0]))
    return results


def _build_reasoning(candidate, sem_s, skills_s, career_s, behavior_m, final, extra=""):
    p = candidate.get("profile", {})
    title = p.get("current_title", "Unknown")
    yoe = p.get("years_of_experience", 0)
    skills = candidate.get("skills", [])
    redrob = candidate.get("redrob_signals", {})
    rr = redrob.get("recruiter_response_rate", 0)
    core_count = sum(1 for s in skills
                     if any(core in s.get("name", "").lower() for core in CORE_SKILLS))
    base = (f"{title} with {yoe:.1f} yrs; {core_count} AI core skills; "
            f"sem={sem_s:.2f} skills={skills_s:.2f} career={career_s:.2f} "
            f"behavior={behavior_m:.2f} final={final:.4f}.")
    if extra:
        base += f" [{extra}]"
    return base


# ============================================================
# I/O
# ============================================================

def load_candidates(path_str: str) -> List[Dict[str, Any]]:
    """Load candidates from JSONL or JSON array."""
    path = Path(path_str)
    with open(path, "r", encoding="utf-8") as f:
        first = f.read(1)
        f.seek(0)
        if first == "[":
            return json.load(f)
        else:
            candidates = []
            for line in f:
                line = line.strip()
                if line:
                    try:
                        candidates.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return candidates


def write_submission(ranked: List[Tuple[str, float, str]], out_path: str, top_n: int = 100):
    """Write top-N ranked candidates to submission CSV (per spec)."""
    path = Path(out_path)
    top = ranked[:top_n]

    # Ensure strictly non-increasing scores (validator requirement)
    adjusted = []
    prev_score = None
    epsilon = 1e-7
    for cid, score, reasoning in top:
        if prev_score is not None and score >= prev_score:
            score = prev_score - epsilon
        score = max(0.0001, score)
        adjusted.append((cid, score, reasoning))
        prev_score = score

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["candidate_id", "rank", "score", "reasoning"])
        for i, (cid, score, reasoning) in enumerate(adjusted, start=1):
            r = reasoning[:300].replace("\n", " ").replace(",", ";")
            writer.writerow([cid, i, f"{score:.6f}", r])


# ============================================================
# ENTRY POINT
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="IndiaRank AI — Intelligent Candidate Ranking System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Quick mode (keyword scoring, no embeddings):
  python rank.py --candidates ./candidates.jsonl --out ./submission.csv

  # Full mode (BGE embeddings, best quality):
  python embed.py --candidates ./candidates.jsonl --out ./embeddings.npz
  python rank.py --candidates ./candidates.jsonl --embeddings ./embeddings.npz --out ./submission.csv
        """
    )
    parser.add_argument("--candidates", required=True, help="Path to candidates.jsonl or .json")
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--embeddings", default="./embeddings.npz",
                        help="Pre-computed embeddings .npz (from embed.py). Auto-detected if exists.")
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--w-sem", type=float, default=0.50)
    parser.add_argument("--w-career", type=float, default=0.20)
    parser.add_argument("--w-behavior", type=float, default=0.30)
    args = parser.parse_args()

    # Load candidates
    if args.verbose:
        print(f"[IndiaRank AI] Loading candidates from {args.candidates}...", flush=True)
    candidates = load_candidates(args.candidates)
    if args.verbose:
        print(f"[IndiaRank AI] Loaded {len(candidates):,} candidates.", flush=True)

    # Load embeddings if available
    embedding_data = None
    emb_path = args.embeddings
    if Path(emb_path).exists():
        if args.verbose:
            print(f"[IndiaRank AI] Loading embeddings from {emb_path}...", flush=True)
        embedding_data = load_embeddings(emb_path)
        if embedding_data and args.verbose:
            _, emb_mat, _ = embedding_data
            print(f"[IndiaRank AI] Embeddings loaded: {emb_mat.shape}", flush=True)
    else:
        if args.verbose:
            print(f"[IndiaRank AI] No embeddings found at {emb_path} — using keyword scoring.")
            print(f"[IndiaRank AI] For better results: python embed.py --candidates {args.candidates} --out {emb_path}")

    # Rank
    if args.verbose:
        print(f"[IndiaRank AI] Ranking {len(candidates):,} candidates...", flush=True)
    import time
    t0 = time.time()
    ranked = rank_candidates(candidates, embedding_data, args.w_sem, args.w_career, args.w_behavior)
    elapsed = time.time() - t0

    if args.verbose:
        print(f"[IndiaRank AI] Ranked {len(candidates):,} in {elapsed:.1f}s. Writing top {args.top}...")
        print("\n--- TOP 10 CANDIDATES ---")
        for i, (cid, score, reasoning) in enumerate(ranked[:10], 1):
            print(f"  {i:2d}. {cid}  score={score:.4f}  {reasoning[:90]}")
        # Honeypot stats
        hp_count = sum(1 for _, s, _ in ranked if s <= 0.001)
        print(f"\n[IndiaRank AI] Honeypots detected: {hp_count}")

    write_submission(ranked, args.out, args.top)

    if args.verbose:
        print(f"[IndiaRank AI] ✅ Done! → {args.out} (total: {elapsed:.1f}s)")


if __name__ == "__main__":
    main()
