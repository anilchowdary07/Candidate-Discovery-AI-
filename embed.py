#!/usr/bin/env python3
"""
IndiaRank AI — Embedding Pre-computation Script
===============================================
Run ONCE (offline) before rank.py:
    python embed.py --candidates ./candidates.jsonl --out ./embeddings.npz

This generates dense semantic embeddings for all 100K candidates using
sentence-transformers. The ranking step (rank.py) loads these embeddings
for fast cosine similarity at ranking time (<5 min CPU constraint).

Model choice: BAAI/bge-small-en-v1.5
- State-of-the-art retrieval model optimized for asymmetric search
- Fast on CPU (~1500 sentences/min batched)
- 512-dim embeddings, 33M params
- Explicitly trained on retrieval tasks (perfect for JD→candidate matching)

Why BGE over MiniLM:
  BGE-small outperforms all-MiniLM-L6 on BEIR retrieval benchmarks by ~8%
  and is specifically designed for retrieval/ranking (not just similarity).
  The "B" in BGE stands for BAAI, state-of-the-art in IR community.
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List, Any

import numpy as np
from sentence_transformers import SentenceTransformer
from tqdm import tqdm


# ──────────────────────────────────────────
# MODEL
# ──────────────────────────────────────────

MODEL_NAME = "BAAI/bge-small-en-v1.5"

# BGE instruction prefix for retrieval (asymmetric search)
# For queries (JD): use prefix
# For candidates (documents): no prefix needed
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


# ──────────────────────────────────────────
# TEXT BUILDER
# ──────────────────────────────────────────

# Max characters to include per candidate text (to stay within 256 tokens)
MAX_TEXT_CHARS = 1200


def build_candidate_text(candidate: Dict[str, Any]) -> str:
    """
    Build a structured text representation of a candidate for embedding.
    Truncated to MAX_TEXT_CHARS to avoid GPU/CPU memory overflows.
    Strategy: most informative signals first.
    """
    profile = candidate.get("profile", {})
    career_history = candidate.get("career_history", [])
    skills = candidate.get("skills", [])
    education = candidate.get("education", [])
    certs = candidate.get("certifications", [])

    parts = []

    # 1. Title + headline (highest signal)
    title = profile.get("current_title", "")
    headline = profile.get("headline", "")
    if title:
        parts.append(f"Current role: {title}.")
    if headline:
        parts.append(headline)

    # 2. Professional summary
    summary = profile.get("summary", "")
    if summary:
        parts.append(summary[:800])  # cap at 800 chars

    # 3. Core skills (with proficiency)
    if skills:
        advanced_skills = [
            f"{s['name']} ({s['proficiency']})"
            for s in skills
            if s.get("proficiency") in ("advanced", "expert")
        ]
        all_skills = [s["name"] for s in skills]
        if advanced_skills:
            parts.append(f"Expert/advanced skills: {', '.join(advanced_skills[:15])}.")
        elif all_skills:
            parts.append(f"Skills: {', '.join(all_skills[:15])}.")

    # 4. Career history (most recent 3 jobs, descriptions)
    sorted_jobs = sorted(
        career_history,
        key=lambda j: j.get("start_date", ""),
        reverse=True
    )[:3]
    for job in sorted_jobs:
        company = job.get("company", "")
        job_title = job.get("title", "")
        desc = job.get("description", "")[:400]
        if job_title or desc:
            parts.append(f"At {company}: {job_title}. {desc}")

    # 5. Education
    for edu in education[:2]:
        degree = edu.get("degree", "")
        field = edu.get("field_of_study", "")
        inst = edu.get("institution", "")
        tier = edu.get("tier", "")
        if degree:
            parts.append(f"{degree} in {field} from {inst} ({tier}).")

    # 6. Certifications
    if certs:
        cert_names = [c.get("name", "") for c in certs[:5] if c.get("name")]
        if cert_names:
            parts.append(f"Certifications: {', '.join(cert_names)}.")

    text = " ".join(parts)
    # Truncate to avoid memory issues with long texts
    return text[:MAX_TEXT_CHARS]


def build_jd_query() -> str:
    """
    Build a focused retrieval query from the JD.
    For BGE asymmetric search: keep this as a clear, dense query.
    """
    return """Senior AI/ML engineer with production experience building embeddings-based 
