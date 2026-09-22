"""
Utility functions for Upwork Scraper PRO
More powerful than original - adds AI scoring, hashing, URL parsing
"""
import hashlib
import re
import json
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime, timezone
from typing import Dict, Any, Optional

def parse_search_url(search_url: str) -> Dict[str, Any]:
    """Parse Upwork search URL into filter dict - same as original actor does"""
    if not search_url or "upwork.com" not in search_url:
        return {}
    try:
        parsed = urlparse(search_url)
        qs = parse_qs(parsed.query)
        filters = {}
        # q param
        if "q" in qs:
            filters["query"] = unquote(qs["q"][0])
        # Common Upwork URL params mapping
        # e.g. ?hourly_rate=10-50&job_type=hourly&contractor_tier=3
        mapping = {
            "job_type": "jobType",
            "contractor_tier": "experienceLevel",
            "hourly_rate": "hourlyRate",
            "amount": "budget",
            "duration_v3": "duration",
            "workload": "workload",
            "payment_verified": "verifiedPaymentOnly",
            "proposals": "proposals",
            "client_hires": "clientHires",
            "sort": "sort",
        }
        for url_key, input_key in mapping.items():
            if url_key in qs:
                filters[input_key] = unquote(qs[url_key][0])
        # location
        if "location" in qs:
            filters["location"] = [unquote(v) for v in qs["location"]]
        return filters
    except Exception:
        return {}

def compute_content_hash(job: Dict[str, Any]) -> str:
    """Content hash for repost detection - same logic as original"""
    content = "|".join([
        str(job.get("title", "")),
        str(job.get("description", ""))[:500],
        str(job.get("budgetAmount", "")),
        str(job.get("hourlyBudgetMin", "")),
        str(job.get("hourlyBudgetMax", "")),
        ",".join(sorted(job.get("skills", []))),
        str(job.get("jobType", "")),
    ])
    return hashlib.sha256(content.encode()).hexdigest()

def calculate_ai_scores(job: Dict[str, Any]) -> Dict[str, Any]:
    """
    PRO FEATURE: AI Lead Scoring - MORE POWERFUL than original's customJobScore
    Returns 0-100 scores to prioritize leads without spending Connects
    """
    score = 50  # base
    tier = "Medium"
    
    # Client spend boost
    spent = job.get("clientTotalSpent") or 0
    if spent >= 100000:
        score += 25
        tier = "PREMIUM"
    elif spent >= 50000:
        score += 20
        tier = "PREMIUM"
    elif spent >= 10000:
        score += 15
        tier = "Good"
    elif spent >= 1000:
        score += 5
    elif spent == 0:
        score -= 10
        tier = "Risky"

    # Payment verified
    if job.get("clientPaymentVerified"):
        score += 10
    else:
        score -= 15
        tier = "Risky" if spent < 1000 else tier

    # Rating
    rating = job.get("clientRating") or 0
    if rating >= 4.9:
        score += 10
    elif rating >= 4.5:
        score += 7
    elif rating >= 4.0:
        score += 3
    elif rating > 0 and rating < 4.0:
        score -= 5

    # Reviews
    reviews = job.get("clientReviewCount") or 0
    if reviews >= 20:
        score += 5
    elif reviews == 0 and rating == 0:
        score -= 5

    # Competition - fewer applicants = better
    applicants = job.get("totalApplicants")
    competition_score = 50
    estimated_connects = 10
    if applicants is not None:
        if applicants <= 4:
            score += 15
            competition_score = 95
            estimated_connects = 6
        elif applicants <= 9:
            score += 10
            competition_score = 80
            estimated_connects = 8
        elif applicants <= 20:
            score += 0
            competition_score = 50
            estimated_connects = 12
        else:
            score -= 10
            competition_score = 20
            estimated_connects = 16

    # Budget attractiveness
    budget = job.get("budgetAmount") or job.get("hourlyBudgetMax") or 0
    if job.get("jobType") == "FIXED" and budget >= 1000:
        score += 5
    elif job.get("jobType") == "HOURLY" and (job.get("hourlyBudgetMax") or 0) >= 50:
        score += 5

    # Hire rate (if available via enrichment)
    hire_rate = job.get("clientHireRate")
    if hire_rate is not None:
        if hire_rate >= 70:
            score += 5
        elif hire_rate < 30:
            score -= 5

    score = max(0, min(100, score))
    
    # Final tier override
    if score >= 85:
        tier = "PREMIUM"
    elif score >= 70:
        tier = "Good"
    elif score >= 50:
        tier = "Medium"
    else:
        tier = "Risky"

    return {
        "customJobScore": round(score / 20, 2),  # 0-5 scale like original
        "aiLeadScore": round(score, 1),  # 0-100 PRO
        "competitionScore": competition_score,  # 0-100
        "clientTier": tier,  # PREMIUM/Good/Medium/Risky
        "estimatedConnects": estimated_connects,
        "hireRate": hire_rate,
    }

def clean_text(text: str, max_len: int = 0) -> str:
    if not text:
        return text
    if max_len and len(text) > max_len:
        return text[:max_len] + "…"
    return text

def map_experience_level(val: str) -> str:
    mapping = {
        "EntryLevel": "EntryLevel",
        "IntermediateLevel": "IntermediateLevel", 
        "ExpertLevel": "ExpertLevel",
        "1": "EntryLevel",
        "2": "IntermediateLevel",
        "3": "ExpertLevel",
    }
    return mapping.get(val, val)

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