retrieval systems and vector databases. Expert in semantic search, ranking systems, 
information retrieval, FAISS, Elasticsearch, Pinecone, sentence-transformers. 
Strong Python. Has shipped recommendation or ranking systems to real users at scale. 
Experience with evaluation frameworks NDCG MRR MAP. NLP deep learning transformers 
LLM fine-tuning. Applied ML at product companies 6-8 years experience."""


# ──────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pre-compute candidate embeddings")
    parser.add_argument("--candidates", required=True, help="Path to candidates.jsonl")
    parser.add_argument("--out", default="./embeddings.npz", help="Output .npz path")
    parser.add_argument("--model", default=MODEL_NAME, help="SentenceTransformer model name")
    parser.add_argument("--batch-size", type=int, default=32, help="Embedding batch size (keep low to avoid OOM)")
    parser.add_argument("--max-candidates", type=int, default=None, help="Limit candidates (for testing)")
    args = parser.parse_args()

    print(f"[embed.py] Loading model: {args.model} (eager attention for CPU safety)")
    t0 = time.time()

    # Disable SDPA at env level before model load
    import os
    os.environ["TRANSFORMERS_NO_SDPA"] = "1"
    os.environ["ATTN_BACKEND"] = "math"

    from sentence_transformers import SentenceTransformer
    # Load with eager attention to avoid "Invalid buffer size: 6 GiB" OOM on CPU
    model = SentenceTransformer(args.model, model_kwargs={"attn_implementation": "eager"})
    # Truncate inputs to 256 tokens to prevent attention memory OOM on CPU
    model.max_seq_length = 256
    print(f"[embed.py] Model loaded in {time.time()-t0:.1f}s, max_seq_length={model.max_seq_length}")

    # Load candidates
    print(f"[embed.py] Loading candidates from {args.candidates}...")
    path = Path(args.candidates)
    candidates = []
    with open(path, "r", encoding="utf-8") as f:
        first_char = f.read(1)
        f.seek(0)
        if first_char == "[":
            candidates = json.load(f)
        else:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        candidates.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    if args.max_candidates:
        candidates = candidates[:args.max_candidates]

    print(f"[embed.py] Loaded {len(candidates):,} candidates")

    # Build texts
    print("[embed.py] Building candidate text representations...")
    candidate_ids = []
    texts = []
    for c in tqdm(candidates, desc="Building texts"):
        candidate_ids.append(c["candidate_id"])
        texts.append(build_candidate_text(c))

    # Compute embeddings — memory-safe settings
    print(f"[embed.py] Computing embeddings (batch_size={args.batch_size}, max_length=256)...")
    t1 = time.time()

    # Disable SDPA attention to avoid 6GB buffer allocation bug on CPU
    import os
    os.environ["TRANSFORMERS_NO_SDPA"] = "1"
    # Also set via torch if available
    try:
        import torch
        torch.backends.cuda.enable_flash_sdp(False)
        torch.backends.cuda.enable_mem_efficient_sdp(False)
        torch.backends.cuda.enable_math_sdp(True)
    except Exception:
        pass

    embeddings = model.encode(
        texts,
        batch_size=args.batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    elapsed = time.time() - t1
    print(f"[embed.py] Encoded {len(texts):,} in {elapsed:.1f}s ({len(texts)/elapsed:.0f}/s)")

    # Also embed the JD query
    jd_query = build_jd_query()
    print(f"[embed.py] Embedding JD query...")
    jd_embedding = model.encode(
        [BGE_QUERY_PREFIX + jd_query],
        normalize_embeddings=True,
        convert_to_numpy=True,
    )[0]

    # Save
    out_path = Path(args.out)
    np.savez_compressed(
        out_path,
        candidate_ids=np.array(candidate_ids),
        embeddings=embeddings.astype(np.float32),
        jd_embedding=jd_embedding.astype(np.float32),
    )
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"[embed.py] Saved to {out_path} ({size_mb:.1f} MB)")
    print(f"[embed.py] Shape: {embeddings.shape}")
    print(f"[embed.py] Total time: {time.time()-t0:.1f}s")
    print(f"\n✅ Done! Run ranking with:\n  python rank.py --candidates {args.candidates} --embeddings {out_path} --out submission.csv")


if __name__ == "__main__":
    main()
